#!/usr/bin/env python3
"""
score.py — Deterministic scoring + history + integrity for the RAI skill.

WHAT THIS SCRIPT DOES (in plain English)
----------------------------------------
The RAI skill stores everything as JSON files in <project>/rai-governance/.
The IDE agent writes most of those files directly during the conversation.
But three things have to be done by code, not the agent, because they need
to be exact and reproducible every time:

  1. compute  — read findings + answers + policy → write a weighted score
  2. snapshot — append a row to the audit history file with a delta vs last time
  3. verify   — make sure the policy change log hasn't been tampered with

That's all this script does. It uses only the Python standard library.
No boto3, no external packages, no LLM calls. Just JSON in, JSON out.

You (the human) should never need to edit this file. If something feels off,
you can read the file top-to-bottom in one sitting — it is intentionally
small and has no hidden behavior.

USAGE (the agent calls these from the skill markdown)
-----------------------------------------------------
    python score.py compute   --project-path /path/to/project
    python score.py snapshot  --project-path /path/to/project --trigger audit_run
    python score.py verify    --project-path /path/to/project

Each command prints JSON to stdout. The agent reads it and surfaces it
to the user in chat or writes it into the report.
"""

# Python standard library imports only — no third-party packages.
import argparse           # for parsing command-line flags like --project-path
import json               # for reading and writing JSON files
import sys                # for printing JSON to stdout and exiting with codes
from pathlib import Path  # cleaner file path handling than os.path

# Skill-internal utilities — file I/O, time, focus-area map, priority profile.
# Local import works because scripts/shared/ is on PYTHONPATH when this script
# is executed directly (Python adds the script's directory automatically).
from utils import (
    skill_root_from,
    state_dir as _state_dir,
    load_json as _load_json,
    save_json as _save_json,
    now_iso as _now,
    focus_area_to_pillar as _focus_area_to_pillar_lookup,
    load_priority_profile as _load_priority_profile,
)

# Computed once at import time so call sites don't pass it around.
_SKILL_ROOT = skill_root_from(__file__)
def _focus_area_to_pillar() -> dict:
    return _focus_area_to_pillar_lookup(_SKILL_ROOT)


# ─────────────────────────────────────────────────────────────────────────────
# DEFAULT SCORING FRAMEWORK
# ─────────────────────────────────────────────────────────────────────────────
# These are the defaults baked into the script. The first time we score a
# project, we copy these into <project>/rai-governance/org-scoring-policy.json.
# After that, the project's file is authoritative — edit that file, not this code.
#
# Rule priority → weight: a "high" priority rule contributes 3x more to the
# score than a "low" priority rule. "critical" is reserved for blocking rules.
#
# Compliance status → numeric value: how much credit each verdict gives.
# A "compliant" finding contributes its full weight; "partial" gives half;
# "non_compliant" gives zero; "unknown" gives a small partial credit so we
# don't overly penalize rules that genuinely couldn't be assessed.
#
# Maturity thresholds: turn the 0-100 weighted score into a label.
# 90+ = Advanced, 70-89 = Established, 40-69 = Developing, 0-39 = Low.
#
# Pillar weights: the four RAI pillars contribute equally by default. An org
# can dial up RAIDD (data) for healthcare or RAIOP (operations) for prod gates.

DEFAULT_SCORING_FRAMEWORK = {
    "weights": {"critical": 5, "high": 3, "medium": 2, "low": 1},
    "compliance_values": {
        "compliant": 1.0,
        "partial": 0.5,
        "non_compliant": 0.0,
        "unknown": 0.3,
        "needs_input": None,   # None means "skip this finding when scoring"
        "disabled": None,
        "not_yet_implemented": None,   # design-stage only — code not written yet
    },
    "maturity_thresholds": {
        "Advanced": 90,
        "Established": 70,
        "Developing": 40,
        "Low": 0,
    },
    "pillar_weights": {
        "RAIUC": 1.0,    # Use Case Definition
        "RAIDD": 1.0,    # Design & Development
        "RAIER": 1.0,    # Evaluation & Release
        "RAIOP": 1.0,    # Operations
    },
}

# A questionnaire item belongs to a Lens "focus area" (Use Case, System Planning, etc).
# We map those focus areas to one of the four pillars so questionnaire
# answers contribute to the same pillar score as code findings.
# Source of truth: data/shared/focus-area-to-pillar.json (loaded at runtime
# by utils._focus_area_to_pillar — cached after first call).


# ─────────────────────────────────────────────────────────────────────────────
# FILE HELPERS
# ─────────────────────────────────────────────────────────────────────────────
# JSON load/save, project state directory, ISO timestamps. These are pure
# utility functions and live in scripts/shared/utils.py — imported above as
# _load_json, _save_json, _state_dir, _now. We no longer redefine them here
# so there is exactly ONE implementation of each, easier to maintain.


# ─────────────────────────────────────────────────────────────────────────────
# POLICY LOADING (READ-ONLY — never modifies policy files)
# ─────────────────────────────────────────────────────────────────────────────
# This script does not write policy files. The agent does that directly via
# str_replace and JSON edits. We only READ policy here to compute scores.

def _load_policy(project_path: str) -> dict:
    """
    Load the scoring framework + per-rule overrides for this project.

    Resolution order (later entries override earlier):
      1. DEFAULT_SCORING_FRAMEWORK (baked in above)
      2. <project>/rai-governance/org-scoring-policy.json (org defaults)
      3. <project>/rai-governance/project-scoring-policy.json (project specifics)

    On first call, we materialize the org file so the user can edit it.
    """
    state = _state_dir(project_path)

    # Org policy: create from defaults if missing, so the user has a file to edit.
    org_path = state / "org-scoring-policy.json"
    if not org_path.exists():
        _save_json(org_path, {
            "policy_name": "Default RAI Scoring Policy",
            "policy_version": "1.0",
            "scoring_framework": DEFAULT_SCORING_FRAMEWORK,
            "rule_overrides": {},   # rule_id → {action, priority, reason, ...}
        })
    org = _load_json(org_path, {})

    # Project policy: optional. Empty rule_overrides means "use org policy as-is".
    proj_path = state / "project-scoring-policy.json"
    proj = _load_json(proj_path, {"rule_overrides": {}})

    return {
        "framework":         org.get("scoring_framework", DEFAULT_SCORING_FRAMEWORK),
        "org_overrides":     org.get("rule_overrides", {}),
        "project_overrides": proj.get("rule_overrides", {}),
    }


def _effective_rule_config(rule_id: str, rule_pillar: str, policy: dict,
                            priority_profile: dict = None) -> dict:
    """
    Compute the effective configuration for one rule.
    Order of override: priority profile (mode-aware) → org → project (project wins).

    Returns a dict with:
      priority : "critical" | "high" | "medium" | "low"
      weight   : numeric weight derived from priority (or explicit override)
      action   : None | "disable" | "downgrade"
      pillar   : which pillar this rule belongs to (for grouping)
    """
    framework = policy["framework"]
    weight_table = framework["weights"]

    # Baseline priority comes from the mode-specific priority profile
    # (data/audit/audit-priority-profile.json or data/design/design-priority-profile.json).
    # The profile is mandatory — every rule must appear there. If a rule is
    # missing, default to "medium" rather than silently dropping it.
    priority = priority_profile.get(rule_id, "medium") if priority_profile else "medium"
    action = None

    # Apply org override if present (skip "_example" placeholders we ship).
    org_o = policy["org_overrides"].get(rule_id, {})
    if org_o and not org_o.get("_example"):
        priority = org_o.get("priority", priority)
        action = org_o.get("action", action)

    # Apply project override (project wins over org).
    proj_o = policy["project_overrides"].get(rule_id, {})
    if proj_o:
        priority = proj_o.get("priority", priority)
        action = proj_o.get("action", action)

    weight = weight_table.get(priority, 2)
    return {
        "priority": priority,
        "weight": weight,
        "action": action,
        "pillar": rule_pillar,
    }


# ─────────────────────────────────────────────────────────────────────────────
# COMPUTE — the main scoring function
# ─────────────────────────────────────────────────────────────────────────────
# This is the math the agent cannot do reliably. It reads the findings file
# (per-rule verdicts from the audit) and the questionnaire-responses file
# (per-question verdicts) and produces a single weighted percentage plus
# per-pillar percentages plus a maturity label.
#
# The formula is a weighted average:
#     score = sum(value * weight) / sum(weight)
# Where:
#     value  = compliance_values[finding.status]   (0.0 to 1.0)
#     weight = rule_weight * pillar_weight
#
# Findings with status "needs_input" or "disabled" have weight=None and are
# excluded — they neither help nor hurt the score.

def cmd_compute(args) -> int:
    """Subcommand: compute the weighted score and write it to score.json."""
    project_path = args.project_path
    state = _state_dir(project_path)

    # Load the inputs.
    findings = _load_json(state / "rai-findings.json", {"findings": []})["findings"]
    answers = _load_json(state / "rai-questionnaire-responses.json", {"answers": {}})["answers"]
    policy = _load_policy(project_path)
    framework = policy["framework"]
    compliance_values = framework["compliance_values"]
    pillar_weights = framework["pillar_weights"]
    thresholds = framework["maturity_thresholds"]

    # We need the rule definitions to know each rule's pillar.
    # Look in the skill assets folder relative to this script's location.
    # Script lives in scripts/shared/, so skill root is two parents up.
    skill_root = Path(__file__).resolve().parent.parent.parent
    rules_path = skill_root / "data" / "shared" / "rules.json"
    rules = _load_json(rules_path, {})

    # Also load Lens BPs for questionnaire scoring (they have risk_level + focus_area).
    lens_path = skill_root / "data" / "shared" / "lens-bps.json"
    lens_bps = _load_json(lens_path, {})

    # Mode-aware priority profile (audit or design).
    priority_profile = _load_priority_profile(_SKILL_ROOT, args.mode)

    # Accumulators: weighted contribution per pillar, max possible per pillar.
    # We'll use these to compute pillar percentages and the overall percentage.
    pillar_score = {p: 0.0 for p in pillar_weights}
    pillar_max = {p: 0.0 for p in pillar_weights}

    # Track per-finding contributions for transparency (shown in the report).
    contributions = []

    # ── Score code findings ──────────────────────────────────────────────────
    for f in findings:
        rule_id = f.get("rule_id")
        status = f.get("status", "unknown")
        rule = rules.get(rule_id)
        if not rule:
            # Finding for a rule we don't know about — skip rather than crash.
            continue

        cfg = _effective_rule_config(rule_id, rule.get("pillar", "RAIDD"), policy, priority_profile)

        # Disabled rules don't contribute (they were turned off deliberately).
        if cfg["action"] == "disable":
            continue

        # Some statuses don't contribute either (needs_input means we lacked evidence).
        value = compliance_values.get(status)
        if value is None and status not in compliance_values:
            # Not a deliberate None (needs_input/disabled/not_yet_implemented) —
            # an unrecognized status that reached this file some other way
            # (hand-edited findings, an older audit-run.py, a test fixture).
            # Score it as unknown rather than silently dropping it from both
            # the numerator and denominator.
            print(f"[WARN] {rule_id}: unrecognized status '{status}' in findings file, scoring as unknown", file=sys.stderr)
            status = "unknown"
            value = compliance_values.get(status)
        if value is None:
            continue

        pillar = cfg["pillar"]
        pillar_w = pillar_weights.get(pillar, 1.0)
        effective_weight = cfg["weight"] * pillar_w

        pillar_score[pillar] += value * effective_weight
        pillar_max[pillar] += effective_weight

        contributions.append({
            "source": "code",
            "rule_id": rule_id,
            "status": status,
            "priority": cfg["priority"],
            "weight": cfg["weight"],
            "pillar": pillar,
            "contribution": round(value * effective_weight, 3),
        })

    # ── Score questionnaire answers ──────────────────────────────────────────
    # Questionnaire answers also contribute. Each is keyed by lens_code (e.g.
    # RAIUC02-BP02). The Lens BP's risk_level becomes the priority and its
    # focus_area maps to a pillar.
    for lens_code, ans in answers.items():
        verdict = ans.get("verdict")
        if not verdict:
            continue
        if ans.get("status") in ("auto_resolved", "deferred"):
            continue
        value = compliance_values.get(verdict)
        if value is None and verdict not in compliance_values:
            # Same reasoning as the code-findings loop above: an unrecognized
            # verdict string must not silently vanish from scoring.
            print(f"[WARN] {lens_code}: unrecognized verdict '{verdict}' in questionnaire responses, scoring as unknown", file=sys.stderr)
            verdict = "unknown"
            value = compliance_values.get(verdict)
        if value is None:
            continue
        bp = lens_bps.get(lens_code)
        if not bp:
            continue

        risk_level = bp.get("risk_level", "Medium").lower()
        weight = framework["weights"].get(risk_level, 2)
        focus = bp.get("focus_area", "Use Case")
        pillar = _focus_area_to_pillar().get(focus, "RAIUC")
        pillar_w = pillar_weights.get(pillar, 1.0)
        effective_weight = weight * pillar_w

        pillar_score[pillar] += value * effective_weight
        pillar_max[pillar] += effective_weight

        contributions.append({
            "source": "questionnaire",
            "lens_code": lens_code,
            "verdict": verdict,
            "weight": weight,
            "pillar": pillar,
            "contribution": round(value * effective_weight, 3),
        })

    # ── Compute pillar percentages ───────────────────────────────────────────
    pillar_pct = {}
    for p in pillar_weights:
        if pillar_max[p] > 0:
            pillar_pct[p] = round(pillar_score[p] / pillar_max[p] * 100, 1)
        else:
            # No findings touched this pillar — no score to report.
            pillar_pct[p] = None

    # ── Compute overall percentage ───────────────────────────────────────────
    total_score = sum(pillar_score.values())
    total_max = sum(pillar_max.values())
    overall = round(total_score / total_max * 100, 1) if total_max > 0 else 0.0

    # ── Determine maturity label from thresholds ─────────────────────────────
    # Walk thresholds high-to-low; the first one we meet wins.
    maturity = "Low"
    for label in ("Advanced", "Established", "Developing"):
        if overall >= thresholds.get(label, 100):
            maturity = label
            break

    # ── Count findings by status for the dashboard ───────────────────────────
    counts = {"compliant": 0, "partial": 0, "non_compliant": 0,
              "unknown": 0, "needs_input": 0, "disabled": 0,
              "not_yet_implemented": 0}
    for f in findings:
        counts[f.get("status", "unknown")] = counts.get(f.get("status", "unknown"), 0) + 1

    # Build the result. This dict is what gets written to score.json AND
    # printed to stdout for the agent to read.
    result = {
        "computed_at": _now(),
        "overall_score": overall,
        "maturity_label": maturity,
        "pillar_scores": pillar_pct,
        "counts": counts,
        "total_findings_scored": len([c for c in contributions if c["source"] == "code"]),
        "total_questionnaire_scored": len([c for c in contributions if c["source"] == "questionnaire"]),
        "contributions": contributions,
    }

    _save_json(state / "score.json", result)
    print(json.dumps(result, indent=2))
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# SNAPSHOT — append a row to the trend file
# ─────────────────────────────────────────────────────────────────────────────
# Every meaningful change (audit run, questionnaire complete, policy change,
# report generated) calls this. We read the current score.json and append a
# new entry to rai-audit-history.json with a delta vs the previous snapshot.

def cmd_snapshot(args) -> int:
    """Subcommand: append a snapshot to the history file."""
    project_path = args.project_path
    trigger = args.trigger
    label = args.label  # optional human-readable label
    state = _state_dir(project_path)

    # We need the latest score. If compute hasn't been run yet, run it implicitly
    # so snapshots always have something to record.
    score_path = state / "score.json"
    if not score_path.exists():
        # Fall back to running compute first. This keeps the agent's life simple —
        # it can call snapshot without remembering to call compute first.
        # Pass through the snapshot's mode so the priority profile picked here
        # matches the mode-tagged snapshot we're about to record.
        cmd_compute(argparse.Namespace(project_path=project_path, mode=args.mode))

    score = _load_json(score_path, {})
    history_path = state / "rai-audit-history.json"
    history = _load_json(history_path, {"snapshots": []})

    snapshots = history["snapshots"]
    new_id = f"snap-{len(snapshots) + 1:04d}"

    # Compute the delta vs the previous snapshot.
    prev = snapshots[-1] if snapshots else None
    if prev:
        delta = round(score.get("overall_score", 0) - prev.get("score", {}).get("weighted", 0), 1)
    else:
        delta = None

    # Capture which rules are currently disabled or downgraded so the trend
    # can show "policy state at this point" alongside the score.
    policy = _load_policy(project_path)
    disabled = [rid for rid, o in policy["project_overrides"].items()
                if o.get("action") == "disable"]
    downgraded = [rid for rid, o in policy["project_overrides"].items()
                  if o.get("action") == "downgrade"]

    snapshot = {
        "snapshot_id": new_id,
        "timestamp": _now(),
        "trigger": trigger,
        "label": label or _default_label(trigger, delta),
        "score": {
            "weighted": score.get("overall_score", 0),
            "maturity": score.get("maturity_label", "Unknown"),
            "pillars": score.get("pillar_scores", {}),
        },
        "counts": score.get("counts", {}),
        "policy_state": {
            "disabled_rules": disabled,
            "downgraded_rules": downgraded,
        },
        "delta": delta,
    }

    snapshots.append(snapshot)
    _save_json(history_path, {"snapshots": snapshots})
    print(json.dumps(snapshot, indent=2))
    return 0


def _default_label(trigger: str, delta) -> str:
    """Build a default label for a snapshot when the caller doesn't supply one."""
    base = {
        "audit_run": "Code audit completed",
        "questionnaire_complete": "Questionnaire recorded",
        "policy_change": "Policy change applied",
        "report_generated": "Report generated",
        "stage_complete": "AIDLC stage completed",
        "manual": "Manual snapshot",
    }.get(trigger, trigger)
    if delta is not None:
        sign = "+" if delta >= 0 else ""
        return f"{base} ({sign}{delta}%)"
    return base


# ─────────────────────────────────────────────────────────────────────────────
# VERIFY — integrity check on the policy change log
# ─────────────────────────────────────────────────────────────────────────────
# The policy change log uses sequential IDs: chg-0001, chg-0002, ...
# If anyone deletes an entry from the middle, the IDs no longer line up with
# the array index. This catches that.

def cmd_verify(args) -> int:
    """Subcommand: verify the policy change log hasn't been tampered with."""
    project_path = args.project_path
    state = _state_dir(project_path)
    log_path = state / "policy-change-log.json"
    log_data = _load_json(log_path, {"log": []})
    log = log_data.get("log", [])

    for i, entry in enumerate(log, start=1):
        expected = f"chg-{i:04d}"
        if entry.get("entry_id") != expected:
            result = {
                "integrity_ok": False,
                "detail": f"Expected {expected} at position {i}, found {entry.get('entry_id')!r}",
                "entry_count": len(log),
            }
            print(json.dumps(result, indent=2))
            return 2  # non-zero exit code so the agent knows it failed

    result = {
        "integrity_ok": True,
        "detail": "Sequential IDs verified",
        "entry_count": len(log),
    }
    print(json.dumps(result, indent=2))
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# COMMAND-LINE ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
# argparse turns "python score.py compute --project-path X" into a function call.
# Each subcommand has its own parser registered below.

def main():
    parser = argparse.ArgumentParser(
        description="RAI scoring, snapshot, and integrity checks."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # compute
    p = sub.add_parser("compute", help="Compute weighted score from findings + answers")
    p.add_argument("--project-path", required=True)
    p.add_argument("--mode", choices=["audit", "design"], default="audit",
                   help="Mode determines which priority profile is loaded (default: audit)")
    p.set_defaults(func=cmd_compute)

    # snapshot
    p = sub.add_parser("snapshot", help="Append a snapshot to audit history")
    p.add_argument("--project-path", required=True)
    p.add_argument("--mode", choices=["audit", "design"], default="audit",
                   help="Mode tag recorded with the snapshot (default: audit)")
    p.add_argument("--trigger", default="manual",
                   help="audit_run | questionnaire_complete | policy_change | report_generated | stage_complete | manual")
    p.add_argument("--label", default=None,
                   help="Optional human-readable label for this snapshot")
    p.set_defaults(func=cmd_snapshot)

    # verify
    p = sub.add_parser("verify", help="Verify policy change log integrity")
    p.add_argument("--project-path", required=True)
    p.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
