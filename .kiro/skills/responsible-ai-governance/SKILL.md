---
name: responsible-ai-governance
description: Audit AI/ML codebases against the AWS Well-Architected Responsible AI Lens and produce a website-style report with weighted maturity score, per-pillar breakdown, code findings, questionnaire responses, and trend.
version: 2.0.0
---

# Responsible AI Governance Skill

This skill assesses AI/ML applications against the AWS Well-Architected
Responsible AI Lens. It audits an existing codebase end-to-end, producing
a weighted maturity score and a self-contained HTML + markdown report.

**Prerequisites:** Python 3.11+. AWS credentials with Bedrock access in your
shell.

---

## File Layout

```
.kiro/skills/responsible-ai-governance/
├── SKILL.md                                  # this file
├── data/
│   ├── shared/
│   │   ├── rules.json                        # 24 rules
│   │   ├── questionnaire.json                # 50 items (32 active for hosted-model)
│   │   ├── lens-bps.json                     # 99 Lens BPs (see _meta for provenance)
│   │   └── focus-area-to-pillar.json         # 8 focus areas → 4 pillars rollup
│   ├── audit/
│   │   └── audit-priority-profile.json       # rule priorities
│   └── design/                               # FUTURE CAPABILITY — not yet active,
│       ├── design-priority-profile.json      # not referenced by this SKILL.md.
│       └── design-stages.json                # See "Roadmap" below.
├── scripts/
│   ├── shared/
│   │   ├── score.py                          # compute · snapshot · verify (mode-aware)
│   │   └── utils.py                          # JSON I/O, paths, sanitization
│   ├── audit/
│   │   ├── audit-run.py                      # Bedrock-backed verdicts
│   │   └── audit-report.py                   # HTML + markdown report
│   └── design/                               # FUTURE CAPABILITY — not yet active
│       └── design-gate.py                    # gate-map operations, code-gen guidance
└── templates/
    ├── shared/
    │   └── project-config.tmpl.md
    ├── audit/
    │   ├── audit-ide-evidence.tmpl.md
    │   ├── audit-questionnaire-review.tmpl.md
    │   ├── audit-report.html.tmpl
    │   └── audit-report.tmpl.md
    └── design/                               # FUTURE CAPABILITY — not yet active
        ├── design-gate-map-aidlc.tmpl.json    # AIDLC default gate-map
        ├── design-gate-map-generic.tmpl.json  # neutral starting point
        └── design-stage-guidance.tmpl.md
```

### Roadmap: design mode (greenfield gating)

`data/design/`, `scripts/design/design-gate.py`, and `templates/design/` implement a
second mode — gating AI development lifecycle stages by filtering Lens rules and
questionnaire items relevant to the current stage, for orchestrators (AIDLC, an IDE
flow, a custom CI step) to consume before generating code. This mode is **not
referenced by the Routing section below** and the agent will not invoke it: it has
not yet completed testing. The code ships so it is available once validated; treat
it as read-only until this note is removed.

---

## MANDATORY: Visual Identity (Always Apply)

The user must always be able to tell at a glance when this skill is driving vs.
when the agent is doing routine work. The 🛡️ shield prefix is the skill's
signature.

### Marker 1 — Activation banner (emit ONCE, at the very start of any mode)

```
╔══════════════════════════════════════════════════════════════╗
║  🛡️  RESPONSIBLE AI GOVERNANCE SKILL — ACTIVATED            ║
║                                                              ║
║  AWS Well-Architected Responsible AI Lens                    ║
║  Mode: Audit                                                 ║
║  Project: <project_id or "TBD">                              ║
╚══════════════════════════════════════════════════════════════╝
```

After the banner, list the steps the skill will walk through.

### Marker 2 — Step header (emit at the start of EVERY numbered step)

```
─────────────────────────────────────────────────────────────
 🛡️ Responsible AI │ STEP <n> of <N> │ <Step name>
─────────────────────────────────────────────────────────────
```

### Marker 3 — File-based input request

```
> 🛡️ **RESPONSIBLE AI INPUT NEEDED** — Step <n> of <N>
> ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
> **Action:** Open `<path/to/file.md>`
> **Fill in:** <what to fill in>
> **Then say:** `<keyword>`
> ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Marker 4 — In-chat question

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🛡️  Responsible AI · QUESTION <n> of <N>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**<Question text>**
▼ Your answer:
```

### Marker 5 — Light clarifier

```
> 🛡️ **Responsible AI** — *Quick clarification:* <follow-up>
```

### Marker 6 — Step completion

```
✅ Step <n> complete — <one-line summary>
   Files: <comma-separated artifacts written>
   Snapshot: <snap-id, if taken>

▶ Moving to Step <n+1> — <next step name> …
```

### Marker 7 — Skill completion (audit mode only)

```
╔══════════════════════════════════════════════════════════════╗
║  🛡️  RESPONSIBLE AI GOVERNANCE SKILL — COMPLETE             ║
║                                                              ║
║  Final Score: <X>% — <maturity_label>                        ║
║  Report: rai-governance/reports/rai-audit-report-<agent>.html║
╚══════════════════════════════════════════════════════════════╝
```

**Marker rules:** every step starts with Marker 2; every wait-for-input gate
uses Marker 3 or 4; every step transition emits Marker 6; the 🛡️ shield prefix
appears in every skill-emitted message.

---

## Routing

When the user wants to assess existing code — e.g. "audit my app for
Responsible AI", "Responsible AI compliance check" — enter audit mode and
emit **Marker 1**.

---

# Audit Workflow

### Step 1 — Project Configuration

#### 1a — Create Pre-Screen Configuration File

Copy `templates/shared/project-config.tmpl.md` into
`<project_path>/rai-governance/project-config.md`. The template has 7
configuration questions with `TODO:` placeholders.

Tell the user: *"Open `rai-governance/project-config.md`, fill in your
answers where it says TODO, and tell me **submit config** when ready."*

Wait for `submit config`.

#### 1b — Apply Configuration

Read `rai-governance/project-config.md`, parse the 7 answers, and write
`<project_path>/rai-governance/rai-profile.json`:

```json
{
  "project_id": "<from Q6>",
  "tier": <from Q2>,
  "tier_name": "Low Risk" | "Standard" | "High Risk",
  "project_path": "<from Q1>",
  "docs_paths": ["<from Q7>"],
  "pre_screen": {
    "hosted_model":   <from Q3>,
    "regulated_data": <from Q4>,
    "has_governance": <from Q5>
  },
  "mode": "audit",
  "created_at": "<ISO timestamp>",
  "applied_adjustments": []
}
```

Show the user a summary. Store `docs_paths` in working memory for Steps 3–4.

### Step 2 — Gather Code Evidence

Copy `templates/audit/audit-ide-evidence.tmpl.md` into
`<project_path>/rai-governance/audit-ide-evidence.md`.

Read `data/shared/rules.json` to get all 24 rules with their `audit_guidance`.

For each rule, gather evidence based on `evidence_source`:
- **`code`** — search the codebase using semantic, intent-based search for
  what the rule is actually checking for (per `audit_guidance.what_to_look_for`),
  read relevant files, reason about the rule's `compliant_if` criterion
- **`documentation`** — search the doc paths from Q7
- **`both`** — search both, reason across both

Write each rule's section in `audit-ide-evidence.md` following the template
format. The `**Agent's assessment:**` field is the most important — it must be
conclusive about whether the evidence satisfies the rule.

Tell the user: *"Evidence gathering complete. Review `audit-ide-evidence.md`
or say `run audit` when ready."*

Wait for `run audit`.

### Step 3 — Run the Audit

**Pre-flight:** confirm AWS credentials. If unsure, ask the user to run
`aws sts get-caller-identity`.

```bash
python <skill-path>/scripts/audit/audit-run.py \
    --project-path <project_path> \
    --evidence-file <project_path>/rai-governance/audit-ide-evidence.md \
    --rules-file <skill-path>/data/shared/rules.json
```

The script writes verdicts to `<project_path>/rai-governance/rai-findings.json`.

If exit code 2 (AWS credentials missing/expired), tell the user to refresh
credentials and say `retry audit`.

After the audit completes:

```bash
python <skill-path>/scripts/shared/score.py compute \
    --project-path <project_path> --mode audit

python <skill-path>/scripts/shared/score.py snapshot \
    --project-path <project_path> --mode audit --trigger audit_run
```

Show the user: weighted score, maturity label, pillar breakdown, counts, top
high-priority findings.

Ask if they want to proceed to the questionnaire.

### Step 4 — Questionnaire (5 Blocks)

Skip Block 3 (18 dataset items) if `pre_screen.hosted_model` is true —
auto-resolved.

#### 4a — Generate Review File

Copy `templates/audit/audit-questionnaire-review.tmpl.md` into
`<project_path>/rai-governance/audit-questionnaire-review.md`.

Read `data/shared/questionnaire.json` to get the catalog. For each active
item, attempt to extract a pre-fill answer from `docs_paths` (read the docs,
search for the question's keywords, propose a draft answer). Write each
item's section per the template format.

For Block 3 (when auto-resolved), include a single block-level note instead
of 18 sections.

Tell the user: *"Open `rai-governance/audit-questionnaire-review.md`. Mark
`[EDIT]` on any answer you want to change. Say `submit` when done."*

Wait for `submit`.

#### 4b — Record Answers

Read approved answers from the review file. Write
`<project_path>/rai-governance/rai-questionnaire-responses.json`:

```json
{
  "answers": {
    "<lens_code>": {
      "block":      "<block_name>",
      "question":   "<question text>",
      "response":   "<answer>",
      "mode":       "answered" | "file_provided" | "deferred",
      "file_path":  "<source file or null>",
      "verdict":    "compliant" | "partial" | "non_compliant" | "unknown",
      "reasoning":  "<why this verdict>",
      "status":     "answered"
    }
  }
}
```

For each answer, assess it against the Lens BP criteria from
`data/shared/lens-bps.json` (use the `description` field as the criterion).
Set verdict and reasoning.

Then:

```bash
python <skill-path>/scripts/shared/score.py compute \
    --project-path <project_path> --mode audit

python <skill-path>/scripts/shared/score.py snapshot \
    --project-path <project_path> --mode audit --trigger questionnaire_complete
```

Show verdict summary and updated score.

### Step 5 — Policy Adjustments (Optional, Any Time)

When the user wants to disable, downgrade, or restore a rule:

1. Ask: rule ID, action (`disable` / `downgrade` / `restore`), reason
   (mandatory), scope (`project` or `org`).
2. Update `<project_path>/rai-governance/project-scoring-policy.json` (project
   scope) or `org-scoring-policy.json` (org scope).
3. Append entry to `policy-change-log.json` with sequential `entry_id`.
4. Re-run `score.py verify`, `compute`, then `snapshot --trigger policy_change`.

### Step 6 — Generate the Report

Ask the user: *"What name should I use for this system in the report?"*

```bash
python <skill-path>/scripts/audit/audit-report.py \
    --project-path <project_path> \
    --codebase-name "<codebase_name>" \
    --agent-label <agent_name>
```

Then snapshot:

```bash
python <skill-path>/scripts/shared/score.py snapshot \
    --project-path <project_path> --mode audit --trigger report_generated
```

Tell the user where to find the HTML and markdown reports. Emit Marker 7.

---

## Customization

Layered priority (lowest first):

```
skill defaults  <  org policy  <  project policy  <  ad-hoc rule overrides
```

### Skill defaults (read-only)

- `data/shared/rules.json` — Lens-derived rules
- `data/shared/questionnaire.json` — questionnaire items
- `data/shared/lens-bps.json` — Lens BPs
- `data/audit/audit-priority-profile.json` — rule priorities

Skill never modifies these. Updates ship via skill version bumps.

### Org-level policy

`<project>/rai-governance/org-scoring-policy.json` (or supplied by org). The
skill seeds this file from defaults at first scoring run.

Org-level fields:
- `pillar_weights` — dial up/down a pillar's contribution to overall score
- `maturity_thresholds` — redefine Advanced/Established/Developing/Low cutoffs
- `rule_priority_defaults` — bump or lower priority for specific rules
- `rule_overrides` — disable/downgrade/restore at org scope (requires named
  approver)

### Project-level policy

`<project>/rai-governance/project-scoring-policy.json` — overrides org policy
for this project only.

- `rule_overrides` — disable/downgrade/restore (requires `reason`; no
  approver required at project scope)
- `pillar_weights` — project-specific weights

### Ad-hoc rule override (any time)

Step 5 accepts a one-shot override request:
- rule_id (required)
- action: `disable` / `downgrade` / `restore` (required)
- reason (required)
- scope: `project` / `org` (org requires approver)

Recorded in `policy-change-log.json` with sequential `entry_id`.

---

## Ongoing Commands

**"Show me the current score / policy"**
→ Read `score.json` and `project-scoring-policy.json` from
`<project>/rai-governance/`.

**"Tell me about rule [rule_id]"**
→ Read `data/shared/rules.json`, return the rule object.

**"How has the score changed over time?"**
→ Read `rai-audit-history.json` and summarize the trend. The HTML report's
Score Trend tab visualizes this.

**"Re-run the audit"**
→ Go back to Step 2 (re-gather evidence) then Step 3 (run audit).

**"Re-generate the report"**
→ Run audit mode Step 6 directly. No need to re-run audit unless code or
evidence changed.

---

## Key Rules

- Visual identity is non-negotiable — Marker 1 on activation, Marker 2 at
  every step start, Marker 3 or 4 at every wait-for-user gate, Marker 6 at
  every step completion, Marker 7 at audit completion.
- Never infer pre-screen answers — always create the config file and wait
  for user fill-in.
- Never hardcode paths — always ask the user for project path and doc paths.
- File-based configuration — generate `project-config.md` for Step 1; never
  ask pre-screen questions one at a time in chat.
- File-based questionnaire — generate `audit-questionnaire-review.md` first;
  never ask one at a time unless explicitly requested.
- Exact question text — use the exact question from `questionnaire.json` in
  the review file. Never abbreviate.
- Block 3 auto-resolution — if `hosted_model=true`, Block 3 is auto-resolved.
  Don't include the 18 items in the review.
- Always show verdicts after recording answers; flag any partial /
  non_compliant items.
- Policy changes need reasons — never write a policy change without a
  documented reason.
- `project_path` consistency — use the same path for all operations in a
  session.
- Reasoning is mandatory in `audit-ide-evidence.md` — `Agent's assessment`
  field for every rule.
- Search intent is in `rules.json` `audit_guidance.what_to_look_for`. Don't
  invent search strategies.
- Each rule's section in `audit-ide-evidence.md` is read by `audit-run.py`
  in isolation — it has no visibility into any other section. Always
  restate concrete evidence (file names, function names, quotes) in full;
  never write a cross-reference like "see above" or "same as rule X" in
  place of evidence.
- Always run snapshot after meaningful state changes — `audit_run`,
  `questionnaire_complete`, `policy_change`, `report_generated`,
  `stage_complete`.
- AWS credentials are required for `audit-run.py`. If absent, the script
  exits 2 with a clear remedy message.
- **Mode flag** — every `score.py` invocation passes `--mode audit`.

---

## MANDATORY: Performance Practices for the Agent

These rules exist because earlier runs hit timeouts or felt stuck. Follow
them every time.

**Tool names below are Kiro's, and are the tested reference
implementation** — these exact names were validated against the timeout
failures described in this section, so keep using them as-is on Kiro.
Running on a different agentic IDE without these tools available: apply the
same *rule* using your IDE's equivalent —
a full-file-read override ↔ `skipPruning`, a delegatable sub-agent ↔
`context-gatherer`, a create call ↔ `fs_write`, an append call ↔ `fs_append`.
Skip a rule only if your IDE has no equivalent capability at all for it.

### File reads

- Default to **pruned reads**. Use the read tool's normal mode.
- **Never** pass `skipPruning=true` on multiple files in the same turn.
  If a file truly needs full content, read it alone with `skipPruning=true`
  and don't combine with other large reads.
- For multi-file context gathering, **delegate to the context-gatherer
  sub-agent** rather than reading 5+ docs sequentially.

### Long file writes — chunked append

When writing a file with many similar sections (evidence, questionnaire
review, report sections), use this pattern:

1. **First call: `fs_write`** — header + the first batch of sections
2. **Subsequent calls: `fs_append`** — one batch per call

**Batch sizes that have worked reliably:**
- `audit-ide-evidence.md` (24 rules) — 4 chunks: header+RAIUC (6 rules),
  RAIDD (7), RAIER (5), RAIOP (6).
- `audit-questionnaire-review.md` (~32 items) — 4 chunks by block:
  Block 1, Block 2, Block 4, Block 5 (Block 3 auto-resolved → 1-line note).

**Why this works:** keeps each tool call short enough to complete without
network timeout, and a failure in one chunk only requires re-running that
chunk — not the whole file.

**Anti-pattern to avoid:** building a giant string in memory and writing it
in a single 500+-line `fs_write`. That's what timed out before.

### Helper scripts

- Don't write Python scripts inside the project's `rai-governance/` folder
  to do work the agent should do directly (e.g. assembling a questionnaire
  response file). The skill's design is for the **agent** to write JSON +
  markdown files based on its reasoning, and for the **shipped scripts**
  (`audit-run.py`, `score.py`, `audit-report.py`) to do
  the deterministic work. Avoid one-off helper scripts as a workaround.

### Read-modify-verify discipline

After any non-trivial write, run a quick verification:

```bash
wc -l <path> && grep -c "<expected_marker>" <path>
```

This catches truncated writes and out-of-order appends before they
propagate downstream.
