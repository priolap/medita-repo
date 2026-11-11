# -*- coding: utf-8 -*-
"""Shared paths and figure style for the paper scripts."""
import os
from pathlib import Path

import matplotlib as mpl

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "results"
FIGURES = REPO / "figures"
TABLES = REPO / "tables"
CONFIG = REPO / "paper" / "config"
SOURCES = ["AIFA", "ISTAT", "MINIS"]


def medita_home():
    """Folder that contains data/ and config/ of a MEDITA installation.

    Order: environment variable MEDITA_HOME, then the folder two levels above the
    repository (layout MEDITA/repository/medita-repo).
    """
    env = os.environ.get("MEDITA_HOME")
    home = Path(env) if env else REPO.parents[1]
    if not (home / "data" / "output").is_dir():
        raise SystemExit(f"MEDITA data not found in {home}. Set MEDITA_HOME to the folder "
                         "that contains data/output/<SOURCE>/ (e.g. the unpacked Zenodo snapshot).")
    return home


# Categorical palette: 8 fixed slots (validated for colour-vision deficiencies on
# adjacent pairs) plus a neutral grey reserved for "Other"/"uncategorized".
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
NEUTRAL = "#9a9893"
INK = "#2b2a28"
MUTED = "#6b6a66"


def set_style():
    mpl.rcParams.update({
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "pdf.fonttype": 42,   # embed TrueType fonts (journal requirement)
        "ps.fonttype": 42,
        "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
        "font.size": 8,
        "axes.titlesize": 9,
        "axes.labelsize": 8,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "legend.fontsize": 7,
        "axes.edgecolor": MUTED,
        "axes.labelcolor": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "text.color": INK,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 0.6,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.color": "#e3e2de",
        "grid.linewidth": 0.5,
        "axes.axisbelow": True,
        "legend.frameon": False,
    })


def save(fig, stem):
    """Save a figure as vector PDF (for LaTeX) and 300-dpi PNG (for preview)."""
    FIGURES.mkdir(parents=True, exist_ok=True)
    out = []
    for ext in ("pdf", "png"):
        p = FIGURES / f"{stem}.{ext}"
        fig.savefig(p, bbox_inches="tight")
        out.append(p)
    return out
