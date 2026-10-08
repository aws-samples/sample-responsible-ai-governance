# Scripts — Quick Reference

Five Python files. All stdlib + boto3 only. You should never need to edit any of them.

## shared/score.py — deterministic math (stdlib only, no boto3)

```bash
# Compute weighted score from findings + answers + policy
python scripts/shared/score.py compute --project-path /path/to/project --mode audit

# Take a trend snapshot (also runs compute if score.json missing)
python scripts/shared/score.py snapshot --project-path /path/to/project --mode audit --trigger audit_run --label "First audit"

# Verify the policy change log integrity (sequential ID check)
python scripts/shared/score.py verify --project-path /path/to/project
```

Exit codes:
- `0` — success
- `2` — `verify` only: integrity check failed

## shared/utils.py — shared helpers (stdlib only, no boto3, not a CLI)

Imported by every other script here — JSON load/save, path resolution
(`skill_root_from`, `state_dir`), timestamps, the focus-area-to-pillar map loader,
the mode-aware priority profile loader, and `sanitize_json_for_html`. No
standalone entry point; nothing to run directly.

## audit/audit-run.py — parallel Bedrock LLM assessment (uses boto3)

```bash
# Run the full 24-rule audit against an evidence file
python scripts/audit/audit-run.py \
    --project-path /path/to/project \
    --evidence-file /path/to/project/rai-governance/audit-ide-evidence.md \
    --rules-file <path-to-skill>/data/shared/rules.json
```

Environment variables:
- `AWS_REGION` (default: `us-east-1`)
- `RAI_LLM_MODEL` (default: `us.anthropic.claude-sonnet-4-6`)
- `AWS_PROFILE` (optional, if you use named profiles)

Exit codes:
- `0` — success, findings written to `<project>/rai-governance/rai-findings.json`
- `1` — generic failure (missing file, malformed JSON)
- `2` — AWS credentials missing or expired (run `aws sso login` and retry)

## audit/audit-report.py — render the website-style HTML report (stdlib only, no boto3)

```bash
# Render the HTML + markdown report from current state files
python scripts/audit/audit-report.py \
    --project-path /path/to/project \
    --codebase-name "Healthcare Scheduling Agent" \
    --agent-label kiro
```

Reads:
- `<project>/rai-governance/{rai-profile.json, score.json, rai-findings.json, rai-questionnaire-responses.json, rai-audit-history.json}`
- Skill assets: `data/shared/rules.json`, `data/shared/lens-bps.json`,
  `templates/audit/audit-report.html.tmpl`, `templates/audit/audit-report.tmpl.md`

Writes:
- `<project>/rai-governance/reports/rai-audit-report-<agent_label>.html` (interactive)
- `<project>/rai-governance/reports/rai-audit-report-<agent_label>.md` (git-friendly summary, if md template present)

Exit codes:
- `0` — success
- `1` — generic failure (missing template, missing rai-governance/ folder, malformed JSON)

## design/design-gate.py — FUTURE CAPABILITY, not yet active

Gate-map operations for design mode (greenfield lifecycle gating). Not referenced
by `SKILL.md` and not invoked by the agent — testing is incomplete. Documented
here so the CLI surface is known when it's picked back up:

```bash
python scripts/design/design-gate.py init-gate-map --project-path /path/to/project --template aidlc
python scripts/design/design-gate.py list-gates --project-path /path/to/project
python scripts/design/design-gate.py describe-gate --project-path /path/to/project --gate-name <name>
python scripts/design/design-gate.py get-best-practices --project-path /path/to/project --gate-name <name>
python scripts/design/design-gate.py validate-coverage --project-path /path/to/project
```

## When you'd ever want to look at these

- Running into an unexpected error → check the `[ERROR]` line printed to stderr
- Wanting to confirm what model is being used → `audit-run.py` prints it on each rule
- Tuning parallelism → change `MAX_PARALLEL_WORKERS` near the top of `audit-run.py`
- Adding a new pre-screen adjustment → edit `PRE_SCREEN_CONTEXT` near the top of `audit-run.py`
- Changing the report layout → edit `templates/audit/audit-report.html.tmpl` directly; `audit-report.py` re-renders it as-is

That's it. The skill markdown (`SKILL.md`) is where you change the workflow. The data files (`data/**/*.json`) are where you change the rules.
