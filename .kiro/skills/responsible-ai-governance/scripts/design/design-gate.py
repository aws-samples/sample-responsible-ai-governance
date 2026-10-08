#!/usr/bin/env python3
"""
design-gate.py — Design-mode entry point. One gate at a time.

WHAT THIS SCRIPT DOES (in plain English)
----------------------------------------
The skill supports two modes: audit (assess existing code, end-to-end) and
design (assess one development-lifecycle gate at a time, before all the code
exists). This script is the design-mode entry point.

When an orchestrator (AIDLC, an IDE plugin, a custom CI flow) reaches a gate
in its development lifecycle, it calls this script with:
  - the project path
  - the gate name (e.g. "functional_design")

The script then:
  1. Reads <project>/rai-governance/design-gate-map.json
     (seeding it from a template if it doesn't exist yet)
  2. Looks up which rules and questionnaire items belong to that gate
  3. Asks the agent to populate evidence for those rules and answers for
     those questionnaire items (the agent does this by editing files in
     rai-governance/, just like it does in audit mode)
  4. Computes a score using the design-mode priority profile
  5. Records a snapshot in the trend history
  6. Returns a JSON summary: blocking-finding count, score delta, snapshot id

WHY THE GATE-MAP IS A FILE, NOT A FLAG
--------------------------------------
Different orchestrators have different gate names. AIDLC has 7 stages.
A custom CI pipeline might have 3 ("scoping", "build", "release"). The
gate-map JSON makes the mapping explicit and reviewable, with no logic
baked into this script. Caller customizes once; subsequent invocations
just name the gate.

USAGE (the orchestrator calls this from its own gating step)
------------------------------------------------------------
    python design-gate.py init-gate-map \\
        --project-path /path/to/project \\
        [--template aidlc|generic]                       # default: aidlc

    python design-gate.py list-gates \\
        --project-path /path/to/project

    python design-gate.py describe-gate \\
        --project-path /path/to/project \\
        --gate-name functional_design

    python design-gate.py validate-coverage \\
        --project-path /path/to/project

Each command prints JSON to stdout. The orchestrator (or the agent) reads
the JSON and decides what to do next.

This script does NOT call Bedrock and does NOT generate evidence on its
own. Evidence gathering and questionnaire answers are the agent's job
(same as audit mode). This script just orchestrates: it tells the agent
what to assess for the requested gate, then computes the score afterward.
"""

# Standard library imports only.
import argparse
import json
import shutil
import sys
from pathlib import Path

# Skill-internal utilities — file I/O, paths, focus area map.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from utils import (
    skill_root_from,
    state_dir,
    load_json,
    save_json,
    now_iso,
)

_SKILL_ROOT = skill_root_from(__file__)


# ─────────────────────────────────────────────────────────────────────────────
# GATE-MAP LIFECYCLE
# ─────────────────────────────────────────────────────────────────────────────
# The gate-map is the single source of truth for what gets assessed at each
# gate. It is initialized from a template at first invocation, then owned by
# the project. Subsequent edits stay in the project's copy.

def gate_map_path(project_path: str) -> Path:
    """Where the project's gate-map lives once initialized."""
    return state_dir(project_path) / "design-gate-map.json"


def template_path(template_name: str) -> Path:
    """Look up the gate-map template that ships with the skill."""
    name = f"design-gate-map-{template_name}.tmpl.json"
    return _SKILL_ROOT / "templates" / "design" / name


def cmd_init_gate_map(args) -> int:
    """
    Subcommand: seed <project>/rai-governance/design-gate-map.json from a template.

    If the project already has a gate-map, do nothing (don't overwrite the
    caller's edits). If the chosen template doesn't exist, fail with a clear
    error.
    """
    target = gate_map_path(args.project_path)
    if target.exists():
        # Don't clobber a caller-edited file. Tell them and exit cleanly.
        print(json.dumps({
            "ok": True,
            "action": "skipped",
            "reason": "gate-map already exists",
            "path": str(target),
        }))
        return 0

    src = template_path(args.template)
    if not src.exists():
        print(json.dumps({
            "ok": False,
            "error": f"template not found: {src.name}",
            "available": [p.name for p in src.parent.glob("design-gate-map-*.tmpl.json")],
        }), file=sys.stderr)
        return 2

    # Copy the template content. We use shutil.copy rather than re-serializing
    # because the template includes _comment fields we want to preserve verbatim.
    shutil.copyfile(src, target)
    print(json.dumps({
        "ok": True,
        "action": "created",
        "template": args.template,
        "path": str(target),
    }, indent=2))
    return 0


def _load_gate_map(project_path: str) -> dict:
    """
    Read the project's gate-map. Auto-seed from the AIDLC template if missing
    so callers can rely on a gate-map being present after this returns.
    """
    p = gate_map_path(project_path)
    if not p.exists():
        # Auto-seed with AIDLC default — same as if init-gate-map was called.
        src = template_path("aidlc")
        shutil.copyfile(src, p)
    return load_json(p, {"gates": []})


# ─────────────────────────────────────────────────────────────────────────────
# COVERAGE VALIDATION
# ─────────────────────────────────────────────────────────────────────────────
# The contract is: every rule in rules.json AND every questionnaire item
# (non-clubbed) must be assigned to exactly one gate. Skipping items based
# on pre-screen flags is a policy concern handled separately — the gate-map
# itself must be complete.

def _validate_coverage(gate_map: dict) -> dict:
    """
    Check that the gate-map covers every rule and every active questionnaire item
    exactly once. Returns a dict of {ok, missing_rules, missing_items,
    duplicate_rules, duplicate_items}.
    """
    rules = load_json(_SKILL_ROOT / "data" / "shared" / "rules.json", {})
    q = load_json(_SKILL_ROOT / "data" / "shared" / "questionnaire.json", [])
    qitems = q if isinstance(q, list) else list(q.values())
    # Skip clubbed items — they're aliases of a parent question.
    qitems = [i for i in qitems if i.get("pre_screen_filter") != "clubbed"]
    expected_rules = set(rules.keys())
    expected_items = {i["lens_code"] for i in qitems}

    seen_rules: list[str] = []
    seen_items: list[str] = []
    for g in gate_map.get("gates", []):
        seen_rules.extend(g.get("rules", []))
        seen_items.extend(g.get("questionnaire_items", []))

    # Use Counter to find duplicates while preserving the offending IDs.
    from collections import Counter
    rule_counts = Counter(seen_rules)
    item_counts = Counter(seen_items)
    duplicate_rules = sorted([r for r, c in rule_counts.items() if c > 1])
    duplicate_items = sorted([i for i, c in item_counts.items() if c > 1])

    missing_rules = sorted(expected_rules - set(seen_rules))
    missing_items = sorted(expected_items - set(seen_items))
    extra_rules = sorted(set(seen_rules) - expected_rules)
    extra_items = sorted(set(seen_items) - expected_items)

    ok = not (missing_rules or missing_items or duplicate_rules or duplicate_items
              or extra_rules or extra_items)
    return {
        "ok": ok,
        "missing_rules": missing_rules,
        "missing_items": missing_items,
        "duplicate_rules": duplicate_rules,
        "duplicate_items": duplicate_items,
        "extra_rules": extra_rules,
        "extra_items": extra_items,
        "total_rules_covered": len(set(seen_rules)),
        "total_items_covered": len(set(seen_items)),
    }


def cmd_validate_coverage(args) -> int:
    """Subcommand: print coverage report for the project's gate-map."""
    gm = _load_gate_map(args.project_path)
    result = _validate_coverage(gm)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


# ─────────────────────────────────────────────────────────────────────────────
# GATE INSPECTION
# ─────────────────────────────────────────────────────────────────────────────
# These commands let the orchestrator understand what a gate covers without
# running an assessment. Useful when AIDLC wants to display "you'll be assessed
# on X rules at this gate" before the user enters that stage.

def cmd_list_gates(args) -> int:
    """Print all gate names + their policy + counts of rules/items per gate."""
    gm = _load_gate_map(args.project_path)
    gates = []
    for g in gm.get("gates", []):
        gates.append({
            "name": g["name"],
            "policy": g.get("policy", "advisory"),
            "pillars_hint": g.get("pillars_hint", []),
            "rule_count": len(g.get("rules", [])),
            "questionnaire_count": len(g.get("questionnaire_items", [])),
        })
    print(json.dumps({"gates": gates}, indent=2))
    return 0


def cmd_describe_gate(args) -> int:
    """
    Print the full content of one gate: rules, questionnaire items, policy.
    The agent reads this and knows exactly what to assess for that gate.
    """
    gm = _load_gate_map(args.project_path)
    target = next((g for g in gm.get("gates", []) if g["name"] == args.gate_name), None)
    if not target:
        print(json.dumps({
            "ok": False,
            "error": f"gate not found: {args.gate_name}",
            "available_gates": [g["name"] for g in gm.get("gates", [])],
        }), file=sys.stderr)
        return 2

    # Enrich the rule IDs with their full rule definitions so the agent
    # has everything in one response.
    rules = load_json(_SKILL_ROOT / "data" / "shared" / "rules.json", {})
    q = load_json(_SKILL_ROOT / "data" / "shared" / "questionnaire.json", [])
    qitems = q if isinstance(q, list) else list(q.values())
    items_by_code = {i["lens_code"]: i for i in qitems}

    # Read the project's pre-screen flags so we can mark items that the
    # policy will auto-resolve. This is informational — the actual auto-resolve
    # decision is made by the policy layer when scoring runs.
    profile = load_json(state_dir(args.project_path) / "rai-profile.json", {})
    pre = profile.get("pre_screen", {})

    enriched_items = []
    for code in target.get("questionnaire_items", []):
        item = items_by_code.get(code, {})
        # Item is auto-resolved if its pre_screen_filter matches the project's flag.
        f = item.get("pre_screen_filter")
        sv = item.get("skip_if_filter_value")
        auto_resolved = bool(f and pre.get(f) == sv)
        enriched_items.append({
            "lens_code": code,
            "block": item.get("block"),
            "topic": item.get("topic"),
            "question": item.get("question"),
            "auto_resolved": auto_resolved,
        })

    enriched_rules = []
    for rid in target.get("rules", []):
        rule = rules.get(rid, {})
        enriched_rules.append({
            "id": rid,
            "name": rule.get("name", ""),
            "pillar": rule.get("pillar", ""),
            "description": rule.get("description", ""),
            "evidence_source": rule.get("evidence_source", ""),
        })

    print(json.dumps({
        "name": target["name"],
        "policy": target.get("policy", "advisory"),
        "pillars_hint": target.get("pillars_hint", []),
        "rules": enriched_rules,
        "questionnaire_items": enriched_items,
    }, indent=2))
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# CONSTRUCTIVE GUIDANCE FOR CODE GENERATION
# ─────────────────────────────────────────────────────────────────────────────
# Skill responsibility: surface the Lens best-practices content (rule intent,
# verification criteria, compliance criteria, linked Lens BP descriptions).
# Caller responsibility: turn that content into stack-specific coding patterns
# and examples appropriate for the project's tech stack and conventions.
#
# This command is meant to be called by an orchestrator's code-generation
# step BEFORE generating code at a given gate. The orchestrator (AIDLC, an
# IDE flow, a custom CI step) feeds the returned bundle into its code-gen
# prompt as guidance, so the resulting code is RAI-aware by construction.

def cmd_get_best_practices(args) -> int:
    """
    Return the raw best-practice content for every rule at a given gate.

    The output is intentionally policy-only — no example code, no language-
    specific patterns. The CALLER converts these into coding patterns
    appropriate for its project's stack. That keeps the skill focused on
    Lens content and lets each orchestrator emit idiomatic code for its
    own environment.
    """
    gm = _load_gate_map(args.project_path)
    target = next((g for g in gm.get("gates", []) if g["name"] == args.gate_name), None)
    if not target:
        print(json.dumps({
            "ok": False,
            "error": f"gate not found: {args.gate_name}",
            "available_gates": [g["name"] for g in gm.get("gates", [])],
        }), file=sys.stderr)
        return 2

    rules = load_json(_SKILL_ROOT / "data" / "shared" / "rules.json", {})
    lens_bps = load_json(_SKILL_ROOT / "data" / "shared" / "lens-bps.json", {})

    best_practices = []
    for rid in target.get("rules", []):
        rule = rules.get(rid, {})
        # Pull each linked Lens BP's description so the agent gets BP-level
        # detail in the same response.
        bp_codes = rule.get("lens_bps", [])
        bp_descriptions = []
        for bp_code in bp_codes:
            bp = lens_bps.get(bp_code, {})
            if bp:
                bp_descriptions.append({
                    "code":        bp_code,
                    "name":        bp.get("name", ""),
                    "focus_area":  bp.get("focus_area", ""),
                    "description": bp.get("description", ""),
                })

        best_practices.append({
            "rule_id":              rid,
            "name":                 rule.get("name", ""),
            "pillar":               rule.get("pillar", ""),
            "intent":               rule.get("description", ""),
            "must_satisfy":         rule.get("verification_criteria", []),
            "compliant_if":         rule.get("audit_guidance", {}).get("compliant_if", ""),
            "evidence_source":      rule.get("evidence_source", ""),
            "lens_bps":             bp_descriptions,
        })

    print(json.dumps({
        "gate_name":      target["name"],
        "policy":         target.get("policy", "advisory"),
        "pillars_hint":   target.get("pillars_hint", []),
        "best_practices": best_practices,
        "_responsibility": (
            "The skill surfaces Lens best-practice content. The CALLER "
            "(AIDLC, IDE flow, custom CI step) converts these into "
            "coding patterns appropriate for the project's tech stack."
        ),
    }, indent=2))
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# CLI WIRING
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Design-mode gate orchestration for the RAI skill."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init-gate-map", help="Seed gate-map.json from a template")
    p.add_argument("--project-path", required=True)
    p.add_argument("--template", choices=["aidlc", "generic"], default="aidlc",
                   help="Which gate-map template to use as the starting point")
    p.set_defaults(func=cmd_init_gate_map)

    p = sub.add_parser("list-gates", help="List all gates in the project's gate-map")
    p.add_argument("--project-path", required=True)
    p.set_defaults(func=cmd_list_gates)

    p = sub.add_parser("describe-gate", help="Show what one gate assesses")
    p.add_argument("--project-path", required=True)
    p.add_argument("--gate-name", required=True)
    p.set_defaults(func=cmd_describe_gate)

    p = sub.add_parser("get-best-practices",
                       help="Get the Lens best-practice content for a gate's rules. "
                            "Caller converts this into stack-specific coding patterns.")
    p.add_argument("--project-path", required=True)
    p.add_argument("--gate-name", required=True)
    p.set_defaults(func=cmd_get_best_practices)

    p = sub.add_parser("validate-coverage",
                       help="Verify every rule + item is covered exactly once")
    p.add_argument("--project-path", required=True)
    p.set_defaults(func=cmd_validate_coverage)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
