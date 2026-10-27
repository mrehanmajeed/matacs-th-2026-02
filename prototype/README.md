# Prototype

Small, readable sketch of the design. Python 3.10+. `triage.py` needs no installs and no API key.

| File | What it does |
|---|---|
| `criteria/commercial_solar_v1.json` | Admin config for this category, one immutable version: constraints, fact fields, mandatory gates, weighted criteria (weight, method, fields, reason phrases), tie-breaks. |
| `facts/sample_facts.json` | Reviewer-confirmed facts for proposals A–E (after checkpoint 1), using the extraction fields. Evidence quotes are deliberately left out because the brief may not be copied; notes are short paraphrases, plus the reviewer's `review_notes`. |
| `triage.py` | Rules only: gates → scores → status → tie-breaks → template reasons. Prints the breakdown and review notes, writes `ranking.json`, appends a run record to `outputs_local/triage_runs.jsonl` (gitignored), and refuses facts confirmed under different fact fields (a fingerprint of the field definitions), while weight or threshold edits rescore the stored facts. |
| `extract.py` | Optional live AI step: `samples_local/*.txt` → extraction prompt from `PROMPTS.md` → schema check → quote, range and currency checks → `outputs_local/facts.json` + `audit.jsonl`. A failed extraction is logged and passed on as a flagged bid, never dropped. |
| `injection_scan.py` | Rule-based scan for text aimed at automated reviewers; runs on the raw text, separately from the AI. |
| `flow.dot` | Graphviz source for `diagram/process-flow.png` (`dot -Tpng -Gdpi=110 prototype/flow.dot -o diagram/process-flow.png`). |
| `test_triage.py` | 12 tests: reproduces `ranking.json` (scores, statuses, reason wording and length); provisional positions C = 3rd, D = 4th; B fails the licence gate; a missing gate fact flags instead of rejecting; weights must sum to 100; a weight change rescores predictably; scanner catches an injected instruction; `PROMPTS.md` matches the code; a failed extraction becomes a flagged bid; a weight-only criteria edit rescores from stored facts while a fact-field change (fact-schema fingerprint) is refused; an unverified or unclear fact is flagged with its real cause, not "not stated"; prices in USD / US$ / EUR / GBP / € / £ are caught as non-CAD. |

```
python prototype/triage.py                    # writes ranking.json
pip install -r prototype/requirements.txt && pytest
python prototype/extract.py                   # optional; needs .env with ANTHROPIC_API_KEY
python prototype/triage.py --facts prototype/outputs_local/facts.json --out prototype/outputs_local/ranking.json
```
