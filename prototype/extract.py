"""AI extraction step: one Claude call per proposal, then plain-code checks.

Reads the prompts from ../PROMPTS.md (so the doc and the code cannot drift),
fills them from the admin's criteria config, and writes extractions in the
shape score.py expects.

Usage:
  cp ../.env.example ../.env   # then add your key
  pip install -r requirements.txt
  # put the sample proposal text in samples/A.txt ... samples/E.txt
  python extract.py
  python score.py --extractions out/extractions.json --out out/ranking.json
"""

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

import anthropic

HERE = Path(__file__).parent
PROMPTS_MD = HERE.parent / "PROMPTS.md"
PROMPT_VERSION = "extract-v1"
MODEL = "claude-opus-5-5"

# Rule-based pre-scan. Cheap, deterministic, and runs before any AI sees the text.
INJECTION_PATTERNS = [
    r"automated (review|system|scoring)",
    r"\b(ai|language model|llm|assistant)\b.{0,40}\b(must|should|rank|score|ignore)",
    r"ignore (all |any )?(previous|prior|above) (instructions|rules)",
    r"\brank (it|this|us)\b.{0,20}\bfirst\b",
    r"full (marks|score|points)",
    r"pre-?approved",
]

JSON_TYPES = {"boolean": "boolean", "integer": "integer", "number": "number", "string": "string"}


def load_env():
    env = HERE.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def load_prompt(name):
    text = PROMPTS_MD.read_text()
    match = re.search(rf"<!-- prompt:{name} -->\s*```text\n(.*?)\n```", text, re.S)
    if not match:
        raise RuntimeError(f"Prompt block '{name}' not found in PROMPTS.md")
    return match.group(1)


def output_schema(criteria):
    fields = {}
    for name, spec in criteria["fields"].items():
        props = {
            "status": {"type": "string", "enum": ["found", "not_stated", "unclear"]},
            "value": {"type": [JSON_TYPES[spec["type"]], "null"]},
            "evidence": {"type": ["string", "null"]},
            "note": {"type": ["string", "null"]},
        }
        for extra, extra_type in spec.get("extra_properties", {}).items():
            props[extra] = {"type": [JSON_TYPES[extra_type], "null"]}
        fields[name] = {"type": "object", "additionalProperties": False,
                        "required": list(props), "properties": props}
    instruction = {"type": "object", "additionalProperties": False,
                   "required": ["quote", "location", "summary"],
                   "properties": {k: {"type": "string"} for k in ("quote", "location", "summary")}}
    return {
        "type": "object", "additionalProperties": False,
        "required": ["fields", "embedded_instructions"],
        "properties": {
            "fields": {"type": "object", "additionalProperties": False,
                       "required": list(fields), "properties": fields},
            "embedded_instructions": {"type": "array", "items": instruction},
        },
    }


def user_message(criteria, proposal_id, proposal_text):
    field_list = "\n".join(f"- {name} ({spec['type']}): {spec['question']}"
                           for name, spec in criteria["fields"].items())
    return load_prompt("user").format(
        category_label=criteria["category_label"],
        project_description=criteria["project"]["description"],
        field_list=field_list,
        proposal_id=proposal_id,
        proposal_text=proposal_text,
    )


def normalise(text):
    text = text.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


def verify_evidence(extraction, source_text):
    """Downgrade any field whose quote is not really in the document."""
    source = normalise(source_text)
    for name, f in extraction["fields"].items():
        if f["status"] == "not_stated":
            continue
        if not f.get("evidence") or normalise(f["evidence"]) not in source:
            f["note"] = f"Quote not found in document. Model said: {f['status']}, {f['value']!r}"
            f["status"] = "unverified"
    return extraction


def prescan(source_text):
    hits = []
    for sentence in re.split(r"(?<=[.!?])\s+", source_text):
        if any(re.search(p, sentence, re.I) for p in INJECTION_PATTERNS):
            hits.append({"quote": sentence.strip()[:300], "location": "pre-scan",
                         "summary": "Matched an injection pattern in the keyword pre-scan"})
    return hits


def extract_one(client, criteria, proposal_id, proposal_text):
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium",
                       "format": {"type": "json_schema", "schema": output_schema(criteria)}},
        system=load_prompt("system"),
        messages=[{"role": "user", "content": user_message(criteria, proposal_id, proposal_text)}],
    )
    if response.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError(f"Proposal {proposal_id}: model stopped with {response.stop_reason}")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text), response


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--criteria", default=HERE / "criteria" / "commercial-solar-v1.json")
    ap.add_argument("--samples", default=HERE / "samples")
    ap.add_argument("--out", default=HERE / "out" / "extractions.json")
    args = ap.parse_args()

    load_env()
    criteria = json.loads(Path(args.criteria).read_text())
    client = anthropic.Anthropic()
    results, calls = {}, []

    for path in sorted(Path(args.samples).glob("*.txt")):
        proposal_id = path.stem
        text = path.read_text()
        try:
            extraction, response = extract_one(client, criteria, proposal_id, text)
        except anthropic.APIConnectionError as e:
            raise SystemExit(f"Could not reach the API: {e}")
        except anthropic.APIStatusError as e:
            raise SystemExit(f"API error {e.status_code} on proposal {proposal_id}: {e.message}")
        extraction = verify_evidence(extraction, text)
        extraction["embedded_instructions"] += prescan(text)
        results[proposal_id] = extraction
        calls.append({
            "proposal": proposal_id, "model": response.model, "prompt_version": PROMPT_VERSION,
            "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens,
        })
        unverified = [n for n, f in extraction["fields"].items() if f["status"] == "unverified"]
        print(f"{proposal_id}: extracted, {len(unverified)} unverified, "
              f"{len(extraction['embedded_instructions'])} embedded instruction(s)")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2) + "\n")
    (out.parent / "extraction-calls.json").write_text(json.dumps(calls, indent=2) + "\n")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
