#!/usr/bin/env python3
"""
audit-report.py — Generate the website-style HTML report for a Responsible AI audit.

WHAT THIS SCRIPT DOES (in plain English)
----------------------------------------
This script produces the final, single-file HTML report that the user opens
in a browser. It reads everything the skill has produced for a project
(profile, score, findings, questionnaire answers, history) plus the canonical
rule and Lens-BP reference data, then injects all of that into the HTML
template at templates/audit/audit-report.html.tmpl.

The template is a single self-contained HTML file with embedded CSS and JS
and a placeholder where the data goes. This script's job is to:

  1. Load every state file from <project>/rai-governance/
  2. Enrich findings with rule names and pillar info from rules.json
  3. Sanitize the JSON so it can sit safely inside an HTML <script> tag
  4. Replace the placeholder ONLY inside the data <script> tag (not in
     the surrounding template comments that also mention the placeholder)
  5. Write the rendered HTML to <project>/rai-governance/reports/

Why this is a permanent script and not done by the agent in chat:

  - The HTML embedding has strict rules (no </script, no <!--, no <script
    inside script content) that an agent doing string replacement is likely
    to violate when user-supplied evidence text contains those substrings
  - The script-tag locating logic is fiddly: there are multiple mentions
    of {{AUDIT_DATA_JSON}} in the template (in documentation comments AND
    in the actual script tag), and only the script tag one should be replaced
  - These bugs have already happened and we shouldn't reinvent the wheel

USAGE
-----
    python audit-report.py \
        --project-path /path/to/project \
        --codebase-name "Healthcare Scheduling Agent" \
        --agent-label kiro

Reads from <project>/rai-governance/:
    rai-profile.json
    score.json
    rai-findings.json
    rai-questionnaire-responses.json
    rai-audit-history.json

Reads from the skill's data/shared/ folder (auto-resolved relative to this script):
    rules.json
    lens-bps.json

Reads from the skill's templates/audit/ folder:
    audit-report.html.tmpl
    audit-report.tmpl.md   (optional — if present, also writes a markdown summary)

Writes:
    <project>/rai-governance/reports/rai-audit-report-<agent_label>.html
    <project>/rai-governance/reports/rai-audit-report-<agent_label>.md (if md template available)

Exit codes:
    0  — success, both files written
    1  — generic failure (missing template, malformed JSON in state files)
"""

import argparse
import html
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Skill-internal utilities — file I/O, path helpers, HTML sanitization.
# scripts/shared/ is on PYTHONPATH because the skill markdown invokes scripts
# with python directly; we add it explicitly here so this script can also be
# run standalone.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from utils import (
    skill_root_from,
    load_json as _load_json,
    sanitize_json_for_html,
)

# Errors go to stderr so the agent can capture them. Final summary goes to stdout.
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("report")

# This script lives in .kiro/skills/responsible-ai-governance/scripts/audit/.
# data/ and templates/ are at the skill root (two levels up).
SKILL_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = SKILL_ROOT / "data"
TEMPLATE_DIR = SKILL_ROOT / "templates"
SHARED_DATA = DATA_DIR / "shared"
AUDIT_DATA = DATA_DIR / "audit"
AUDIT_TEMPLATES = TEMPLATE_DIR / "audit"


# ─────────────────────────────────────────────────────────────────────────────
# FILE + HTML HELPERS
# ─────────────────────────────────────────────────────────────────────────────
# _load_json and sanitize_json_for_html now live in scripts/shared/utils.py
# and are imported at the top of this file. They are not redefined here so
# there is exactly ONE implementation per helper across the skill.


# ─────────────────────────────────────────────────────────────────────────────
# DATA ASSEMBLY — pull everything together that the report's JS needs
# ─────────────────────────────────────────────────────────────────────────────

def assemble_data(state_dir: Path, codebase_name: str, agent_label: str) -> dict:
    """
    Build the single dict that becomes the report's data blob.

    The report's JS reads this dict via document.getElementById('audit-data')
    and renders every tab from it. The shape here must match what
    audit-report.html.tmpl expects.
    """
    profile = _load_json(state_dir / "rai-profile.json", {})
    score = _load_json(state_dir / "score.json", {})
    findings_data = _load_json(state_dir / "rai-findings.json", {"findings": []})
    qresp = _load_json(state_dir / "rai-questionnaire-responses.json", {"answers": {}})
    history = _load_json(state_dir / "rai-audit-history.json", {"snapshots": []})

    # Reference data from the skill assets — names, pillars, Lens BP details.
    rules = _load_json(SHARED_DATA / "rules.json", {})
    lens_bps = _load_json(SHARED_DATA / "lens-bps.json", {})

    # Enrich each finding with its rule name, pillar, and Lens BP links.
    # The audit-run.py output doesn't carry these (it just has rule_id + verdict);
    # the report wants them so it can render the rule cards with full context.
    enriched_findings = []
    for f in findings_data.get("findings", []):
        rule_id = f.get("rule_id")
        rule = rules.get(rule_id, {})
        enriched_findings.append({
            **f,
            "name": rule.get("name", rule_id),
            "pillar": rule.get("pillar", ""),
            "lens_bps": rule.get("lens_bps", []),
            "remediation": (rule.get("audit_guidance") or {}).get("remediation", ""),
        })

    # Determine audit_mode from the most recent findings file (defaults to ide_agent).
    audit_mode = findings_data.get("audit_mode", "ide_agent")

    return {
        "meta": {
            "codebase_name": codebase_name,
            "audit_mode": audit_mode,
            "agent_label": agent_label,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "profile": profile,
        "score": score,
        "findings": enriched_findings,
        "questionnaire": qresp,
        "lens_bps": lens_bps,
        "history": history,
    }


# ─────────────────────────────────────────────────────────────────────────────
# HTML RENDERING — load the template, do the precise replacement
# ─────────────────────────────────────────────────────────────────────────────

# These exact strings delimit the data <script> tag in the template. We use
# them to locate the body of that tag so we replace ONLY inside it, not in
# the documentation comments at the top of the template (which also contain
# the {{AUDIT_DATA_JSON}} placeholder string).
_SCRIPT_TAG_OPEN = '<script type="application/json" id="audit-data">'
_SCRIPT_TAG_CLOSE = '</script>'


def render_html(data: dict, codebase_name: str) -> str:
    """
    Read audit-report.html.tmpl, inject the data dict + codebase name, return the
    final HTML string.

    This function performs two distinct substitutions:
      1. The data blob — replaced ONLY inside the <script type=application/json>
         body. A naive global replace would also rewrite the placeholder mention
         in the template's top-of-file documentation comment (harmless but
         bloats the file by tens of kilobytes).
      2. The codebase name — replaced globally. The {{CODEBASE_NAME}} placeholder
         only appears in the <title>, so a global replace is safe.
    """
    template_path = AUDIT_TEMPLATES / "audit-report.html.tmpl"
    if not template_path.exists():
        raise FileNotFoundError(f"Template missing: {template_path}")

    tmpl = template_path.read_text()
    data_json = sanitize_json_for_html(json.dumps(data))

    # Locate the data <script> tag and replace its body.
    open_at = tmpl.find(_SCRIPT_TAG_OPEN)
    if open_at < 0:
        raise ValueError(f"Template missing '{_SCRIPT_TAG_OPEN}' open tag")
    close_at = tmpl.find(_SCRIPT_TAG_CLOSE, open_at)
    if close_at < 0:
        raise ValueError(f"Template missing closing '{_SCRIPT_TAG_CLOSE}' after data tag open")

    new_body = "\n" + data_json + "\n"
    out = tmpl[:open_at + len(_SCRIPT_TAG_OPEN)] + new_body + tmpl[close_at:]

    # Replace the codebase-name placeholder (only in <title>).
    # codebase_name lands inside <title>. Escape it so a name containing markup
    # cannot close the title element and inject nodes into the document head.
    # NOTE: render_markdown() deliberately does NOT escape — that output is
    # markdown, and HTML-escaping would corrupt it.
    out = out.replace("{{CODEBASE_NAME}}", html.escape(codebase_name))

    return out


# ─────────────────────────────────────────────────────────────────────────────
# OPTIONAL MARKDOWN SUMMARY — draft a short companion .md from the data
# ─────────────────────────────────────────────────────────────────────────────
#
# The HTML report is the primary artifact. The markdown summary is a
# git-friendly companion that's easy to diff and quote in PRs/runbooks.
# We populate templates/audit/audit-report.tmpl.md with simple {PLACEHOLDER} substitutions.

def render_markdown(data: dict, codebase_name: str, agent_label: str) -> str | None:
    """
    Optional companion: render templates/audit/audit-report.tmpl.md → markdown summary.
    Returns None if the template doesn't exist (the .md is optional).

    The template uses simple {PLACEHOLDER} substitutions. We only fill the
    metadata header and a few key totals here — the agent can hand-author a
    richer markdown summary alongside if it wants. This script exists to
    guarantee a baseline machine-generated .md always sits next to the HTML.
    """
    tmpl_path = AUDIT_TEMPLATES / "audit-report.tmpl.md"
    if not tmpl_path.exists():
        return None

    profile = data.get("profile", {})
    score = data.get("score", {})
    pillar_scores = score.get("pillar_scores", {}) or {}
    counts = score.get("counts", {}) or {}
    pre = profile.get("pre_screen", {}) or {}

    placeholders = {
        "{CODEBASE_NAME}": codebase_name,
        "{PROJECT_ID}": profile.get("project_id", "—"),
        "{TIER}": str(profile.get("tier", "—")),
        "{TIER_NAME}": profile.get("tier_name", "—"),
        "{AUDIT_MODE}": data.get("meta", {}).get("audit_mode", "—"),
        "{AGENT_LABEL}": agent_label,
        "{GENERATED_AT}": data.get("meta", {}).get("generated_at", "—"),
        "{OVERALL_SCORE}": str(score.get("overall_score", "—")),
        "{MATURITY_LABEL}": score.get("maturity_label", "—"),
        "{RAIUC_SCORE}": str(pillar_scores.get("RAIUC", "—")),
        "{RAIDD_SCORE}": str(pillar_scores.get("RAIDD", "—")),
        "{RAIER_SCORE}": str(pillar_scores.get("RAIER", "—")),
        "{RAIOP_SCORE}": str(pillar_scores.get("RAIOP", "—")),
        "{N_COMPLIANT}": str(counts.get("compliant", 0)),
        "{N_PARTIAL}": str(counts.get("partial", 0)),
        "{N_NON_COMPLIANT}": str(counts.get("non_compliant", 0)),
        "{N_UNKNOWN}": str(counts.get("unknown", 0)),
        "{N_NEEDS_INPUT}": str(counts.get("needs_input", 0)),
        "{N_DISABLED}": str(counts.get("disabled", 0)),
        "{HOSTED_MODEL}": "yes" if pre.get("hosted_model") else "no",
        "{REGULATED_DATA}": "yes" if pre.get("regulated_data") else "no",
        "{HAS_GOVERNANCE}": "yes" if pre.get("has_governance") else "no",
    }

    md = tmpl_path.read_text()
    for k, v in placeholders.items():
        md = md.replace(k, v)
    return md


# ─────────────────────────────────────────────────────────────────────────────
# COMMAND-LINE ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate the Responsible AI audit HTML report.",
    )
    parser.add_argument(
        "--project-path", required=True,
        help="Project root (the audit's <project>/rai-governance/ folder).",
    )
    parser.add_argument(
        "--codebase-name", required=True,
        help='Display name for the system (e.g. "Healthcare Scheduling Agent").',
    )
    parser.add_argument(
        "--agent-label", default="ide_agent",
        help='Agent identifier used in the report header and filename suffix '
             '(e.g. "kiro", "claude_code", "codekb"). Default: ide_agent.',
    )
    args = parser.parse_args()

    project = Path(args.project_path)
    state_dir = project / "rai-governance"
    reports_dir = state_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    if not state_dir.exists():
        log.error(f"No rai-governance/ folder at {state_dir}. Has the audit run?")
        return 1

    try:
        data = assemble_data(state_dir, args.codebase_name, args.agent_label)
        html = render_html(data, args.codebase_name)
    except Exception as e:
        log.error(f"Render failed: {e}")
        return 1

    # Slugify the agent label for safe filenames (lowercase, underscores).
    import re as _re
    safe_label = _re.sub(r"[^a-z0-9]+", "_", args.agent_label.lower()).strip("_") or "ide_agent"

    html_path = reports_dir / f"rai-audit-report-{safe_label}.html"
    html_path.write_text(html)

    md_path = None
    md_content = render_markdown(data, args.codebase_name, safe_label)
    if md_content is not None:
        md_path = reports_dir / f"rai-audit-report-{safe_label}.md"
        md_path.write_text(md_content)

    summary = {
        "ok": True,
        "html_path": str(html_path),
        "html_size": len(html),
        "md_path": str(md_path) if md_path else None,
        "score": data.get("score", {}).get("overall_score"),
        "maturity": data.get("score", {}).get("maturity_label"),
        "findings": len(data.get("findings", [])),
        "questionnaire_answers": len(data.get("questionnaire", {}).get("answers", {})),
        "snapshots": len(data.get("history", {}).get("snapshots", [])),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
