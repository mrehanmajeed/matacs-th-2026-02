"""Optional live path: proposal .txt files -> AI fact extraction -> rule validation -> facts JSON.

Reads proposals from prototype/samples_local/*.txt (gitignored; you add them), the system prompt and
user template from PROMPTS.md, and the fields from the admin criteria config. Writes to
prototype/outputs_local/ (gitignored): facts.json (input for triage.py), audit.jsonl and a cache.
Needs ANTHROPIC_API_KEY (and optionally ANTHROPIC_MODEL) in .env at the repo root.
"""
import argparse
import datetime
import getpass
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

from injection_scan import scan

HERE = Path(__file__).parent
ROOT = HERE.parent
PROMPT_VERSION = "extract-v1"
DEFAULT_MODEL = "claude-haiku-5-5"  # verified on platform.claude.com models overview, 2026-10-27
MIN_WORDS = 40  # below this the text is probably a failed extraction or a bad scan
FOREIGN_CURRENCY = re.compile(r"\b(USD|US\$|EUR|GBP)\b|[€£]")
VALUE_TYPES = {"boolean": {"type": "boolean"}, "number": {"type": "number"}, "integer": {"type": "integer"},
               "string": {"type": "string"},
               "licence_holder": {"type": "string", "enum": ["bidder", "subcontractor", "other"]}}


def load_prompts():
    """System prompt and user template, taken verbatim from the marked blocks in PROMPTS.md."""
    md = (ROOT / "PROMPTS.md").read_text(encoding="utf-8")
    blocks = dict(re.findall(r"<!-- prompt:(\w+) -->\s*```\w*\n(.*?)\n```", md, re.DOTALL))
    return blocks["system"], blocks["user"]


def build_schema(criteria):
    """JSON schema for the model's output, generated from the admin's field definitions."""
    fields = criteria["fields"]
    used = sorted({f["type"] for f in fields.values()})
    defs = {f"fact_{t}": {
        "type": "object", "additionalProperties": False, "required": ["value", "status", "evidence", "note"],
        "properties": {"value": {"anyOf": [VALUE_TYPES[t], {"type": "null"}]},
                       "status": {"type": "string", "enum": ["stated", "not_stated", "unclear"]},
                       "evidence": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                       "note": {"anyOf": [{"type": "string"}, {"type": "null"}]}}} for t in used}
    defs["passage"] = {"type": "object", "additionalProperties": False, "required": ["quote", "reason"],
                       "properties": {"quote": {"type": "string"}, "reason": {"type": "string"}}}
    return {"type": "object", "additionalProperties": False,
            "required": ["proposal_id", "facts", "suspicious_instructions", "unsupported_claims"],
            "properties": {
                "proposal_id": {"type": "string"},
                "facts": {"type": "object", "additionalProperties": False, "required": list(fields),
                          "properties": {n: {"$ref": f"#/$defs/fact_{f['type']}"} for n, f in fields.items()}},
                "suspicious_instructions": {"type": "array", "items": {"$ref": "#/$defs/passage"}},
                "unsupported_claims": {"type": "array", "items": {"$ref": "#/$defs/passage"}}},
            "$defs": defs}


def render_user(template, criteria, proposal_id, text):
    users = {}
    for g in criteria["mandatory"]:
        for r in g["require"]:
            users.setdefault(r["field"], []).append(g["key"])
    for c in criteria["weighted"]:
        for f in c["fields"]:
            users.setdefault(f, []).append(c["key"])
    fields = "\n".join(f"- {n} ({f['type']}): {f['desc']}. Used by: {', '.join(users.get(n, ['reviewer context']))}"
                       for n, f in criteria["fields"].items())
    constraints = "\n".join(f"- {k}: {v}" for k, v in criteria["constraints"].items())
    for key, val in {"CATEGORY_NAME": criteria["category"], "PROJECT_CONSTRAINTS": constraints,
                     "CRITERIA_FIELDS": fields, "PROPOSAL_ID": proposal_id, "PROPOSAL_TEXT": text}.items():
        template = template.replace("{{" + key + "}}", val)
    return template


def norm(s):
    return " ".join(unicodedata.normalize("NFKC", s).split())


def validate(data, source, criteria):
    """Rule checks after the AI: verbatim evidence, plausible ranges, CAD. Failures mark the fact unverified."""
    src = norm(source)
    for name, f in data["facts"].items():
        if f["value"] is None:
            continue
        problems = []
        if not f["evidence"] or norm(f["evidence"]) not in src:
            problems.append("evidence quote not found verbatim in source")
        lo, hi = criteria["fields"][name].get("range", (None, None))
        if lo is not None and not isinstance(f["value"], bool) and not lo <= f["value"] <= hi:
            problems.append(f"value outside plausible range {lo}-{hi}")
        if name.endswith("_cad") and f["evidence"] and FOREIGN_CURRENCY.search(f["evidence"]):
            problems.append("currency not confirmed as CAD")
        if problems:
            f["verified"] = False
            f["note"] = "; ".join(filter(None, [f["note"], *problems]))
    return data


def load_env():
    env = dict(os.environ)
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--criteria", default=HERE / "criteria" / "commercial_solar_v1.json")
    ap.add_argument("--samples", default=HERE / "samples_local")
    ap.add_argument("--out", default=HERE / "outputs_local")
    a = ap.parse_args()
    env = load_env()
    key = env.get("ANTHROPIC_API_KEY", "")
    if not key or key == "your-key-here":
        sys.exit("No ANTHROPIC_API_KEY found. Copy .env.example to .env and add a key; triage.py needs no key.")
    files = sorted(Path(a.samples).glob("*.txt"))
    if not files:
        sys.exit(f"No proposal .txt files in {a.samples}. Add one file per proposal, named by letter (A.txt).")

    import anthropic  # only the live path needs these
    import jsonschema

    model = env.get("ANTHROPIC_MODEL") or DEFAULT_MODEL
    # Temperature 0 only where the pinned model supports it (set ANTHROPIC_TEMPERATURE=0); otherwise model default.
    sampling = {"temperature": float(env["ANTHROPIC_TEMPERATURE"])} if env.get("ANTHROPIC_TEMPERATURE") else {}
    criteria = json.loads(Path(a.criteria).read_text(encoding="utf-8"))
    system, template = load_prompts()
    schema = build_schema(criteria)
    prompt_sha = hashlib.sha256((system + template + json.dumps(schema, sort_keys=True)).encode()).hexdigest()
    out = Path(a.out)
    (out / "cache").mkdir(parents=True, exist_ok=True)
    client = anthropic.Anthropic(api_key=key)
    proposals, seen = {}, {}

    for path in files:
        raw_bytes = path.read_bytes()
        sha = hashlib.sha256(raw_bytes).hexdigest()
        if sha in seen:
            print(f"{path.name}: duplicate of {seen[sha]}, skipped")
            continue
        seen[sha] = path.name
        pid, text = path.stem, raw_bytes.decode("utf-8")
        intake = [f"only {len(text.split())} words of text; check the file or OCR"] if len(text.split()) < MIN_WORDS else []
        hits = scan(text)

        # Same file + same prompt + same model -> reuse the stored output instead of calling the AI again.
        cache = out / "cache" / f"{sha[:16]}_{prompt_sha[:12]}_{model}.json"
        hit = cache.exists()
        if hit:
            raw = cache.read_text(encoding="utf-8")
        else:
            try:
                resp = client.messages.create(
                    model=model, max_tokens=16000, system=system,
                    messages=[{"role": "user", "content": render_user(template, criteria, pid, text)}],
                    output_config={"format": {"type": "json_schema", "schema": schema}}, **sampling)
            except anthropic.APIError as e:
                print(f"{path.name}: API error, skipped: {e}")
                continue
            if resp.stop_reason != "end_turn":
                print(f"{path.name}: stopped with {resp.stop_reason}, skipped")
                continue
            raw = next(b.text for b in resp.content if b.type == "text")
            cache.write_text(raw, encoding="utf-8")
        data = json.loads(raw)
        jsonschema.validate(data, schema)
        data = validate(data, text, criteria)

        proposals[pid] = {
            "intake_flags": intake,
            "suspicious_instructions": [s["reason"] for s in data["suspicious_instructions"]]
                                       + [f"rule scan matched \"{h['match']}\"" for h in hits],
            "unsupported_claims": [c["quote"] for c in data["unsupported_claims"]],
            "facts": data["facts"]}
        record = {"timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), "user": getpass.getuser(),
                  "file": path.name, "file_sha256": sha, "criteria_version_id": criteria["criteria_version_id"],
                  "model": model, "prompt_version": PROMPT_VERSION, "prompt_sha256": prompt_sha,
                  "cache_hit": hit, "raw_output": raw, "scanner_hits": hits, "validated": proposals[pid]}
        with open(out / "audit.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        print(f"{path.name}: extracted ({len(hits)} scanner hits)")

    facts = {"criteria_version_id": criteria["criteria_version_id"], "proposals": proposals}
    (out / "facts.json").write_text(json.dumps(facts, indent=2), encoding="utf-8")
    print(f"wrote {out / 'facts.json'}; review it (checkpoint 1), then: "
          f"python prototype/triage.py --facts {out / 'facts.json'} --out {out / 'ranking.json'}")


if __name__ == "__main__":
    main()
