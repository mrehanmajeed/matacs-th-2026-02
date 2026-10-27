# Prototype

Small, readable sketch of the design. Python 3.10+. `triage.py` needs no installs and no API key.

| File | What it does |
|---|---|
| `criteria/commercial_solar_v1.json` | Admin config for this category, one immutable version: constraints, fact fields, mandatory gates, weighted criteria (weight, method, fields, reason phrases), tie-breaks. |
| `facts/sample_facts.json` | Human-confirmed facts for proposals A–E in the extraction schema (paraphrased notes, no source text). |
| `triage.py` | Rules only: gates → scores → status → tie-breaks → template reasons. Prints the breakdown and writes `ranking.json`. |
| `extract.py` | Optional live AI step: `samples_local/*.txt` → extraction prompt from `PROMPTS.md` → schema check → verbatim-evidence and range checks → `outputs_local/facts.json` + `audit.jsonl`. |
| `injection_scan.py` | Rule-based scan for text aimed at automated reviewers; runs on the raw text, separately from the AI. |
| `flow.dot` | Graphviz source for `diagram/process-flow.png` (`dot -Tpng -Gdpi=110 prototype/flow.dot -o diagram/process-flow.png`). |
| `test_triage.py` | Tests: reproduces `ranking.json`, B fails the licence gate, weights must sum to 100, scanner catches an injected instruction, weight change rescoring, `PROMPTS.md` in sync with code. |

```
python prototype/triage.py                    # writes ranking.json
pip install -r prototype/requirements.txt && pytest
python prototype/extract.py                   # optional; needs .env with ANTHROPIC_API_KEY
python prototype/triage.py --facts prototype/outputs_local/facts.json --out prototype/outputs_local/ranking.json
```
