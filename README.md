# Responsible AI Governance Skill

An agentic skill that assesses AI/ML applications against the AWS
Well-Architected Responsible AI Lens. It runs entirely inside your own
development environment - your source code and documentation are never sent
anywhere outside your machine or your own AWS account.

## What this does

- **Audits an existing codebase** (brownfield) against 24 Responsible AI
  rules and a 50-item best-practices questionnaire derived from the AWS
  Well-Architected Responsible AI Lens
- Produces a weighted maturity score, a per-pillar breakdown, and a
  self-contained HTML report you can share with your team
- Tracks score history over time as you make improvements
- Supports policy customization (disable/downgrade specific rules with a
  documented reason) at project or org scope

## What this is, and isn't

This skill turns the [AWS Well-Architected Framework — Responsible AI
Lens](https://docs.aws.amazon.com/wellarchitected/latest/responsible-ai-lens/responsible-ai-lens.html)
(initial release, November 19, 2025) into something you can run against your
own codebase today: a weighted maturity score, a pillar-by-pillar breakdown,
and concrete findings tied to actual files and functions - in minutes, not
in the time it takes to schedule a formal review. Using this skill you can also assess your processes alignment with AWS Responsible AI Well Architected lens by providing the tool documentation or answering process related questions your self. 

The Lens's 99 best practices are mapped into 24 higher-level rules across
four pillars, purpose-built to make the assessment approachable to read,
prioritize, and act on. Best-practice text is reproduced verbatim from the
Lens; see `_meta` in `data/shared/lens-bps.json` for the exact source and
publication date.

The 24-rule mapping is this skill's own addition, not part of the Lens
itself. Because of that restructuring, the score and the granularity of any
individual finding may not line up exactly with how the Lens's 99 best
practices are organized.

## How your data is handled

- Your source code and documentation are read by your IDE agent (e.g. Kiro)
  during evidence gathering (Step 2) and questionnaire pre-fill (Step 4).
  **This skill itself does not send that content anywhere** - but your IDE
  agent is a separate piece of software with its own model backend, and this
  skill has no visibility into or control over where that backend runs or
  what it does with the content it's given. If your IDE agent's model runs
  locally, this step is local. If it calls a remote model - Bedrock or
  otherwise - repository content leaves the machine at that point, before
  this skill's own Bedrock call ever happens. Check your IDE agent's own
  data-handling documentation to know which applies to you
- Separately, and only once you say `run audit`, **this skill makes its own
  call to Amazon Bedrock, using your own AWS account and credentials** - the
  same trust boundary as any other Bedrock call you make. The prompt
  includes the evidence gathered in Step 2, which quotes excerpts of your
  source code and documentation verbatim. The evidence file is written to
  disk and you are asked to review it before the audit runs, so you can see
  and edit exactly what will be sent to Bedrock. This gate controls what
  reaches Bedrock - it does not control what your IDE agent's own model
  already saw while gathering that evidence in Step 2, which happened
  earlier and is governed by your IDE agent's own data handling, not by
  this skill
- All output (evidence, findings, scores, reports) is written to a
  `rai-governance/` folder inside your project, on your machine

## Verdicts are advisory - human review is required

- **Each rule's compliance verdict is produced by a language model**, not by a
  deterministic check. Treat the report as a structured starting point for review,
  not as an authoritative compliance record.
- **Verdicts can be influenced by the repository being audited.** Evidence is
  quoted from the codebase into the prompt, so text in a code comment, docstring,
  or document can steer the model's verdict. Audit repositories you trust, and
  independently confirm any finding you would need to defend.
- **Two review gates are built into the workflow, and the skill waits at both.**
  Step 2 writes `audit-ide-evidence.md` and waits for you to say `run audit`, so
  you can inspect and correct the evidence before any verdict or score is
  produced. Step 4 writes `audit-questionnaire-review.md` and waits for `submit`,
  so you can change any pre-filled answer before it is recorded. Neither gate is
  optional.
- **Rules without evidence are excluded, not passed.** A rule the agent could not
  gather evidence for is recorded as `needs_input` and left out of the score
  entirely rather than counted as compliant.

## Prerequisites

- Python 3.11 or later
- `boto3` (`pip install boto3`)
- AWS credentials with Amazon Bedrock `InvokeModel` permission, configured
  in your environment (e.g. via `aws configure` or your organization's SSO)
- **Model access enabled for the model you use.** The default,
  `us.anthropic.claude-sonnet-4-6`, is a US cross-region inference profile, so
  `AWS_REGION` must be a US region and model access must be granted in that
  account. `audit-run.py` defaults to `us-east-1`. Override either with the
  `AWS_REGION` and `RAI_LLM_MODEL` environment variables
- An agentic IDE that can read and act on a skill's `SKILL.md` (Kiro is one
  example; any IDE agent that supports this skill format works)

Verify your setup:

```bash
aws sts get-caller-identity
python3 -c "import boto3; print(boto3.__version__)"
```

## Cost

The audit calls Amazon Bedrock in your own AWS account and is billed at standard
per-token rates for whichever model you use. A single audit run issues up to 24
requests - one per rule, 8 at a time. Each request carries that rule's evidence,
capped at 60,000 characters, which is on the order of 15,000 input tokens, so a
full run at the cap is roughly 360,000 input tokens plus a short JSON response
per rule. Most runs land well below the cap because few rules produce that much
evidence.

Re-generating the report and re-computing the score make no Bedrock calls and cost
nothing, so iterating on a report after the audit is free. To tighten the budget,
lower `MAX_EVIDENCE_CHARS` or `MAX_PARALLEL_WORKERS` at the top of
`audit-run.py`.

## Installation

1. Clone this repository
2. Copy the `.kiro/skills/responsible-ai-governance` folder into your project's
   `.kiro/skills/` directory (create it if it doesn't exist):

   ```bash
   mkdir -p /path/to/your/project/.kiro/skills
   cp -R .kiro/skills/responsible-ai-governance /path/to/your/project/.kiro/skills/
   ```

3. Open your project in Kiro (or your agentic IDE of choice)

## Running your first audit

In your IDE's chat, ask:

> "Run a Responsible AI audit on my application."

The skill will walk you through:

1. **Project configuration** - a short set of questions about your
   application's risk profile (answered by editing a generated file)
2. **Evidence gathering** - the skill reads your code and documentation and
   summarizes findings per rule
3. **Audit** - findings are sent to Amazon Bedrock (in your AWS account) for
   a verdict on each rule
4. **Questionnaire** - a set of governance and process questions,
   pre-filled from your documentation where possible, for you to review
5. **Report generation** - an HTML report with your score, pillar
   breakdown, and detailed findings

Full step-by-step behavior is documented in `SKILL.md` inside the skill package.

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.
