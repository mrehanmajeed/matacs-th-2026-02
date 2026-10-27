"""Deterministic triage: mandatory gates -> weighted scoring -> status -> ranking -> template reasons.

No AI in this file. Stdlib only. Each run is appended to a local, gitignored run log.
Usage: python prototype/triage.py [--criteria FILE] [--facts FILE] [--out FILE] [--log FILE]
"""
import argparse
import datetime
import getpass
import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).parent


def fact(proposal, field):
    """Return (value, usable). Usable = stated, non-null and evidence verified (default True)."""
    f = proposal["facts"].get(field, {})
    usable = f.get("status") == "stated" and f.get("value") is not None and f.get("verified", True)
    return f.get("value"), usable


def fact_schema_fingerprint(criteria):
    """Hash of the fact field definitions only (names, types, ranges). Weight, method or threshold edits make a
    new criteria version but keep this fingerprint, so stored facts can be rescored with rules only."""
    fields = {n: [f["type"], f.get("range")] for n, f in criteria["fields"].items()}
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:16]


def validate_criteria(criteria):
    total = sum(c["weight"] for c in criteria["weighted"])
    if not math.isclose(total, 100):
        raise ValueError(f"weighted criteria must sum to 100, got {total}")


def gate(proposal, g, cons):
    """'fail' only on an explicitly stated value that breaks the rule; missing/unclear -> 'unconfirmed'."""
    result = "pass"
    for r in g["require"]:
        v, usable = fact(proposal, r["field"])
        if not usable:
            result = "unconfirmed"
        elif ("equals" in r and v != r["equals"]) or ("min_constraint" in r and v < cons[r["min_constraint"]]):
            return "fail"
    return result


def score_criterion(pool, crit, cons):
    """Return {letter: (sub_score 0..1, flag_kind or None)} for one weighted criterion over the pool."""
    fields = crit["fields"]
    if crit["method"] == "checklist":  # not stated counts as no credit, but is not a flag
        return {k: (sum(fact(p, f) == (True, True) for f in fields) / len(fields), None) for k, p in pool.items()}
    limit = cons[crit["limit"]] if "limit" in crit else None
    parts, flags = {k: [] for k in pool}, {k: None for k in pool}
    for f in fields:
        vals = {k: fact(p, f) for k, p in pool.items()}
        usable = [v for v, ok in vals.values() if ok and (limit is None or v <= limit)]
        best = (max if crit["method"] == "higher_better" else min)(usable, default=0)
        for k, (v, ok) in vals.items():
            if not ok:
                parts[k].append(0.0)
                flags[k] = "missing"
            elif limit is not None and v > limit:
                parts[k].append(0.0)
                flags[k] = "over_limit"
            elif crit["method"] == "higher_better":
                parts[k].append(v / best if best else 0.0)
            else:
                parts[k].append(best / v if v > 0 else 0.0)
    return {k: (sum(s) / len(s), flags[k]) for k, s in parts.items()}


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def join(items):
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def phrase(crit, kind, proposal, cons, eligible=False, field=None):
    """Reason phrase for one criterion (or one field of it, e.g. "best:workmanship_warranty_years");
    eligible=True says the claim only holds within the eligible pool."""
    field = field or crit["fields"][0]
    template = crit["phrases"].get(f"{kind}:{field}", crit["phrases"].get(kind))
    return template.format(v=fact(proposal, field)[0], limit=cons.get(crit.get("limit")),
                           eligible="eligible " if eligible else "")


def strict_leader(members, field, higher):
    """The one bid with the strictly highest (or lowest) stated value on a field; None on a tie."""
    vals = {k: fact(p, field)[0] for k, p in members.items() if fact(p, field)[1]}
    if len(vals) < 2:
        return None
    best = (max if higher else min)(vals.values())
    winners = [k for k, v in vals.items() if v == best]
    return winners[0] if len(winners) == 1 else None


def flag_texts(crit, kind, proposal, cons):
    """Flags for a criterion that scored 0, naming the real cause. An unverified fact is already flagged with its
    cause, an unclear one says so, and only a fact that is truly not stated gets the 'missing' phrase."""
    if kind == "over_limit":
        return [phrase(crit, "over_limit", proposal, cons)]
    out = []
    for field in crit["fields"]:
        f = proposal["facts"].get(field, {})
        if fact(proposal, field)[1] or f.get("verified", True) is False:
            continue
        text = (f"{field} is unclear and needs a person to confirm it ({crit['key']} scored 0)"
                if f.get("status") == "unclear" else phrase(crit, "missing", proposal, cons))
        if text not in out:
            out.append(text)
    return out


def triage(criteria, facts):
    validate_criteria(criteria)
    cons = criteria["constraints"]
    # A failed extraction has no facts to score: flag it for a person, keep it out of the comparison pool.
    failed = {k: p["extraction_error"] for k, p in facts["proposals"].items() if p.get("extraction_error")}
    props = {k: p for k, p in facts["proposals"].items() if k not in failed}
    rows = {}
    for k in sorted(props):
        gates = {g["key"]: gate(props[k], g, cons) for g in criteria["mandatory"]}
        rows[k] = {"proposal": k, "gates": gates, "sub": {}, "points": {}, "flags": [], "total": None,
                   "review_notes": props[k].get("review_notes", [])}

    # Normalisation pool: everything not explicitly failing a gate (ineligible bids never shift others' scores).
    pool = {k: props[k] for k, r in rows.items() if "fail" not in r["gates"].values()}
    for k in pool:
        p, r = props[k], rows[k]
        for g in criteria["mandatory"]:
            if r["gates"][g["key"]] == "unconfirmed":
                r["flags"].append(f"the {g['short']} check could not be confirmed")
        for note in p.get("suspicious_instructions", []):
            r["flags"].append(f"embedded instruction ignored ({note})")
        r["flags"] += [f"intake check: {note}" for note in p.get("intake_flags", [])]
        for field, f in p["facts"].items():
            if f.get("verified", True) is False:
                r["flags"].append(f"{field} unverified ({', '.join(f.get('verification_issues', ['check failed']))})")

    for crit in criteria["weighted"]:
        for k, (sub, flag) in score_criterion(pool, crit, cons).items():
            rows[k]["sub"][crit["key"]] = sub
            rows[k]["points"][crit["key"]] = crit["weight"] * sub
            if flag:
                rows[k]["flags"] += flag_texts(crit, flag, props[k], cons)

    for k in pool:
        rows[k]["total"] = sum(rows[k]["points"].values())
        rows[k]["status"] = "flagged" if rows[k]["flags"] else "ranked"
    for k, r in rows.items():
        if k not in pool:
            r["status"] = "ineligible"

    def sort_key(k):
        r = rows[k]
        return (-r["total"], *(-r["sub"][c] for c in criteria["tie_break"]), k)

    ranked = sorted((k for k in pool if rows[k]["status"] == "ranked"), key=sort_key)
    flagged = sorted((k for k in pool if rows[k]["status"] == "flagged"), key=sort_key)
    ineligible = sorted(k for k in rows if k not in pool)
    for i, k in enumerate(ranked, 1):
        rows[k]["rank"] = i
    for k in flagged + ineligible:
        rows[k]["rank"] = None
    eligible = sorted(pool, key=sort_key)  # ranked + flagged, same tie-breaks: provisional positions
    for k in flagged:
        rows[k]["provisional_position"] = eligible.index(k) + 1

    # Template reasons, built only from the facts and breakdown above.
    n_gates = len(criteria["mandatory"])
    passes = f"passes {'both' if n_gates == 2 else f'all {n_gates}'} mandatory checks"

    def claims(k, kind):
        """Superlatives only where k strictly leads ('best') or trails ('worst') the eligible bids on a field;
        'eligible' is added when an ineligible bid goes further overall. A full checklist is not a superlative."""
        out = []
        for c in criteria["weighted"]:
            if c["method"] == "checklist":
                if kind == "best" and math.isclose(rows[k]["sub"][c["key"]], 1):
                    out.append(phrase(c, "best", props[k], cons))
                continue
            higher = (c["method"] == "higher_better") == (kind == "best")
            for f in c["fields"]:
                if strict_leader(pool, f, higher) == k:
                    v = fact(props[k], f)[0]
                    beyond = any(fact(props[j], f)[1] and (fact(props[j], f)[0] > v if higher else fact(props[j], f)[0] < v)
                                 for j in ineligible)
                    out.append(phrase(c, kind, props[k], cons, beyond, f))
        return out

    for k in ranked + flagged:
        r = rows[k]
        strong, weak = claims(k, "best"), claims(k, "worst")
        if r["status"] == "ranked":
            reason = f"Ranked {ordinal(r['rank'])} because it {passes}" + (f" and has {join(strong)}" if strong else "")
            reason += (f", but {join(weak)}" if strong else f", but has {join(weak)}") if weak else ""
        else:
            reason = "Held for review: " + "; ".join(r["flags"] + r["review_notes"])
            reason += f"; strongest point{'s' if len(strong) > 1 else ''}: {join(strong)}" if strong else ""
            reason += (f"; provisional {r['total']:.1f}, {ordinal(r['provisional_position'])} of {len(eligible)}"
                       " eligible bids; not ranked until resolved")
        r["reason"] = reason + "."
    for k in ineligible:
        p, r = props[k], rows[k]
        fails = []
        for g in criteria["mandatory"]:
            if r["gates"][g["key"]] == "fail":
                notes = [p["facts"][q["field"]].get("note") for q in g["require"] if p["facts"].get(q["field"], {}).get("note")]
                fails.append(f"Fails the mandatory {g['short']} check" + (f": {notes[0]}" if notes else ""))
        # What it strictly leads on against every bid (an overall claim), to make clear those were not counted.
        despite = [phrase(c, "best", p, cons, field=f) for c in criteria["weighted"] if c["method"] != "checklist"
                   for f in c["fields"] if strict_leader(props, f, c["method"] == "higher_better") == k]
        r["reason"] = "; ".join(fails) + "; not scored" + (f" despite {join(despite)}" if despite else "") + "."
    for k, cause in sorted(failed.items()):
        rows[k] = {"proposal": k, "gates": {}, "sub": {}, "points": {}, "flags": [f"extraction failed: {cause}"],
                   "review_notes": [], "total": None, "status": "flagged", "rank": None,
                   "reason": f"Held for review: extraction failed: {cause}, needs a person to review."}
    return [rows[k] for k in ranked + flagged + sorted(failed) + ineligible]


def to_output(rows):
    # Only ranked bids get a score; a flagged bid's provisional total stays in its reason and the breakdown.
    return [{"proposal": r["proposal"], "rank": r["rank"], "status": r["status"],
             "score": round(r["total"], 1) if r["status"] == "ranked" else None, "reason": r["reason"]}
            for r in rows]


def print_breakdown(criteria, rows):
    keys = [c["key"] for c in criteria["weighted"]]
    print(f"criteria_version_id: {criteria['criteria_version_id']} | fact fields: {fact_schema_fingerprint(criteria)}")
    head = "".join(f"{c['key'][:10]:>11}" for c in criteria["weighted"])
    print(f"{'prop':<5}{'gates':<20}{head}{'total':>10}  status      rank")
    for r in rows:
        gates = " ".join(f"{g}:{v}" for g, v in r["gates"].items())
        pts = "".join(f"{r['points'][k]:>11.2f}" if k in r["points"] else f"{'-':>11}" for k in keys)
        total = f"{r['total']:>10.4f}" if r["total"] is not None else f"{'-':>10}"
        print(f"{r['proposal']:<5}{gates:<20}{pts}{total}  {r['status']:<11} {r['rank'] if r['rank'] else '-'}")
        print(f"     review notes: {'; '.join(r['review_notes']) or '-'}")
    print("weights: " + ", ".join(f"{c['key']}={c['weight']}" for c in criteria["weighted"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--criteria", default=HERE / "criteria" / "commercial_solar_v1.json")
    ap.add_argument("--facts", default=HERE / "facts" / "sample_facts.json")
    ap.add_argument("--out", default=HERE.parent / "ranking.json")
    ap.add_argument("--log", default=HERE / "outputs_local" / "triage_runs.jsonl", help="local run log (gitignored)")
    a = ap.parse_args()
    criteria = json.loads(Path(a.criteria).read_text(encoding="utf-8"))
    facts_bytes = Path(a.facts).read_bytes()
    facts = json.loads(facts_bytes)
    fingerprint = fact_schema_fingerprint(criteria)
    if facts.get("fact_schema_fingerprint") != fingerprint:
        sys.exit(f"Refusing to run: the facts were confirmed under fact fields {facts.get('fact_schema_fingerprint')!r}"
                 f" but the criteria now define {fingerprint!r}. Re-confirm the facts for the new fields first.")
    rows = triage(criteria, facts)
    print_breakdown(criteria, rows)
    Path(a.out).write_text(json.dumps(to_output(rows), indent=2) + "\n", encoding="utf-8", newline="\n")
    record = {"timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), "user": getpass.getuser(),
              "criteria_version_id": criteria["criteria_version_id"], "fact_schema_fingerprint": fingerprint,
              "facts_file": str(a.facts),
              "facts_sha256": hashlib.sha256(facts_bytes).hexdigest(),
              "bids": {r["proposal"]: {"status": r["status"], "total": r["total"], "rank": r["rank"],
                                       "provisional_position": r.get("provisional_position"), "reason": r["reason"]}
                       for r in rows}}
    Path(a.log).parent.mkdir(parents=True, exist_ok=True)
    with open(a.log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    print(f"wrote {a.out}; run logged to {a.log}")


if __name__ == "__main__":
    main()
