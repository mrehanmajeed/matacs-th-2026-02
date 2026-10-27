import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from triage import HERE, gate, to_output, triage

ROOT = HERE.parent
CRITERIA = json.loads((HERE / "criteria" / "commercial_solar_v1.json").read_text(encoding="utf-8"))
FACTS = json.loads((HERE / "facts" / "sample_facts.json").read_text(encoding="utf-8"))

# Expected unrounded totals, hand-computed from the formulas in README.md.
EXPECTED = {"A": (98.0147, 1, "ranked"), "E": (84.8035, 2, "ranked"),
            "C": (77.0608, None, "flagged"), "D": (69.8214, None, "flagged"), "B": (None, None, "ineligible")}


def test_reproduces_ranking_json_exactly(tmp_path):
    out = tmp_path / "ranking.json"
    subprocess.run([sys.executable, str(HERE / "triage.py"), "--out", str(out)], check=True, capture_output=True)
    assert out.read_bytes() == (ROOT / "ranking.json").read_bytes()
    rows = {r["proposal"]: r for r in triage(CRITERIA, FACTS)}
    for k, (total, rank, status) in EXPECTED.items():
        assert (rows[k]["rank"], rows[k]["status"]) == (rank, status)
        if total is not None:
            assert rows[k]["total"] == pytest.approx(total, abs=0.05)
    assert [r["proposal"] for r in to_output(triage(CRITERIA, FACTS))] == ["A", "E", "C", "D", "B"]


def test_b_fails_licence_gate():
    b = FACTS["proposals"]["B"]
    assert gate(b, CRITERIA["mandatory"][0], CRITERIA["constraints"]) == "fail"
    assert gate(b, CRITERIA["mandatory"][1], CRITERIA["constraints"]) == "pass"


def test_missing_mandatory_fact_flags_instead_of_rejecting():
    facts = copy.deepcopy(FACTS)
    facts["proposals"]["A"]["facts"]["wsib_clearance"] = {"value": None, "status": "not_stated"}
    a = next(r for r in triage(CRITERIA, facts) if r["proposal"] == "A")
    assert a["status"] == "flagged" and a["gates"]["M2"] == "unconfirmed"


def test_weights_must_sum_to_100():
    bad = copy.deepcopy(CRITERIA)
    bad["weighted"][0]["weight"] = 31
    with pytest.raises(ValueError, match="sum to 100"):
        triage(bad, FACTS)


def test_weight_change_rescores_deterministically():
    v2 = copy.deepcopy(CRITERIA)
    v2["criteria_version_id"] = "commercial_solar_v2"
    weights = {c["key"]: c for c in v2["weighted"]}
    weights["price"]["weight"], weights["timeline"]["weight"] = 20, 20  # move 5 points from price to timeline
    old = {r["proposal"]: r for r in triage(CRITERIA, FACTS)}
    new = {r["proposal"]: r for r in triage(v2, FACTS)}
    assert new == {r["proposal"]: r for r in triage(v2, FACTS)}  # same input, same output
    for k in "ACDE":
        s = old[k]["sub"]
        assert new[k]["total"] == pytest.approx(old[k]["total"] - 5 * s["price"] + 5 * s["timeline"])
    assert new["D"]["total"] < old["D"]["total"]  # D has no timeline, so moving weight there costs it
