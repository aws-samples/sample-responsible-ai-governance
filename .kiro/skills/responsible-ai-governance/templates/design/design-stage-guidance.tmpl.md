> **⚠ Design mode — not yet available.** This stage-gate workflow is unreleased and
> untested. `SKILL.md` does not reference it, so it will not run from this skill
> today. Shown here for design review only.

# Responsible AI Stage Guidance — {STAGE_NAME}
## AIDLC + AWS Well-Architected Responsible AI Lens

**Project:** {PROJECT_ID}
**Tier:** {TIER} — {TIER_NAME}
**Stage:** {STAGE_NAME}
**Generated:** {TIMESTAMP}

---

## Why this matters at this stage

Responsible AI decisions are cheapest to make early. Rules below are the AWS Well-Architected Responsible AI Lens best practices that apply specifically at the **{STAGE_NAME}** stage. Address them now — in design — rather than discovering gaps at audit time.

---

## Rules to Address at this Stage

For each rule below, confirm with the user that the design doc for this stage covers it. If not, request the doc be updated before stage completion.

{FOR EACH RULE FROM rules.json WHERE lifecycle_stage == STAGE_NAME AND tier_<N> == "enforced":}

### {rule.id} — {rule.name}
**Pillar:** {rule.pillar}
**Description:** {rule.description}

**Verification criteria** (from `rules.json`):
{FOR EACH ITEM IN rule.verification_criteria:}
- {item}

**What to ensure in the design doc for this stage:**
{rule.audit_guidance.what_to_look_for joined with bullets}

**Status:** [ ] Addressed in design doc | [ ] Needs update | [ ] N/A (with rationale)

---

## Questionnaire Items for this Stage

{FOR EACH ITEM FROM questionnaire.json WHERE lifecycle_stage == STAGE_NAME AND not auto_resolved:}

### Q{n} — {item.lens_code}
**Question:** {item.question}
**Why this matters:** {item.bp.description}
**Pre-fill from docs:** {extracted answer or "TODO — please answer"}
**Your decision:** [APPROVE]

---

## Stage Gate Summary

When all rules above are either compliant, partial-with-mitigation, or N/A-with-rationale, this stage's Responsible AI gate is satisfied.

If `stage_gate_policy.{STAGE_NAME}` is `blocking` (in `org-scoring-policy.json`), the stage cannot complete with non-N/A blocking findings.

After stage completion:
1. Findings are appended to `<project>/rai-governance/rai-findings.json`
2. Snapshot is taken with trigger `stage_complete` and label `{STAGE_NAME} complete`
3. The score reflects the new findings — viewable at any time via the report's Score Trend tab

---

## Notes

{ANY ADDITIONAL CONTEXT — e.g., pre-screen adjustments that apply to this stage}

---

> **⚠ Design mode — not yet available.** See note at top of document.
