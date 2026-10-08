# Responsible AI Audit — Project Configuration
# Review each question and fill in your answer where indicated.
# When done, tell me "submit config" and I will apply the settings.

---

## Q1 — Application Path
**Question:** What is the path to your AI application codebase?
**Answer:** TODO: /path/to/your/app

---

## Q2 — Risk Level
**Question:** What risk level is this project?
- Low Risk (1) — internal tool, no user-facing AI decisions, no regulated data
- Standard (2) — consumer-facing AI, non-regulated domain
- High Risk (3) — healthcare, finance, legal, agentic AI, or regulated data
**Answer:** TODO: enter 1, 2, or 3

---

## Q3 — Hosted Model
**Question:** Are you using a hosted foundation model (Amazon Bedrock, OpenAI, Anthropic) with no custom training or fine-tuning?
Note: If yes, 18 dataset governance questions will be auto-resolved as not applicable.
**Answer:** TODO: yes or no

---

## Q4 — Regulated Data
**Question:** Does this project handle regulated data — HIPAA, GDPR, financial, or legal data?
Note: If yes, privacy rules will be assessed strictly.
**Answer:** TODO: yes or no

---

## Q5 — Formal Governance
**Question:** Does your organization have a formal AI governance process — a risk registry, approval committee, or compliance review board?
Note: If yes, some governance questions will be simplified.
**Answer:** TODO: yes or no

---

## Q6 — Project Identifier
**Question:** What short identifier should be used for this audit? (e.g. my-project-v1)
**Answer:** TODO: enter a short project id

---

## Q7 — Documentation & Context Paths
**Question:** Where are your requirements, design, architecture, and other context documents?
List one path per line. These folders will be used throughout the audit — for code
evidence (doc-based rules), the questionnaire pre-fill, and the final report.
Include any folder that contains:
  - Requirements or user stories
  - Application or functional design docs
  - Architecture or infrastructure docs
  - Risk assessments or governance records
  - NFR or evaluation criteria
  - Any other written context about the AI system
**Answer:**
  TODO: /path/to/docs-folder-1
  TODO: /path/to/docs-folder-2 (add more lines as needed)
