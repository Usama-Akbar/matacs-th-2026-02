"""Deterministic scoring and ranking (the rule-based half of the pipeline).

Takes the admin's criteria config and the per-proposal extractions (from
extract.py, or the hand-checked fixtures) and produces:
  - ranking.json in the format the brief asks for
  - a run record with the full per-criterion breakdown for the audit log

No AI is used here. Same inputs always give the same output.

Usage:
  python score.py                                  # fixtures -> ../ranking.json
  python score.py --extractions out/extractions.json --out out/ranking.json
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
DEFAULT_CRITERIA = HERE / "criteria" / "commercial-solar-v1.json"
DEFAULT_EXTRACTIONS = HERE / "fixtures" / "extractions.json"
DEFAULT_OUT = HERE.parent / "ranking.json"


def sha256_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def field(extraction, name):
    return extraction["fields"].get(name, {"status": "not_stated", "value": None})


def usable(f):
    """A value only counts if it was found and (in live mode) its evidence checked out."""
    return f["status"] == "found" and f["value"] is not None


def check_gates(criteria, extraction):
    """Mandatory pass/fail criteria and hard project limits.

    Returns (failures, flags). A failure makes the proposal ineligible.
    A flag means a person has to look before it can be ranked.
    """
    failures, flags = [], []

    for gate in criteria["mandatory"]:
        for name in gate["fields"]:
            f = field(extraction, name)
            if f["status"] in ("unclear", "unverified"):
                flags.append(f"{gate['label']}: could not confirm '{name}' ({f['status']})")
            elif not usable(f) or f["value"] is not True:
                failures.append(f"{gate['label']}: not met" + (f" ({f['note']})" if f.get("note") else ""))

    for crit in criteria["weighted"]:
        limit_key = crit.get("hard_max")
        if not limit_key:
            continue
        limit = criteria["project"][limit_key]
        f = field(extraction, crit["field"])
        unit = crit.get("unit", "")
        if usable(f) and f["value"] > limit:
            failures.append(f"{crit['label']}: {f['value']:,} {unit} is over the {limit:,} {unit} limit")
        elif not usable(f):
            flags.append(f"{crit['label'].lower()} not stated, so the {limit:,} {unit} limit cannot be confirmed")

    for item in extraction.get("embedded_instructions", []):
        flags.append(f"possible manipulation: {item['summary']} ({item['location']}); "
                     "the instruction was ignored and the bid scored on its facts only")

    for name, f in extraction["fields"].items():
        if f["status"] == "unverified":
            flags.append(f"Evidence for '{name}' was not found in the document text")

    return failures, flags


def warnings_for(criteria, extraction):
    """Things a reviewer should know that do not block ranking."""
    out = []
    window_start = criteria["project"]["assessment_year"] - criteria["project"]["experience_window_years"]
    exp = field(extraction, "qualifying_installs_count")
    if exp.get("earliest_year") and exp["earliest_year"] < window_start:
        out.append(f"experience count starts in {exp['earliest_year']}, before the {window_start} window")
    return out


def best_in_pool(pool, name, lower_is_better):
    values = [field(e, name)["value"] for e in pool if usable(field(e, name))]
    if not values:
        return None
    return min(values) if lower_is_better else max(values)


def score_criterion(crit, extraction, pool):
    """Return the fraction (0..1) of the criterion's weight earned, and a short note."""
    rule = crit["rule"]

    if rule in ("higher_is_better", "lower_is_better"):
        lower = rule == "lower_is_better"
        f = field(extraction, crit["field"])
        if not usable(f):
            return 0.0, "not stated"
        best = best_in_pool(pool, crit["field"], lower)
        frac = best / f["value"] if lower else f["value"] / best
        unit = crit.get("unit", "")
        return frac, f"{f['value']:,} {unit}" + (", best in set" if f["value"] == best else f" vs best {best:,}")

    if rule == "average_of_higher_is_better":
        parts = []
        for name in crit["fields"]:
            f = field(extraction, name)
            best = best_in_pool(pool, name, lower_is_better=False)
            parts.append(f["value"] / best if usable(f) and best else 0.0)
        values = [field(extraction, n)["value"] for n in crit["fields"]]
        labels = [n.replace("_warranty_years", "") for n in crit["fields"]]
        return sum(parts) / len(parts), ", ".join(f"{v} yr {l}" for v, l in zip(values, labels))

    if rule == "checklist":
        met = [n for n in crit["fields"] if usable(field(extraction, n)) and field(extraction, n)["value"] is True]
        missing = [n for n in crit["fields"] if n not in met]
        note = f"{len(met)} of {len(crit['fields'])} items" + (f", missing {', '.join(m.replace('_', ' ') for m in missing)}" if missing else "")
        return len(met) / len(crit["fields"]), note

    raise ValueError(f"Unknown rule '{rule}' in criterion '{crit['id']}'")


def build_reason(status, total, breakdown, failures, flags, warnings, rank=None, next_total=None):
    if status == "ineligible":
        return "Ineligible: " + "; ".join(failures)
    if status == "flagged":
        return (f"Held for human review (provisional score {total}): " + "; ".join(flags + warnings)) + "."
    strongest = max(breakdown, key=lambda b: b["fraction"])
    weakest = min(breakdown, key=lambda b: b["fraction"])
    reason = f"Passed all mandatory checks; score {total}"
    if next_total is not None:
        reason += f", {round(total - next_total, 1)} ahead of the next ranked bid"
    reason += f". Strongest: {strongest['label'].lower()} ({strongest['note']})"
    if weakest["fraction"] < 1:
        reason += f"; weakest: {weakest['label'].lower()} ({weakest['note']})"
    if warnings:
        reason += "; note: " + "; ".join(warnings)
    return reason + "."


def run(criteria, extractions):
    letters = sorted(k for k in extractions if not k.startswith("_"))
    gates = {p: check_gates(criteria, extractions[p]) for p in letters}

    # Relative scoring compares against every bid that passed the gates
    # (including flagged ones, whose facts are still on the table).
    pool = [extractions[p] for p in letters if not gates[p][0]]

    results = []
    for p in letters:
        failures, flags = gates[p]
        status = "ineligible" if failures else "flagged" if flags else "ranked"
        breakdown, total = [], None
        if status != "ineligible":
            for crit in criteria["weighted"]:
                frac, note = score_criterion(crit, extractions[p], pool)
                breakdown.append({
                    "criterion": crit["id"], "label": crit["label"], "weight": crit["weight"],
                    "fraction": round(frac, 4), "points": round(frac * crit["weight"], 2), "note": note,
                })
            total = round(sum(b["points"] for b in breakdown), 1)
        results.append({
            "proposal": p, "status": status, "total": total, "breakdown": breakdown,
            "failures": failures, "flags": flags, "warnings": warnings_for(criteria, extractions[p]),
        })

    # Ties break on lower price, then proposal letter, so the order never depends on input order.
    ranked = sorted(
        (r for r in results if r["status"] == "ranked"),
        key=lambda r: (-r["total"], field(extractions[r["proposal"]], "total_price_cad")["value"] or 0, r["proposal"]),
    )
    for i, r in enumerate(ranked):
        r["rank"] = i + 1
        r["next_total"] = ranked[i + 1]["total"] if i + 1 < len(ranked) else None

    status_order = {"ranked": 0, "flagged": 1, "ineligible": 2}
    results.sort(key=lambda r: (status_order[r["status"]], r.get("rank") or 0, -(r["total"] or 0), r["proposal"]))

    ranking = []
    for r in results:
        ranking.append({
            "proposal": r["proposal"],
            "rank": r.get("rank"),
            "status": r["status"],
            "score": r["total"] if r["status"] == "ranked" else None,
            "reason": build_reason(r["status"], r["total"], r["breakdown"], r["failures"],
                                   r["flags"], r["warnings"], r.get("rank"), r.get("next_total")),
        })
    return ranking, results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--criteria", default=DEFAULT_CRITERIA)
    ap.add_argument("--extractions", default=DEFAULT_EXTRACTIONS)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--record", default=HERE / "out" / "run-record.json")
    args = ap.parse_args()

    criteria = json.loads(Path(args.criteria).read_text())
    extractions = json.loads(Path(args.extractions).read_text())
    ranking, results = run(criteria, extractions)

    Path(args.out).write_text(json.dumps(ranking, indent=2) + "\n")

    record = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "category_id": criteria["category_id"],
        "criteria_version": criteria["criteria_version"],
        "criteria_sha256": sha256_of(args.criteria),
        "extractions_sha256": sha256_of(args.extractions),
        "scoring_code": "score.py",
        "results": results,
    }
    Path(args.record).parent.mkdir(parents=True, exist_ok=True)
    Path(args.record).write_text(json.dumps(record, indent=2) + "\n")

    for r in ranking:
        print(f"{r['proposal']}  rank={r['rank']!s:<4} {r['status']:<10} score={r['score']!s:<5} {r['reason']}")


if __name__ == "__main__":
    main()
