# AI Proposal Triage Design

| | |
|---|---|
| **Name** | Usama Akbar |
| **Reference** | MATACS-TH-2026-02 |
| **Role** | Associate Software Developer |
| **Time actually spent** | _TODO: fill in_ |

A design for a tool that takes contractor proposals, checks them against criteria the admin has set, and returns a ranked list with a reason for each position. A person makes the final award.

**The core idea:** AI does only the reading. It pulls facts out of each proposal and quotes the sentence each fact came from. Plain code checks those quotes, applies the pass/fail rules, does the scoring and builds the ranking. A person reviews anything doubtful and makes the award.

## Files

| File | What it is |
|---|---|
| [README.md](README.md) | This page |
| [diagram/process-flow.png](diagram/process-flow.png) | Process flow from upload to ranked output. AI steps, rule steps and human checkpoints are colour-coded. |
| [WRITEUP.md](WRITEUP.md) | Answers to the five questions (under 1,000 words) |
| [PROMPTS.md](PROMPTS.md) | The extraction prompt exactly as sent, plus the output schema |
| [ranking.json](ranking.json) | Expected ranking of proposals A–E |
| [prototype/](prototype/README.md) | Optional: a Python script that does the scoring and ranking (produces `ranking.json`) and one that runs the AI extraction |
| [.env.example](.env.example) | Placeholder for the API key. No keys are committed. |

## Result on the sample set

| Rank | Proposal | Status | Score | Why |
|---|---|---|---|---|
| 1 | A | ranked | 98.0 | Passes every mandatory check. Most experience (14 installs) and the shortest committed timeline (12 weeks). Its only weaker point is a 10-year workmanship warranty against E's 12. |
| 2 | E | ranked | 84.8 | Passes every mandatory check. Best warranty and a full team/approach checklist, but much less experience (8 installs vs 14). |
| – | C | flagged | (77.1) | Contains text addressed to automated review systems asking to be ranked first with full marks. The tool ignores it and scores C on its facts only, but holds it for a person to decide. Its experience count also starts in 2020, which is partly outside the 5-year window. |
| – | D | flagged | (69.8) | No committed timeline ("after site assessment"), so the 16-week requirement can't be confirmed. Lowest price, but held until a person gets a timeline from the bidder. |
| – | B | ineligible | – | Fails the licence gate: electrical work would go to a subcontractor still "to be confirmed". It is the cheapest bid, which is exactly why the gates run before any scoring. |

Scores in brackets are provisional. Flagged bids are not ranked until a person clears them. If a flag is cleared, the tool re-runs the rules. For example, if D confirms 12 weeks, it scores 84.8. That is a near-tie with E (84.82 vs 84.80), and D comes out ahead because its price is lower. A gap that small is a reason for a person to read both bids, not for the tool to pick one.

How the scores are worked out: each criterion earns *weight × (this bid ÷ best bid that passed the gates)*, or *best ÷ this bid* where lower is better (price, weeks). The full per-criterion breakdown is written to `prototype/out/run-record.json` when you run `python prototype/score.py`.

## Assumptions

- "Last 5 years" is counted by calendar year from 2026, so 2021 onwards. C's count starts in 2020, so some of it may fall outside the window. This is noted on C.
- A licence held only by a subcontractor that is "to be confirmed" does not meet "licence held by the bidder", so B is **ineligible**. A reviewer can override this with a reason.
- "Schedule after site assessment" means no committed timeline. The 16-week requirement can't be confirmed, so D is **flagged**, not ineligible.
- "Weekly progress reports" (C) are project reporting, not performance monitoring.
- Flagged bids stay in the comparison pool used for relative scoring, because their facts are real. If a flagged bid is rejected later, the others are re-scored automatically.

## How I used AI tools

_TODO: write this in your own words (2–3 sentences). Must include at least one place where you disagreed with or corrected the AI's output, and why._
