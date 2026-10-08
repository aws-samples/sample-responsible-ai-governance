#!/usr/bin/env python3
"""
audit-run.py — Parallel Bedrock LLM assessment for the RAI brownfield audit.

WHAT THIS SCRIPT DOES (in plain English)
----------------------------------------
For brownfield audits, the agent gathers raw evidence for each of the
24 RAI rules and writes it to <project>/rai-governance/audit-ide-evidence.md.
This script reads that evidence file plus rules.json, sends each rule's
evidence to Amazon Bedrock for a compliance verdict, and writes all 24
verdicts to <project>/rai-governance/rai-findings.json.

The reason this is a Python script and not done by the agent directly:
  - SPEED: 24 rules assessed in parallel via a thread pool takes ~2 minutes
           total. The agent doing them sequentially in chat would take ~15.
  - DETERMINISM: Bedrock with temperature=0 returns the same verdict for the
           same prompt every time. Reproducible audits across runs.
  - PARALLELISM: The agent processes one prompt per chat turn. Threads in
           Python can fan out 24 concurrent API calls in seconds.

Everything else (evidence gathering, questionnaire flow, report drafting)
stays with the agent. This script is the one place where Python earns its
keep, and it's the only place where boto3 (the AWS SDK) is needed.

USAGE (the agent calls this from the skill markdown)
----------------------------------------------------
    python audit-run.py \
        --project-path /path/to/project \
        --evidence-file /path/to/project/rai-governance/audit-ide-evidence.md \
        --rules-file /path/to/.kiro/skills/responsible-ai-governance/data/shared/rules.json

Environment variables (optional, but commonly set):
    AWS_REGION       defaults to us-east-1
    RAI_LLM_MODEL    defaults to us.anthropic.claude-sonnet-4-6
    AWS_PROFILE      if you use named AWS profiles instead of env credentials

Exit codes:
    0  — audit succeeded, findings written
    1  — generic failure (e.g. evidence file missing, JSON malformed)
    2  — AWS credentials missing or expired (agent should tell user to refresh)
"""

# Standard library imports.
import argparse              # parse --project-path etc
import json                  # read rules.json, write findings.json
import os                    # read environment variables
import re                    # extract per-rule sections from the evidence markdown
import sys                   # stdout printing, exit codes
import logging               # error reporting
from concurrent.futures import ThreadPoolExecutor, as_completed  # parallel calls
from datetime import datetime, timezone
from pathlib import Path

# Configure logging to stderr so stdout stays clean for JSON output.
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("rai-audit")


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION via environment variables
# ─────────────────────────────────────────────────────────────────────────────
# We resolve config once at module load. Defaults are sane for AWS users.

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
RAI_LLM_MODEL = os.environ.get("RAI_LLM_MODEL", "us.anthropic.claude-sonnet-4-6")

# How many rules to assess in parallel. Bedrock can handle this comfortably
# and 24 rules ÷ 8 workers ≈ 3 batches of API calls. Tune up if you hit
# Bedrock throttling, tune down for stricter rate-limit budgets.
MAX_PARALLEL_WORKERS = 8

# Hard cap on how much code we send per rule. LLM context isn't free.
MAX_EVIDENCE_CHARS = 60_000


# ─────────────────────────────────────────────────────────────────────────────
# PRE-SCREEN PROMPT ADJUSTMENTS
# ─────────────────────────────────────────────────────────────────────────────
# The pre-screen answers (in rai-profile.json) tell us things about the
# project that change how strictly we should apply specific rules. For
# example, if the project uses a hosted model with no fine-tuning, then
# RAIDD-06 (training data lineage) doesn't apply — the foundation model
# provider owns that pipeline.
#
# These prompts are injected into the LLM call so the model knows the
# context. Without them, RAIDD-06 would be flagged non-compliant for
# every Bedrock-using project, which is wrong.

PRE_SCREEN_CONTEXT = {
    "hosted_model": {
        "RAIDD-06": (
            "IMPORTANT CONTEXT: This project uses a hosted foundation model "
            "(e.g., Amazon Bedrock, OpenAI) with NO custom training or fine-tuning. "
            "Training data lineage is NOT applicable (the provider owns the training "
            "pipeline). A model registry is NOT applicable (the provider manages versions). "
            "For this project, assess ONLY: (1) Is the model version pinned (not 'latest')? "
            "(2) Is inference logging configured with appropriate retention? "
            "If both are present, this rule is COMPLIANT. Do NOT penalize for missing "
            "training data lineage or model registry."
        ),
        "RAIUC-06": (
            "IMPORTANT CONTEXT: This project uses a hosted model with no custom training. "
            "Input variation analysis applies to INFERENCE INPUTS ONLY (what users send "
            "to the model at runtime), not to training data variation."
        ),
    },
    "regulated_data": {
        "RAIDD-03": (
            "IMPORTANT CONTEXT: This project handles regulated data (HIPAA/GDPR/financial). "
            "Apply STRICT assessment: PHI handling, explicit consent, data minimization, "
            "and audit logging are all REQUIRED, not optional."
        ),
    },
    "has_governance": {
        "RAIUC-05": (
            "IMPORTANT CONTEXT: This organization has a formal AI governance process. "
            "Look for REFERENCES to the approval process in documentation — the approval "
            "may be recorded in a separate governance system. Evidence of regulatory scope "
            "identification and a reference to the approval pathway is sufficient."
        ),
    },
}


def _pre_screen_text(profile: dict, rule_id: str) -> str:
    """Return any extra context to inject for this rule given the project profile."""
    pre = profile.get("pre_screen", {})
    parts = []
    for flag, rule_map in PRE_SCREEN_CONTEXT.items():
        if pre.get(flag) and rule_id in rule_map:
            parts.append(rule_map[rule_id])
    return "\n\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# PARSING THE EVIDENCE FILE
# ─────────────────────────────────────────────────────────────────────────────
# The agent writes audit-ide-evidence.md as a sequence of sections, one per rule.
# Each section starts with "## RULE-ID — Rule Name". This function splits
# the file into a {rule_id: section_text} dict so we can hand each rule's
# evidence to its own LLM call.
#
# Format (from the skill markdown):
#     ## RAIUC-01 — Verify AI Is Necessary
#     **Evidence source:** documentation
#     **Doc findings:** ...
#     **Agent's assessment:** ...
#
#     ## RAIUC-02 — ...

# Match a heading like "## RAIUC-01 — Verify AI..." capturing the rule ID.
# We accept either em-dash, en-dash, or ASCII hyphen between ID and name.
SECTION_HEADER_RE = re.compile(r"^##\s+([A-Z]+-\d+)\s*[—–-]", re.MULTILINE)


def parse_evidence_file(path: Path) -> dict[str, str]:
    """
    Read audit-ide-evidence.md and split it into per-rule sections.
    Returns a dict {rule_id: full_section_markdown}.

    If the agent didn't write a section for a rule, that rule won't appear
    in the dict and the audit will record it as "needs_input".
    """
    if not path.exists():
        return {}

    text = path.read_text()
    # Find all rule headings + their start positions.
    matches = list(SECTION_HEADER_RE.finditer(text))
    sections = {}
    for i, m in enumerate(matches):
        rule_id = m.group(1)
        start = m.start()
        # End of this section = start of next section (or end of file).
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section = text[start:end].strip()
        # Cap evidence size so we don't blow past the LLM context window.
        if len(section) > MAX_EVIDENCE_CHARS:
            section = section[:MAX_EVIDENCE_CHARS] + "\n\n[... truncated for LLM context ...]"
        sections[rule_id] = section
    return sections


# ─────────────────────────────────────────────────────────────────────────────
# BUILDING THE LLM PROMPT
# ─────────────────────────────────────────────────────────────────────────────
# We construct one prompt per rule. The prompt has four parts:
#   1. The rule name + what we're looking for
#   2. The compliant_if / partial_if / non_compliant_if criteria
#   3. The evidence the agent wrote in audit-ide-evidence.md
#   4. Instructions to reply in strict JSON
#
# Strict JSON output is what makes this script deterministic. We can't
# parse free-form prose reliably, but we CAN parse JSON.

def build_audit_prompt(rule: dict, evidence: str, pre_screen_note: str) -> str:
    """Assemble the full prompt for one rule."""
    guidance = rule.get("audit_guidance", {})
    what_to_look_for = "\n".join(
        f"  - {item}" for item in guidance.get("what_to_look_for", [])
    )

    return f"""You are auditing a codebase against the AWS Well-Architected Responsible AI Lens.

Rule: {rule['id']} — {rule['name']}
Pillar: {rule.get('pillar', 'unknown')}

{pre_screen_note}

What to look for:
{what_to_look_for}

Verdict criteria:
  Compliant if: {guidance.get('compliant_if', 'N/A')}
  Partial if: {guidance.get('partial_if', 'N/A')}
  non_compliant if: {guidance.get('non_compliant_if', 'N/A')}
  Unknown if: {guidance.get('unknown_if', 'Insufficient evidence')}

Evidence from the codebase (gathered by an AI coding assistant):
{evidence}

Return ONLY valid JSON in this exact format. No markdown, no commentary outside the JSON:
{{
  "status": "compliant" | "partial" | "non_compliant" | "unknown",
  "evidence": "specific file:line or pattern, or 'not found'",
  "reasoning": "one or two sentences explaining the verdict",
  "priority": "high" | "medium" | "low" | null
}}

priority is null if status is compliant or unknown.
priority reflects the risk if status is non_compliant or partial.
"""


# ─────────────────────────────────────────────────────────────────────────────
# THE BEDROCK CALL
# ─────────────────────────────────────────────────────────────────────────────
# This is the only function in this entire skill stack that talks to AWS.
# We use boto3's Converse API which works with all Anthropic Claude models on
# Bedrock and returns a clean text response.

def call_bedrock(prompt: str) -> str:
    """
    Send a prompt to Amazon Bedrock and return the raw text reply.
    Raises RuntimeError on any failure (caller decides how to handle).

    Why temperature=0 is passed explicitly:
        The module docstring's determinism claim only holds if every rerun
        picks the same argmax token, so it is passed here explicitly rather
        than relying on model-default sampling.
    """
    # Lazy import so non-audit users (e.g., score.py callers) don't need boto3.
    try:
        import boto3
    except ImportError as e:
        raise RuntimeError(
            "boto3 is not installed. Install it with: pip install boto3"
        ) from e

    try:
        client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
        response = client.converse(
            modelId=RAI_LLM_MODEL,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"temperature": 0},
        )
        # Converse always returns content[0].text for single-turn text replies.
        return response["output"]["message"]["content"][0]["text"]
    except Exception as e:
        # Inspect the error message to give a more helpful exit code upstream.
        msg = str(e)
        if "Unable to locate credentials" in msg or "ExpiredToken" in msg:
            raise RuntimeError("AWS_CREDENTIALS_MISSING_OR_EXPIRED") from e
        raise RuntimeError(f"Bedrock call failed: {msg}") from e


# ─────────────────────────────────────────────────────────────────────────────
# PARSING THE LLM REPLY
# ─────────────────────────────────────────────────────────────────────────────
# We told the LLM to return strict JSON. Sometimes it wraps it in ```json
# code fences anyway. This function strips those and parses. If parsing
# fails, we don't crash the whole audit — we just record an "unknown" verdict
# with a note that the LLM response was malformed.

# The only status values score.py and the report understand. Anything else
# from the model is a bug/typo, not a real verdict, and must not be allowed
# to reach disk unflagged — it would silently vanish from scoring (see
# REVIEW-FINDINGS.md D1 / finding #3).
VALID_STATUSES = {"compliant", "partial", "non_compliant", "unknown"}


def parse_verdict(raw: str, rule_id: str) -> dict:
    """Parse the LLM's JSON reply into a verdict dict."""
    text = raw.strip()
    # Strip markdown code fences if present.
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]).strip()

    try:
        data = json.loads(text)
        status = data.get("status", "unknown")
        if status not in VALID_STATUSES:
            log.warning(
                f"{rule_id}: LLM returned unrecognized status '{status}', "
                "coercing to 'unknown'"
            )
            status = "unknown"
        return {
            "rule_id": rule_id,
            "status": status,
            "evidence": data.get("evidence", ""),
            "reasoning": data.get("reasoning", ""),
            "priority": data.get("priority"),
        }
    except json.JSONDecodeError:
        log.warning(f"{rule_id}: LLM returned malformed JSON, recording as unknown")
        return {
            "rule_id": rule_id,
            "status": "unknown",
            "evidence": "LLM response could not be parsed",
            "reasoning": "Audit LLM returned non-JSON output. Re-run or review manually.",
            "priority": None,
        }


# ─────────────────────────────────────────────────────────────────────────────
# ASSESS A SINGLE RULE
# ─────────────────────────────────────────────────────────────────────────────
# Wraps the whole "build prompt → call Bedrock → parse verdict" flow for one
# rule. This is what gets submitted to the thread pool 24 times.

def assess_rule(rule_id: str, rule: dict, evidence: str, profile: dict) -> dict:
    """Audit one rule against its evidence. Returns a finding dict."""
    # No evidence at all: short-circuit with needs_input.
    if not evidence.strip():
        return {
            "rule_id": rule_id,
            "status": "needs_input",
            "evidence": "No evidence section found for this rule in audit-ide-evidence.md",
            "reasoning": "The agent did not gather evidence for this rule. Re-run evidence gathering.",
            "priority": None,
        }

    pre_screen_note = _pre_screen_text(profile, rule_id)
    prompt = build_audit_prompt(rule, evidence, pre_screen_note)
    log.info(f"{rule_id}: calling Bedrock ({RAI_LLM_MODEL})")
    raw = call_bedrock(prompt)
    return parse_verdict(raw, rule_id)


# ─────────────────────────────────────────────────────────────────────────────
# THE MAIN AUDIT LOOP — parallelized
# ─────────────────────────────────────────────────────────────────────────────
# ThreadPoolExecutor is the standard Python pattern for I/O-bound parallelism.
# Each Bedrock call spends most of its time waiting on the network, so threads
# (not processes) are the right tool. We submit all 24 rules at once and
# collect verdicts as they finish.

def run_audit(project_path: str, evidence_file: Path, rules_file: Path) -> dict:
    """Run the full audit. Returns the findings dict that gets written to disk."""
    # Load rules and evidence.
    rules = json.loads(rules_file.read_text())
    sections = parse_evidence_file(evidence_file)

    # Load the project profile so we can apply pre-screen context adjustments.
    # If no profile exists yet (rai_activate not run), use empty defaults.
    profile_path = Path(project_path) / "rai-governance" / "rai-profile.json"
    profile = {}
    if profile_path.exists():
        profile = json.loads(profile_path.read_text())

    # Decide which rules to assess. By default: all rules in rules.json.
    # The score.py file handles "disabled" rule logic later — we still send
    # them here so the user can see what they would have looked like.
    rule_ids = list(rules.keys())
    log.info(f"Auditing {len(rule_ids)} rules with {MAX_PARALLEL_WORKERS} parallel workers")

    findings = []
    # ThreadPoolExecutor handles thread lifecycle for us. The "with" block
    # waits for all threads to finish before exiting.
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as pool:
        # Submit all rule assessments. Each future represents an in-flight Bedrock call.
        future_to_rule = {
            pool.submit(
                assess_rule,
                rule_id,
                rules[rule_id],
                sections.get(rule_id, ""),
                profile,
            ): rule_id
            for rule_id in rule_ids
        }
        # as_completed yields futures in the order they finish (not submission order).
        # This means the first verdict to print is whichever rule was fastest,
        # which is fine — we collect them all into a list and sort at the end.
        for future in as_completed(future_to_rule):
            rule_id = future_to_rule[future]
            try:
                finding = future.result()
                findings.append(finding)
                log.info(f"{rule_id}: {finding['status']}")
            except RuntimeError as e:
                msg = str(e)
                if msg == "AWS_CREDENTIALS_MISSING_OR_EXPIRED":
                    # Special exit: bubble this up so the agent can prompt the user.
                    raise
                log.error(f"{rule_id}: error — {msg}")
                findings.append({
                    "rule_id": rule_id,
                    "status": "unknown",
                    "evidence": "Audit error",
                    "reasoning": msg,
                    "priority": None,
                })

    # Sort by rule_id for stable output (helps git diffs and human review).
    findings.sort(key=lambda f: f["rule_id"])

    return {
        "audit_run_at": datetime.now(timezone.utc).isoformat(),
        "audit_mode": "ide_agent",   # this script is always called in ide_agent mode
        "model": RAI_LLM_MODEL,
        "region": AWS_REGION,
        "rules_assessed": len(findings),
        "findings": findings,
    }


# ─────────────────────────────────────────────────────────────────────────────
# COMMAND-LINE ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Run a parallel Bedrock-based RAI audit against an evidence file."
    )
    parser.add_argument(
        "--project-path", required=True,
        help="Project being audited (rai-governance/ folder lives here)",
    )
    parser.add_argument(
        "--evidence-file", required=True,
        help="Path to audit-ide-evidence.md written by the agent",
    )
    parser.add_argument(
        "--rules-file", required=True,
        help="Path to rules.json (typically in .kiro/skills/responsible-ai-governance/data/shared/)",
    )
    args = parser.parse_args()

    evidence_path = Path(args.evidence_file)
    rules_path = Path(args.rules_file)

    if not evidence_path.exists():
        log.error(f"Evidence file not found: {evidence_path}")
        return 1
    if not rules_path.exists():
        log.error(f"Rules file not found: {rules_path}")
        return 1

    try:
        result = run_audit(args.project_path, evidence_path, rules_path)
    except RuntimeError as e:
        if str(e) == "AWS_CREDENTIALS_MISSING_OR_EXPIRED":
            print(json.dumps({
                "error": "AWS credentials missing or expired",
                "remedy": "Run `aws sso login` or refresh your credentials and retry.",
            }, indent=2), file=sys.stdout)
            return 2
        log.error(f"Audit failed: {e}")
        return 1

    # Write findings to the project's rai-governance folder.
    out_path = Path(args.project_path) / "rai-governance" / "rai-findings.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2) + "\n")

    # Print a small summary to stdout for the agent to read.
    summary = {
        "ok": True,
        "rules_assessed": result["rules_assessed"],
        "model": result["model"],
        "findings_file": str(out_path),
        "next_step": "Run score.py compute and snapshot to update the trend.",
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
