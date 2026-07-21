"""
Quantitative comparison charts across therapist models and conditions.
These answer "which model scored higher" — see why_analysis.py for the
qualitative "why did it score that way" layer.

Every session now has TWO overall scores in the summary CSV:
    - llm_overall_score      -> the Evaluator LLM's own holistic 0-100 judgment
    - formula_overall_score  -> computed directly from the Evaluator's
                                 structured flags via the equations in
                                 analytics/metrics.py (see README "Formula
                                 Reference")
plot_llm_vs_formula_agreement() below visualizes how well the two agree.

Requires: pandas, matplotlib (pip install pandas matplotlib)
"""

import os
from typing import Dict, Optional

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # headless-safe (Colab, servers, CI)
import matplotlib.pyplot as plt

import config

# ── Consistent chart styling ────────────────────────────────────────────────
_STYLE_APPLIED = False

def _apply_chart_style():
    """Set shared matplotlib rcParams once for uniform chart appearance."""
    global _STYLE_APPLIED
    if _STYLE_APPLIED:
        return
    plt.rcParams.update({
        "figure.facecolor": "white",
        "axes.facecolor": "#FAFAFA",
        "axes.edgecolor": "#CCCCCC",
        "axes.grid": True,
        "grid.alpha": 0.3,
        "grid.color": "#CCCCCC",
        "font.size": 11,
        "axes.titlesize": 13,
        "axes.labelsize": 11,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
        "figure.dpi": 150,
    })
    _STYLE_APPLIED = True


def _savefig(fig, out_dir: str, name: str) -> str:
    path = os.path.join(out_dir, f"{name}.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_overall_score_by_model(df: pd.DataFrame, out_dir: str) -> str:
    _apply_chart_style()
    """Grouped bar: LLM holistic overall score vs. formula-derived overall score, per model."""
    grouped = df.groupby("therapist_model")[["llm_overall_score", "formula_overall_score"]].mean()
    grouped = grouped.sort_values("formula_overall_score", ascending=False)

    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(grouped.index))
    width = 0.35
    ax.bar(x - width / 2, grouped["llm_overall_score"], width, label="LLM holistic score", color="#4C72B0")
    ax.bar(x + width / 2, grouped["formula_overall_score"], width, label="Formula-derived score", color="#DD8452")

    ax.set_xticks(x)
    ax.set_xticklabels(grouped.index, rotation=25, ha="right")
    ax.set_ylabel("Overall Score (0-100)")
    ax.set_title("Overall Therapist Performance by Model\n(LLM holistic judgment vs. formula-derived)")
    ax.set_ylim(0, 100)
    ax.legend()
    return _savefig(fig, out_dir, "overall_score_by_model")


def plot_pillar_comparison(df: pd.DataFrame, out_dir: str) -> str:
    _apply_chart_style()
    """LLM's own 0-10 holistic pillar scores, by model."""
    pillars = ["llm_diagnostic_score", "llm_safety_score", "llm_coherence_score", "llm_empathy_score"]
    labels = ["diagnostic", "safety", "coherence", "empathy"]
    grouped = df.groupby("therapist_model")[pillars].mean()

    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.arange(len(grouped.index))
    width = 0.2
    colors = ["#4C72B0", "#DD8452", "#55A868", "#C44E52"]
    for i, (pillar, label) in enumerate(zip(pillars, labels)):
        ax.bar(x + i * width, grouped[pillar], width, label=label, color=colors[i])

    ax.set_xticks(x + width * 1.5)
    ax.set_xticklabels(grouped.index, rotation=25, ha="right")
    ax.set_ylabel("Score (0-10)")
    ax.set_ylim(0, 10)
    ax.set_title("Four-Pillar Comparison by Model (LLM holistic scores)")
    ax.legend()
    return _savefig(fig, out_dir, "pillar_comparison_by_model")


def plot_condition_model_heatmap(df: pd.DataFrame, out_dir: str,
                                  score_col: str = "formula_overall_score",
                                  name_suffix: str = "formula") -> str:
    _apply_chart_style()
    pivot = df.pivot_table(index="condition", columns="therapist_model", values=score_col, aggfunc="mean")

    fig, ax = plt.subplots(figsize=(1.5 * len(pivot.columns) + 3, 0.6 * len(pivot.index) + 3))
    im = ax.imshow(pivot.values, cmap="RdYlGn", vmin=0, vmax=100, aspect="auto")

    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns, rotation=25, ha="right")
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)

    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            val = pivot.values[i, j]
            if np.isnan(val):
                ax.text(j, i, "n/a", ha="center", va="center", color="#999999",
                        fontsize=9, fontstyle="italic")
            else:
                ax.text(j, i, f"{val:.0f}", ha="center", va="center", color="black", fontsize=9)

    fig.colorbar(im, ax=ax, label="Overall Score (0-100)")
    ax.set_title(f"Overall Score by Condition x Model ({name_suffix})")
    return _savefig(fig, out_dir, f"condition_model_heatmap_{name_suffix}")


def plot_barrett_lennard_radar(df: pd.DataFrame, out_dir: str) -> str:
    _apply_chart_style()
    dims = ["bl_level_of_regard", "bl_empathic_understanding",
            "bl_unconditionality_of_regard", "bl_congruence"]
    labels = ["Level of Regard", "Empathic Understanding", "Unconditionality", "Congruence"]
    grouped = df.groupby("therapist_model")[dims].mean()

    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))
    cmap = plt.get_cmap("tab10")
    zero_models = []
    for i, (model_name, row) in enumerate(grouped.iterrows()):
        values = row.tolist()
        # Detect all-zero models — these produce invisible polygons at origin
        if all(v == 0 for v in values):
            zero_models.append(model_name)
            continue
        values += values[:1]
        ax.plot(angles, values, linewidth=2, label=model_name, color=cmap(i % 10))
        ax.fill(angles, values, alpha=0.08, color=cmap(i % 10))

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 10)
    ax.set_title("Barrett-Lennard Empathy Dimensions by Model")

    # Annotate models that scored 0 on all dims instead of drawing invisible lines
    if zero_models:
        note = "Scored 0 on all dims: " + ", ".join(zero_models)
        ax.annotate(note, xy=(0.5, -0.08), xycoords="axes fraction",
                    ha="center", fontsize=9, fontstyle="italic", color="#888888")

    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1))
    return _savefig(fig, out_dir, "barrett_lennard_radar")


def plot_safety_incidents(df: pd.DataFrame, out_dir: str) -> str:
    _apply_chart_style()
    cols = ["missed_risk_markers_count", "hallucinations_count", "bias_flags_count"]
    grouped = df.groupby("therapist_model")[cols].sum()

    fig, ax = plt.subplots(figsize=(9, 5))
    grouped.plot(kind="bar", ax=ax, color=["#C44E52", "#8172B2", "#CCB974"])
    ax.set_xlabel("Therapist Model")
    ax.set_ylabel("Total Count Across All Sessions")
    ax.set_title("Safety & Bias Incident Counts by Model")
    plt.xticks(rotation=25, ha="right")
    ax.legend(["Missed risk markers", "Clinical hallucinations", "Western-centric bias flags"])
    return _savefig(fig, out_dir, "safety_incidents_by_model")


def plot_llm_vs_formula_agreement(df: pd.DataFrame, out_dir: str) -> str:
    _apply_chart_style()
    """
    Scatter of every session's LLM holistic overall score vs. its
    formula-derived overall score, colored by therapist model, with a y=x
    reference line. Points near the diagonal mean the Evaluator LLM's gut
    judgment matched the reproducible formula; systematic offset in either
    direction is itself a finding worth reporting (e.g. "the Evaluator LLM
    over-scores empathetic-sounding but safety-poor responses relative to
    the formula").
    """
    fig, ax = plt.subplots(figsize=(7, 7))

    models = df["therapist_model"].unique()
    cmap = plt.get_cmap("tab10")
    for i, model_name in enumerate(models):
        sub = df[df["therapist_model"] == model_name]
        ax.scatter(sub["formula_overall_score"], sub["llm_overall_score"],
                   label=model_name, color=cmap(i % 10), alpha=0.75, s=50)

    ax.plot([0, 100], [0, 100], linestyle="--", color="gray", linewidth=1, label="perfect agreement (y=x)")

    if df[["formula_overall_score", "llm_overall_score"]].dropna().shape[0] >= 2:
        corr = df["formula_overall_score"].corr(df["llm_overall_score"])
        ax.text(0.05, 0.95, f"Pearson r = {corr:.2f}", transform=ax.transAxes, va="top",
                fontsize=10, bbox=dict(facecolor="white", alpha=0.7, edgecolor="none"))

    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Formula-derived overall score")
    ax.set_ylabel("LLM holistic overall score")
    ax.set_title("Evaluator LLM vs. Formula-Derived Score Agreement")
    ax.legend(loc="lower right", fontsize=8)
    return _savefig(fig, out_dir, "llm_vs_formula_agreement")


def generate_all_charts(df: pd.DataFrame, output_dir: Optional[str] = None) -> Dict[str, str]:
    output_dir = output_dir or config.FIGURES_DIR
    os.makedirs(output_dir, exist_ok=True)
    return {
        "overall_score_by_model": plot_overall_score_by_model(df, output_dir),
        "pillar_comparison_by_model": plot_pillar_comparison(df, output_dir),
        "condition_model_heatmap_formula": plot_condition_model_heatmap(
            df, output_dir, score_col="formula_overall_score", name_suffix="formula"),
        "condition_model_heatmap_llm": plot_condition_model_heatmap(
            df, output_dir, score_col="llm_overall_score", name_suffix="llm"),
        "barrett_lennard_radar": plot_barrett_lennard_radar(df, output_dir),
        "safety_incidents_by_model": plot_safety_incidents(df, output_dir),
        "llm_vs_formula_agreement": plot_llm_vs_formula_agreement(df, output_dir),
    }
