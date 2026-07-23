"""
LLM Client Adapters
====================
Every agent (Patient / Therapist / Evaluator) talks to a model through the
same tiny interface: `LLMClient.chat(system_prompt, messages) -> str`.
This file is the ONLY place that needs to change if a provider's SDK
changes shape.

Supported backends:
    - GeminiClient    -> Google Gemini API (google-genai SDK)      [free tier]
    - MistralClient   -> Mistral "La Plateforme" (mistralai SDK)   [free Experiment tier]
    - GroqClient      -> Groq Cloud (groq SDK, OpenAI-compatible)  [free tier - Llama-3.1-8b, Mixtral-8x7b]
    - OpenAIClient    -> OpenAI API (openai SDK)                   [paid - switch to this later]
    - HFLocalClient   -> Any local/Colab-hosted HF transformers    [MentaLLaMA, ChatCounselor, etc.]
                         checkpoint, run on a GPU (e.g. Colab T4/A100).

`messages` is always a list of {"role": "user"/"assistant", "content": str}
representing the conversation from THIS agent's point of view (i.e. the
agent that owns this client is always "assistant").
"""

from __future__ import annotations
import os
import time
from abc import ABC, abstractmethod
from typing import List, Dict, Optional


class LLMClient(ABC):
    def __init__(self, model_name: str, temperature: float = 0.7, max_retries: int = 3):
        self.model_name = model_name
        self.temperature = temperature
        self.max_retries = max_retries

    @abstractmethod
    def _call(self, system_prompt: str, messages: List[Dict[str, str]]) -> str:
        ...

    def chat(self, system_prompt: str, messages: List[Dict[str, str]]) -> str:
        """Wraps _call with basic retry/backoff for transient rate-limit errors."""
        last_err = None
        for attempt in range(self.max_retries):
            try:
                return self._call(system_prompt, messages)
            except Exception as e:  # noqa: BLE001 - deliberately broad, this is a research harness
                last_err = e
                wait = min(2 ** attempt, 20)
                print(f"[{self.__class__.__name__}] error on attempt {attempt + 1}: {e} "
                      f"-> retrying in {wait}s")
                time.sleep(wait)
        raise RuntimeError(f"{self.__class__.__name__} failed after {self.max_retries} retries: {last_err}")


# =============================================================================
# GEMINI  (free tier: https://ai.google.dev/gemini-api/docs/rate-limits)
# =============================================================================

class GeminiClient(LLMClient):
    """
    Uses Google's current `google-genai` SDK.
    pip install google-genai
    Env var: GEMINI_API_KEY
    Supports multiple keys separated by commas for rotation on rate limits.
    """

    def __init__(self, model_name: str = "gemini-2.5-flash", temperature: float = 0.7, api_key: Optional[str] = None):
        super().__init__(model_name, temperature)
        from google import genai  # local import so the package is optional
        self._genai = genai
        self._types = __import__("google.genai.types", fromlist=["types"])
        
        # Parse comma-separated keys, stripping whitespace and any surrounding quotes
        raw_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.api_keys = [k.strip().strip("'").strip('"').strip() for k in raw_key.split(",") if k.strip()]
        self.current_key_index = 0
        
        if not self.api_keys:
            self.client = genai.Client()
        else:
            self.client = genai.Client(api_key=self.api_keys[0])

    def _call(self, system_prompt: str, messages: List[Dict[str, str]]) -> str:
        # Gemini's "contents" is a flat turn sequence with role "user"/"model".
        contents = []
        for m in messages:
            role = "model" if m["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})

        tried_indices = set()
        last_exception = None

        # Loop through available keys in rotation if we hit rate limits or auth errors
        while not self.api_keys or len(tried_indices) < len(self.api_keys):
            if self.api_keys:
                idx = self.current_key_index
                tried_indices.add(idx)
                active_key = self.api_keys[idx]
            else:
                idx = None
                active_key = None

            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=self._types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=self.temperature,
                    ),
                )
                return response.text
            except Exception as e:
                last_exception = e
                err_str = str(e)
                # Check if it is a rate limit, authentication, permission, or invalid key error
                is_key_error = (
                    "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower() or
                    "401" in err_str or "UNAUTHENTICATED" in err_str or "auth" in err_str.lower() or
                    "403" in err_str or "permission" in err_str.lower() or
                    "400" in err_str or "invalid" in err_str.lower() or "not valid" in err_str.lower()
                )
                
                if is_key_error and self.api_keys and len(self.api_keys) > 1:
                    print(f"\n[GeminiClient] Error hit on key index {idx}: {err_str}")
                    
                    # If it's a rate limit, sleep briefly to cooldown
                    if any(x in err_str or x in err_str.lower() for x in ["429", "resource_exhausted", "quota"]):
                        print("[GeminiClient] Rate limit detected. Sleeping 2 seconds for cooldown...")
                        time.sleep(2)
                        
                    # Switch to next key in pool
                    self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
                    next_key = self.api_keys[self.current_key_index]
                    print(f"[GeminiClient] Rotating to key index {self.current_key_index}...")
                    self.client = self._genai.Client(api_key=next_key)
                    continue
                else:
                    # Let the outer logic handle errors if we cannot rotate
                    raise e

        # If all keys in the pool were rate-limited/invalid in this turn, prompt for a new key
        print("\n[GeminiClient] All pre-configured Gemini API keys were rate-limited or invalid in this turn.")
        try:
            import getpass
            new_key = getpass.getpass("Please enter a new Gemini API key (or press Enter to fail/retry with backoff): ").strip().strip("'").strip('"').strip()
            if new_key:
                if new_key in self.api_keys:
                    self.current_key_index = self.api_keys.index(new_key)
                    print(f"[GeminiClient] Re-using entered API key index {self.current_key_index}...")
                else:
                    self.api_keys.append(new_key)
                    self.current_key_index = len(self.api_keys) - 1
                    print(f"[GeminiClient] Added and switched to new API key...")
                self.client = self._genai.Client(api_key=self.api_keys[self.current_key_index])
                return self._call(system_prompt, messages)
        except (OSError, EOFError, ValueError) as prompt_err:
            print(f"[GeminiClient] Could not prompt for new key interactively: {prompt_err}")

        if last_exception:
            raise last_exception
        raise RuntimeError("GeminiClient failed: All keys rate-limited and no new key was provided.")


# =============================================================================
# MISTRAL  (free "Experiment" tier: https://docs.mistral.ai)
# =============================================================================

class MistralClient(LLMClient):
    """
    pip install mistralai
    Env var: MISTRAL_API_KEY
    Supports multiple keys separated by commas for rotation on rate/token limits.
    """

    def __init__(self, model_name: str = "mistral-large-latest", temperature: float = 0.7, api_key: Optional[str] = None):
        super().__init__(model_name, temperature)
        try:
            from mistralai.client import Mistral
        except ImportError:
            from mistralai import Mistral
        self._Mistral = Mistral
        
        # Parse comma-separated keys, stripping whitespace and surrounding quotes
        raw_key = api_key or os.environ.get("MISTRAL_API_KEY", "")
        self.api_keys = [k.strip().strip("'").strip('"').strip() for k in raw_key.split(",") if k.strip()]
        self.current_key_index = 0
        
        if not self.api_keys:
            self.client = Mistral()
        else:
            self.client = Mistral(api_key=self.api_keys[0])

    def _call(self, system_prompt: str, messages: List[Dict[str, str]]) -> str:
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        tried_indices = set()
        last_exception = None

        # Loop through available keys in rotation if we hit rate/limit/auth errors
        while not self.api_keys or len(tried_indices) < len(self.api_keys):
            if self.api_keys:
                idx = self.current_key_index
                tried_indices.add(idx)
            else:
                idx = None

            try:
                response = self.client.chat.complete(
                    model=self.model_name,
                    temperature=self.temperature,
                    messages=full_messages,
                )
                return response.choices[0].message.content
            except Exception as e:
                last_exception = e
                err_str = str(e)
                # Check for rate limit, token limit, or authentication errors on Mistral
                is_key_error = (
                    "429" in err_str or "rate_limit" in err_str.lower() or 
                    "limit" in err_str.lower() or "quota" in err_str.lower() or
                    "401" in err_str or "unauthenticated" in err_str.lower() or "auth" in err_str.lower() or
                    "403" in err_str or "permission" in err_str.lower() or "invalid" in err_str.lower() or
                    "unauthorized" in err_str.lower()
                )

                if is_key_error and self.api_keys and len(self.api_keys) > 1:
                    print(f"\n[MistralClient] Error hit on key index {idx}: {err_str}")
                    
                    # If it's a rate/token limit error, sleep briefly to cooldown
                    if any(x in err_str or x in err_str.lower() for x in ["429", "rate_limit", "limit", "quota"]):
                        print("[MistralClient] Rate/Token limit detected. Sleeping 2 seconds for cooldown...")
                        time.sleep(2)

                    # Switch to next key in pool
                    self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
                    next_key = self.api_keys[self.current_key_index]
                    print(f"[MistralClient] Rotating to key index {self.current_key_index}...")
                    self.client = self._Mistral(api_key=next_key)
                    continue
                else:
                    # Let the outer logic handle errors if we cannot rotate
                    raise e

        # If all keys in the pool were rate-limited or invalid in this turn, prompt for a new key
        print("\n[MistralClient] All pre-configured Mistral API keys were rate-limited or invalid in this turn.")
        try:
            import getpass
            new_key = getpass.getpass("Please enter a new Mistral API key (or press Enter to fail/retry with backoff): ").strip().strip("'").strip('"').strip()
            if new_key:
                if new_key in self.api_keys:
                    self.current_key_index = self.api_keys.index(new_key)
                    print(f"[MistralClient] Re-using entered API key index {self.current_key_index}...")
                else:
                    self.api_keys.append(new_key)
                    self.current_key_index = len(self.api_keys) - 1
                    print(f"[MistralClient] Added and switched to new API key...")
                self.client = self._Mistral(api_key=self.api_keys[self.current_key_index])
                return self._call(system_prompt, messages)
        except (OSError, EOFError, ValueError) as prompt_err:
            print(f"[MistralClient] Could not prompt for new key interactively: {prompt_err}")

        if last_exception:
            raise last_exception
        raise RuntimeError("MistralClient failed: All keys rate-limited and no new key was provided.")


# =============================================================================
# GROQ  (free tier, no credit card: Llama-3.1-8b-instant, Mixtral-8x7b, etc.)
# =============================================================================

class GroqClient(LLMClient):
    """
    pip install groq
    Env var: GROQ_API_KEY
    Get a free key at https://console.groq.com/keys
    Supports multiple keys separated by commas for rotation on rate/token limits.

    Model IDs current as of this writing (verify at
    https://console.groq.com/docs/models before running — Groq periodically
    retires older model IDs):
        - "llama-3.1-8b-instant"
        - "mixtral-8x7b-32768"
        - "llama-3.3-70b-versatile"
    """

    def __init__(self, model_name: str = "llama-3.1-8b-instant", temperature: float = 0.7, api_key: Optional[str] = None):
        super().__init__(model_name, temperature)
        from groq import Groq
        self._Groq = Groq
        
        # Parse comma-separated keys, stripping whitespace and any surrounding quotes
        raw_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self.api_keys = [k.strip().strip("'").strip('"').strip() for k in raw_key.split(",") if k.strip()]
        self.current_key_index = 0
        
        if not self.api_keys:
            self.client = Groq()
        else:
            self.client = Groq(api_key=self.api_keys[0])

    def _call(self, system_prompt: str, messages: List[Dict[str, str]]) -> str:
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        tried_indices = set()
        last_exception = None

        # Loop through available keys in rotation if we hit rate/limit/auth errors
        while not self.api_keys or len(tried_indices) < len(self.api_keys):
            if self.api_keys:
                idx = self.current_key_index
                tried_indices.add(idx)
            else:
                idx = None

            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    temperature=self.temperature,
                    messages=full_messages,
                )
                return response.choices[0].message.content
            except Exception as e:
                last_exception = e
                err_str = str(e)
                # Check for rate limit, token limit, or authentication errors on Groq
                is_key_error = (
                    "429" in err_str or "413" in err_str or "rate_limit" in err_str.lower() or 
                    "tpm" in err_str.lower() or "rpm" in err_str.lower() or "limit" in err_str.lower() or
                    "401" in err_str or "unauthenticated" in err_str.lower() or "auth" in err_str.lower() or
                    "403" in err_str or "permission" in err_str.lower() or "invalid" in err_str.lower()
                )

                if is_key_error and self.api_keys and len(self.api_keys) > 1:
                    print(f"\n[GroqClient] Error hit on key index {idx}: {err_str}")
                    
                    # If it's a rate/token limit error, sleep briefly to cooldown
                    if any(x in err_str or x in err_str.lower() for x in ["429", "413", "rate_limit", "tpm", "rpm", "limit"]):
                        print("[GroqClient] Rate/Token limit detected. Sleeping 2 seconds for cooldown...")
                        time.sleep(2)

                    # Switch to next key in pool
                    self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
                    next_key = self.api_keys[self.current_key_index]
                    print(f"[GroqClient] Rotating to key index {self.current_key_index}...")
                    self.client = self._Groq(api_key=next_key)
                    continue
                else:
                    # Let the outer logic handle errors if we cannot rotate
                    raise e

        # If all keys in the pool were rate-limited or invalid in this turn, prompt for a new key
        print("\n[GroqClient] All pre-configured Groq API keys were rate-limited or invalid in this turn.")
        try:
            import getpass
            new_key = getpass.getpass("Please enter a new Groq API key (or press Enter to fail/retry with backoff): ").strip().strip("'").strip('"').strip()
            if new_key:
                if new_key in self.api_keys:
                    self.current_key_index = self.api_keys.index(new_key)
                    print(f"[GroqClient] Re-using entered API key index {self.current_key_index}...")
                else:
                    self.api_keys.append(new_key)
                    self.current_key_index = len(self.api_keys) - 1
                    print(f"[GroqClient] Added and switched to new API key...")
                self.client = self._Groq(api_key=self.api_keys[self.current_key_index])
                return self._call(system_prompt, messages)
        except (OSError, EOFError, ValueError) as prompt_err:
            print(f"[GroqClient] Could not prompt for new key interactively: {prompt_err}")

        if last_exception:
            raise last_exception
        raise RuntimeError("GroqClient failed: All keys rate-limited and no new key was provided.")


# =============================================================================
# OPENAI  (paid — wire this in when you're ready to switch off free tiers)
# =============================================================================

class OpenAIClient(LLMClient):
    """
    pip install openai
    Env var: OPENAI_API_KEY
    """

    def __init__(self, model_name: str = "gpt-4-turbo", temperature: float = 0.7, api_key: Optional[str] = None):
        super().__init__(model_name, temperature)
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key or os.environ["OPENAI_API_KEY"])

    def _call(self, system_prompt: str, messages: List[Dict[str, str]]) -> str:
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        response = self.client.chat.completions.create(
            model=self.model_name,
            temperature=self.temperature,
            messages=full_messages,
        )
        return response.choices[0].message.content


# =============================================================================
# HF LOCAL  (MentaLLaMA, ChatCounselor/ChatPsychiatrist — run in Colab)
# =============================================================================

class HFLocalClient(LLMClient):
    """
    Wraps a locally-loaded (Colab GPU) Hugging Face `transformers` checkpoint
    so it plugs into the same PatientAgent/TherapistAgent/EvaluatorAgent
    interface as the API-based clients above.

    Designed for models with NO hosted free inference API, e.g.:
        - klyang/MentaLLaMA-chat-7B
        - klyang/MentaLLaMA-chat-13B
        - EmoCareAI/ChatPsychiatrist   (a.k.a. "ChatCounselor", LLaMA-7B base)

    See notebooks/colab_self_hosted_models.ipynb for the full Colab setup
    (4-bit quantization so these fit on a free T4 GPU).

    Usage:
        client = HFLocalClient("klyang/MentaLLaMA-chat-7B", load_in_4bit=True)
        client.chat(system_prompt, messages)
    """

    def __init__(self, model_name: str, temperature: float = 0.7,
                 load_in_4bit: bool = True, max_new_tokens: int = 300,
                 model=None, tokenizer=None):
        super().__init__(model_name, temperature)
        self.max_new_tokens = max_new_tokens

        if model is not None and tokenizer is not None:
            # Caller already loaded the model (recommended in Colab, so you
            # only pay the load cost once and can reuse it across agents).
            self.model = model
            self.tokenizer = tokenizer
            return

        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        quant_config = None
        if load_in_4bit:
            quant_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
            )

        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            quantization_config=quant_config,
            device_map="auto",
            torch_dtype=torch.float16 if not load_in_4bit else None,
        )

    def _render_prompt(self, system_prompt: str, messages: List[Dict[str, str]]) -> str:
        # Generic instruction-style template. MentaLLaMA / ChatCounselor were
        # both fine-tuned from LLaMA/Vicuna-family instruction formats, so a
        # simple System/Human/Assistant transcript works well as a fallback.
        # If a model's card specifies its own chat template, prefer
        # `self.tokenizer.apply_chat_template(...)` instead.
        lines = [system_prompt.strip(), ""]
        for m in messages:
            speaker = "Assistant" if m["role"] == "assistant" else "Human"
            lines.append(f"{speaker}: {m['content']}")
        lines.append("Assistant:")
        return "\n".join(lines)

    def _call(self, system_prompt: str, messages: List[Dict[str, str]]) -> str:
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList

        prompt = self._render_prompt(system_prompt, messages)
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        prompt_len = inputs["input_ids"].shape[1]

        # --- Stop generation when the model starts a new "Human:" turn ------
        stop_strings = ["\nHuman:", "\n\nHuman:", "Human:"]
        class _StopOnDelimiter(StoppingCriteria):
            """Halt as soon as any stop-string appears in the newly generated text."""
            def __init__(self, tokenizer, prompt_length, stops):
                self.tokenizer = tokenizer
                self.prompt_length = prompt_length
                self.stops = stops

            def __call__(self, input_ids, scores, **kwargs):
                generated_text = self.tokenizer.decode(
                    input_ids[0][self.prompt_length:], skip_special_tokens=True
                )
                return any(s in generated_text for s in self.stops)

        stopping_criteria = StoppingCriteriaList([
            _StopOnDelimiter(self.tokenizer, prompt_len, stop_strings)
        ])

        with torch.no_grad():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                temperature=self.temperature,
                do_sample=True,
                top_p=0.9,
                pad_token_id=self.tokenizer.eos_token_id,
                stopping_criteria=stopping_criteria,
            )

        generated = self.tokenizer.decode(
            output_ids[0][prompt_len:], skip_special_tokens=True
        )

        # Post-process: truncate at the first "Human:" delimiter in case the
        # stopping criteria fired one token late.
        for delim in ["\nHuman:", "Human:"]:
            idx = generated.find(delim)
            if idx != -1:
                generated = generated[:idx]

        return generated.strip()


# =============================================================================
# FACTORY — builds a client from (provider, model_name) so run_benchmark.py
# doesn't need to import every SDK directly.
# =============================================================================

def get_client(provider: str, model_name: str, temperature: float = 0.7, **kwargs) -> LLMClient:
    provider = provider.lower()
    if provider == "gemini":
        return GeminiClient(model_name, temperature, **kwargs)
    if provider == "mistral":
        return MistralClient(model_name, temperature, **kwargs)
    if provider == "groq":
        return GroqClient(model_name, temperature, **kwargs)
    if provider == "openai":
        return OpenAIClient(model_name, temperature, **kwargs)
    if provider == "hf_local":
        return HFLocalClient(model_name, temperature, **kwargs)
    raise ValueError(f"Unknown provider: {provider}")
