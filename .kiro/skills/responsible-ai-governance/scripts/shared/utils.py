#!/usr/bin/env python3
"""
utils.py — Stateless utility helpers shared across the RAI skill scripts.

WHAT BELONGS HERE
-----------------
Functions that are pure transformations, file I/O wrappers, or constant
loaders with no business logic of their own. If a function makes scoring
decisions, calls Bedrock, parses Lens-specific structures, or otherwise
encodes domain knowledge, it stays in its owning script.

Things that live here:
- JSON load/save with stable formatting
- Project state directory resolution (rai-governance/ folder)
- ISO-8601 timestamp helper
- Skill-asset path helpers (resolve data/, templates/ from any script)
- Focus-area to pillar map loader (cached at first call)
- Mode-aware priority profile loader
- HTML-safe JSON escaping for embedding into <script> blocks

These functions have no dependencies beyond the standard library.
They are imported by score.py, audit-run.py, audit-report.py, and design-gate.py.
"""

import json
from datetime import datetime, timezone
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# PATH HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def skill_root_from(script_file: str) -> Path:
    """
    Resolve the skill root directory from a script's __file__.
    Scripts live in scripts/{shared,audit,design}/ — two levels up from any of them.
    """
    return Path(script_file).resolve().parent.parent.parent


def state_dir(project_path: str) -> Path:
    """
    Return the rai-governance/ directory inside the project being audited.
    Creates it if it doesn't exist yet. This is where ALL state files live.
    """
    p = Path(project_path) / "rai-governance"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ─────────────────────────────────────────────────────────────────────────────
# JSON I/O
# ─────────────────────────────────────────────────────────────────────────────

def load_json(path: Path, default=None):
    """
    Read a JSON file. If it doesn't exist, return the supplied default value
    so callers can keep their code simple (no "if exists" checks needed).
    """
    if not path.exists():
        return default
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    """
    Write a JSON file with stable formatting: 2-space indent, trailing newline.
    Stable formatting matters because these files end up in git diffs.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


# ─────────────────────────────────────────────────────────────────────────────
# TIME
# ─────────────────────────────────────────────────────────────────────────────

def now_iso() -> str:
    """ISO 8601 timestamp in UTC. Used for every timestamp we record."""
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# FOCUS AREA → PILLAR MAP (cached)
# ─────────────────────────────────────────────────────────────────────────────
# The 8 AWS Well-Architected RAI Lens focus areas roll up into 4 pillars for
# reporting. Source of truth lives in data/shared/focus-area-to-pillar.json.
# We cache the flattened map after first load so repeat calls are free.

_FOCUS_AREA_CACHE = None


def focus_area_to_pillar(skill_root: Path) -> dict:
    """
    Return the focus-area-to-pillar map (flat dict) — the 8 RAI Lens focus
    areas keyed by name, valued by the 4-pillar code (RAIUC/RAIDD/RAIER/RAIOP).
    Cached after first call so repeat lookups are free.
    """
    global _FOCUS_AREA_CACHE
    if _FOCUS_AREA_CACHE is not None:
        return _FOCUS_AREA_CACHE

    path = skill_root / "data" / "shared" / "focus-area-to-pillar.json"
    raw = load_json(path, {})
    # Strip metadata keys (anything starting with "_" is a comment / docstring).
    out = {k: v for k, v in raw.items() if not k.startswith("_")}
    _FOCUS_AREA_CACHE = out
    return out


# ─────────────────────────────────────────────────────────────────────────────
# MODE-AWARE PRIORITY PROFILE
# ─────────────────────────────────────────────────────────────────────────────
# Audit mode and design mode use different rule priorities to reflect the
# different cost-of-failure when a gap is found. Profiles live in
# data/{mode}/{mode}-priority-profile.json. Falls back to empty dict if absent.

def load_priority_profile(skill_root: Path, mode: str) -> dict:
    """
    Load the rule priority profile for the given mode.
    Returns a dict of {rule_id: priority}. Missing file returns empty dict
    (caller falls back to its own default priority lookup).
    """
    path = skill_root / "data" / mode / f"{mode}-priority-profile.json"
    if not path.exists():
        return {}
    return load_json(path, {}).get("priorities", {})


# ─────────────────────────────────────────────────────────────────────────────
# HTML SAFETY
# ─────────────────────────────────────────────────────────────────────────────
# When embedding JSON inside a <script> tag in an HTML report, certain
# sequences must be escaped to comply with the WHATWG spec for script content
# restrictions. Otherwise a stray "</script>" or "<!--" inside data values
# can break parsing.

def sanitize_json_for_html(s: str) -> str:
    """
    Escape characters that would break JSON embedded inside an HTML <script> tag.

    Per the HTML5 spec (whatwg.org/multipage/scripting.html#restrictions-for-contents-of-script-elements),
    script element content cannot contain the literal substrings "</script",
    "<!--", or "<script". If your data has any of those, the browser will
    misparse the page.

    The replacements below are JSON-valid escape sequences. JSON.parse() in the
    browser restores the original characters cleanly.
    """
    return (
        s.replace("</",      r"<\/")          # neutralises </script and any other </tag
         .replace("<!--",    r"<\u0021--")    # cannot open an HTML comment
         .replace("<script", r"<\u0073cript") # cannot open a nested script tag
    )
