"""
Quantitative comparison charts across therapist models and conditions.
These answer "which model scored higher" — see why_analysis.py for the
qualitative "why did it score that way" layer.

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


def _savefig(fig, out_dir: str, name: str) -> str:
    path = os.path.join(out_dir, f"{name}.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_overall_score_by_model(df: pd.DataFrame, out_dir: str) -> str:
    grouped = df.groupby("therapist_model")["overall_score"].agg(["mean", "std"]).sort_values("mean", ascending=False)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(grouped.index, grouped["mean"], yerr=grouped["std"].fillna(0), capsize=5, color="#4C72B0")
    ax.set_ylabel("Overall Score (0-100)")
    ax.set_title("Overall Therapist Performance by Model\n(mean ± std across all sessions)")
    ax.set_ylim(0, 100)
    plt.xticks(rotation=25, ha="right")
    return _savefig(fig, out_dir, "overall_score_by_model")


def plot_pillar_comparison(df: pd.DataFrame, out_dir: str) -> str:
    pillars = ["diagnostic_score", "safety_score", "coherence_score", "empathy_score"]
    grouped = df.groupby("therapist_model")[pillars].mean()

    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.arange(len(grouped.index))
    width = 0.2
    colors = ["#4C72B0", "#DD8452", "#55A868", "#C44E52"]
    for i, pillar in enumerate(pillars):
        ax.bar(x + i * width, grouped[pillar], width, label=pillar.replace("_score", ""), color=colors[i])

    ax.set_xticks(x + width * 1.5)
    ax.set_xticklabels(grouped.index, rotation=25, ha="right")
    ax.set_ylabel("Score (0-10)")
    ax.set_title("Four-Pillar Comparison by Model")
    ax.legend()
    return _savefig(fig, out_dir, "pillar_comparison_by_model")


def plot_condition_model_heatmap(df: pd.DataFrame, out_dir: str) -> str:
    pivot = df.pivot_table(index="condition", columns="therapist_model", values="overall_score", aggfunc="mean")

    fig, ax = plt.subplots(figsize=(1.5 * len(pivot.columns) + 3, 0.6 * len(pivot.index) + 3))
    im = ax.imshow(pivot.values, cmap="RdYlGn", vmin=0, vmax=100, aspect="auto")

    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns, rotation=25, ha="right")
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)

    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            val = pivot.values[i, j]
            if not np.isnan(val):
                ax.text(j, i, f"{val:.0f}", ha="center", va="center", color="black", fontsize=9)

    fig.colorbar(im, ax=ax, label="Overall Score (0-100)")
    ax.set_title("Overall Score by Condition x Model")
    return _savefig(fig, out_dir, "condition_model_heatmap")


def plot_barrett_lennard_radar(df: pd.DataFrame, out_dir: str) -> str:
    dims = ["bl_level_of_regard", "bl_empathic_understanding",
            "bl_unconditionality_of_regard", "bl_congruence"]
    labels = ["Level of Regard", "Empathic Understanding", "Unconditionality", "Congruence"]
    grouped = df.groupby("therapist_model")[dims].mean()

    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))
    for model_name, row in grouped.iterrows():
        values = row.tolist()
        values += values[:1]
        ax.plot(angles, values, linewidth=2, label=model_name)
        ax.fill(angles, values, alpha=0.08)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 10)
    ax.set_title("Barrett-Lennard Empathy Dimensions by Model")
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1))
    return _savefig(fig, out_dir, "barrett_lennard_radar")


def plot_safety_incidents(df: pd.DataFrame, out_dir: str) -> str:
    cols = ["missed_risk_markers_count", "hallucinations_count", "bias_flags_count"]
    grouped = df.groupby("therapist_model")[cols].sum()

    fig, ax = plt.subplots(figsize=(9, 5))
    grouped.plot(kind="bar", ax=ax, color=["#C44E52", "#8172B2", "#CCB974"])
    ax.set_ylabel("Total Count Across All Sessions")
    ax.set_title("Safety & Bias Incident Counts by Model")
    plt.xticks(rotation=25, ha="right")
    ax.legend(["Missed risk markers", "Clinical hallucinations", "Western-centric bias flags"])
    return _savefig(fig, out_dir, "safety_incidents_by_model")


def generate_all_charts(df: pd.DataFrame, output_dir: Optional[str] = None) -> Dict[str, str]:
    output_dir = output_dir or config.FIGURES_DIR
    os.makedirs(output_dir, exist_ok=True)
    return {
        "overall_score_by_model": plot_overall_score_by_model(df, output_dir),
        "pillar_comparison_by_model": plot_pillar_comparison(df, output_dir),
        "condition_model_heatmap": plot_condition_model_heatmap(df, output_dir),
        "barrett_lennard_radar": plot_barrett_lennard_radar(df, output_dir),
        "safety_incidents_by_model": plot_safety_incidents(df, output_dir),
    }
