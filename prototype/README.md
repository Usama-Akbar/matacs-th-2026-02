# Prototype

A small script version of the design. Python 3.10+.

| File | What it does | Uses AI? |
|---|---|---|
| [criteria/commercial-solar-v1.json](criteria/commercial-solar-v1.json) | The admin's criteria for this category, as the admin screens would save them (versioned) | No |
| [extract.py](extract.py) | Pre-scans each proposal for injection text, sends the [PROMPTS.md](../PROMPTS.md) prompt to Claude, then checks every quote against the source text | Yes (one call per proposal) |
| [score.py](score.py) | Mandatory gates, hard limits, weighted scoring, ranking and reasons. Writes `ranking.json` and an audit run record | No |
| [fixtures/extractions.json](fixtures/extractions.json) | Hand-checked extraction results for A–E, so scoring runs without an API key | — |

## Run the scoring (no API key needed)

```bash
cd prototype
python score.py          # writes ../ranking.json and out/run-record.json
```

Running it twice gives the same `ranking.json`, byte for byte.

## Run the full pipeline with AI extraction

```bash
cp ../.env.example ../.env       # add ANTHROPIC_API_KEY
pip install -r requirements.txt
# save the five sample proposals as samples/A.txt … samples/E.txt (git-ignored)
python extract.py                # writes out/extractions.json + out/extraction-calls.json
python score.py --extractions out/extractions.json --out out/ranking.json
```

Then compare `out/ranking.json` with the committed `../ranking.json`. Any difference points at an extraction to look at.

**Status:** the scoring path is tested. The prompt rendering, schema building, pre-scan and quote check were tested offline. The live API call was not run for this submission, so I have not checked model output against the fixtures.
