# Responsible AI Audit Report — {CODEBASE_NAME}
## AWS Well-Architected Responsible AI Lens

**Project:** {PROJECT_ID}
**Tier:** {TIER} — {TIER_NAME}
**Audit Mode:** {AUDIT_MODE} ({AGENT_LABEL})
**Generated:** {GENERATED_AT}

> The full interactive report is in `rai-audit-report-{AGENT_LABEL}.html`. This markdown file is a summary for git diffs and quick reference.

---

## Overall Maturity

- **Weighted Score:** {OVERALL_SCORE}%
- **Maturity:** {MATURITY_LABEL}

### Pillar Breakdown

| Pillar | Score |
|---|---|
| RAIUC — Use Case Definition | {RAIUC_SCORE}% |
| RAIDD — Design & Development | {RAIDD_SCORE}% |
| RAIER — Evaluation & Release | {RAIER_SCORE}% |
| RAIOP — Operations | {RAIOP_SCORE}% |

### Finding Counts

| Status | Count |
|---|---|
| ✅ Compliant | {N_COMPLIANT} |
| ⚠️ Partial | {N_PARTIAL} |
| ❌ Non-compliant | {N_NON_COMPLIANT} |
| ❓ Unknown | {N_UNKNOWN} |
| 📥 Needs Input | {N_NEEDS_INPUT} |
| ⏸ Disabled | {N_DISABLED} |

---

## Pre-Screen Configuration

| Question | Answer |
|---|---|
| Hosted model (no fine-tuning) | {HOSTED_MODEL} |
| Regulated data (HIPAA / GDPR / financial) | {REGULATED_DATA} |
| Has formal AI governance process | {HAS_GOVERNANCE} |

{IF applied_adjustments:}
**Pre-screen adjustments applied:**
{FOR EACH ADJUSTMENT:}
- **{rule_id}:** {note}

---

## Code Findings — All 24 Rules

| Rule | Status | Priority | Pillar | Reasoning |
|---|---|---|---|---|
{FOR EACH FINDING:}
| {rule_id} — {name} | {status} | {priority} | {pillar} | {reasoning_truncated} |

---

## Questionnaire Coverage

{FOR EACH BLOCK with answers:}

### {block_name}
{FOR EACH ANSWER:}
- **{lens_code}** ({verdict}): {response_truncated}

---

## Score Trend

| Snapshot | When | Trigger | Score | Δ | Label |
|---|---|---|---|---|---|
{FOR EACH SNAPSHOT:}
| {snapshot_id} | {timestamp} | {trigger} | {weighted}% | {delta} | {label} |

---

## Top Priority Findings

{FOR EACH FINDING WITH priority == "high" AND status IN ("non_compliant", "partial"):}

### {rule_id} — {name}
- **Status:** {status}
- **Pillar:** {pillar}
- **Evidence:** {evidence}
- **Reasoning:** {reasoning}
- **Remediation:** {remediation if available else "See rule definition in rules.json"}

---

## References

- [AWS Well-Architected Responsible AI Lens](https://docs.aws.amazon.com/wellarchitected/latest/responsible-ai-lens/responsible-ai-lens.html)
- Full interactive report: `rai-audit-report-{AGENT_LABEL}.html`
- Per-project state: `rai-governance/`
- Skill source: `.kiro/skills/responsible-ai-governance/`
