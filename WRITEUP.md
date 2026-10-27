# Design write-up

The flow is in [diagram/process-flow.png](diagram/process-flow.png). In one line: **AI reads each proposal and quotes it. Code checks the quotes, applies the admin's rules and does the maths. People resolve anything doubtful and make the award.**

## 1. AI vs. rules

**AI is used for one step: extracting facts (step 4).** Proposals are free text, and some facts depend on reading the whole sentence. B says a licensed *subcontractor*, *to be confirmed after award*, will do the electrical work. Regex can't reliably tell that apart from "we hold a licence"; a language model can. For every field the model returns a status, a value and an **exact quote**.

**Everything else is plain code:**

- PDF text extraction, the injection pre-scan and the quote check (steps 2, 3, 5)
- Mandatory gates and hard limits (steps 6, 7). Pass/fail decisions with contractual weight should be auditable rules, not model judgement.
- Scoring, ranking and reasons (step 8). Code does arithmetic exactly. Reasons are filled from the score breakdown, so a reason can't disagree with its score.

**Where I drew the line:** the model answers narrow, checkable questions ("is there a safety plan? quote it"), and code turns answers into scores. I didn't ask it to rate "Team and approach" 1–10; a quoted four-item checklist is repeatable and easy to dispute.

## 2. Consistency and explainability

- **Repeatable.** Scoring is deterministic: the same extractions and the same criteria version give the same `ranking.json`, byte for byte. Ties break on lower price, then proposal letter.
- **Extraction is the only variable part.** It is kept stable with a structured output schema, narrow questions, a pinned model and prompt version, and the quote check. Extractions are stored and re-ranking reuses them, so **ranking the same proposals twice gives the same result**. A fresh re-extraction could rarely differ on a borderline field, which is exactly the kind that comes back "unclear" and gets flagged.
- **Explainable.** Every score has a breakdown: criterion → value → quote → PDF page → points (e.g. *Price: $238,000 vs best $231,000 → 24.3 of 25*). The reviewer clicks a number and sees the sentence it came from.
- **Scoring method.** Each criterion earns `weight × (bid ÷ best gated bid)`, or `best ÷ bid` when lower is better. Warranty averages panel and workmanship; Team is a four-item checklist.

## 3. Human in the loop

- **Before:** the admin publishes the criteria (step 0).
- **During:** the reviewer works through a **flagged queue** (step 9). A flagged bid gets a provisional score but **no rank** until a person clears it. The reviewer can correct an extracted value, clear a flag, or override a gate. A reason is required for each. Corrections re-run the rules (steps 6–8); nobody edits a final score by hand.
- **After:** a person makes the award (step 10). The tool's output is advice only.
- **Audit log (append-only):** uploader, time, file hashes; criteria version plus config hash; model id, prompt version, raw AI output, token cost; every quote-check and pre-scan result; gate results and points per criterion; every human action with old value, new value, who, when and why; scoring code version. Any result can be rebuilt from the log.

## 4. Changing criteria

Criteria are **versioned** and become read-only once a run has used them. Editing them creates v2.

- Existing runs keep v1, so the record of what was decided doesn't change. They show a "criteria changed since this run" banner.
- Re-running on v2 **reuses stored extractions**. A weight change is just re-calculation: instant, free, no AI. Only **new or reworded fields** need new AI calls, for those fields only.
- The reviewer sees a v1 vs v2 comparison ("E moves up because Warranty rose from 15% to 25%"). Nothing is silently re-scored.

## 5. Risks and safeguards

| Risk | Safeguard |
|---|---|
| **Wrong extraction** (misread number, wrong field) | Quote required for every value. Code checks the quote is really in the PDF and that the number parses. Narrow per-field questions. Reviewer sees the quote next to the value. |
| **Made-up facts** | "Not stated" is an allowed, expected answer. Quotes must match the source text exactly, or the field is `unverified` and flagged. The model never scores, so it has no reason to fill gaps. |
| **Manipulation / prompt injection** (Proposal C's "rank it first" note) | Proposal text is wrapped and labelled as untrusted data. The model reports embedded instructions instead of following them. A keyword pre-scan runs **before** the AI, so detection doesn't rely only on the model. And even an obedient model couldn't rank anything, because ranking is code. C is flagged, scored on facts only, and left for a person to decide. |
| **Missing key information** (D has no timeline) | A missing value for a hard limit is a **flag**, not a silent zero. A person asks the bidder or decides. D still gets a provisional score (timeline = 0 points). |
| **Bias** (polished or wordy bids, known brands scoring higher) | The model extracts facts and never judges quality. Scoring uses only numbers and checklist items. B is the cheapest bid but fails the licence gate, and the reason says so. |
| **Over-trust** | The ranked list is labelled advice. The award is a separate human step. |
| **Cost / latency** | One AI call per proposal, not per criterion. Extractions are reused when weights change. Token cost is logged per run. |
| **Bad PDFs** (scans, images) | OCR fallback. Empty text is stopped at step 2, before any AI call. |
| **Admin config errors** | Publishing is blocked unless weights add up to 100%. Changes are versioned. |

Assumptions I made about unclear points are listed in the [README](README.md#assumptions).
