"""Run the audited M2 fixture scope through the CLI and optional Python CLVM."""
import json
from verify_collections import ROOT, main


def fixtures():
    spec = ROOT / "docs/spec"
    original = json.loads((spec / "source-cases.json").read_text(encoding="utf-8"))["cases"]
    scope = json.loads((spec / "m2-conformance-scope.json").read_text(encoding="utf-8"))["m0"]
    assert len(scope) == len(original) == 29
    assert len({entry["id"] for entry in scope}) == len(scope)
    assert {entry["id"] for entry in scope} == {case["id"] for case in original}
    active = []
    deferred = []
    for entry in scope:
        case = next(case for case in original if case["id"] == entry["id"])
        if entry["status"] == "deferred":
            assert entry["reason"]
            deferred.append(entry["id"])
            continue
        assert entry["status"] == "active"
        item = {"id": "m0-" + case["id"], "source": case["source"], "check": "accept" if case["accept"] else "reject"}
        if case["accept"]:
            item["execution"] = {"conditions": case["expected_conditions"]}
        else:
            item["diagnostic"] = case["diagnostic"]
        active.append(item)
    assert len(active) == 24 and len(deferred) == 5
    for filename, prefix, count in [("m2-source-cases.json", "m2-", 14), ("m2-collections-cases.json", "collections-", 31)]:
        cases = json.loads((spec / filename).read_text(encoding="utf-8"))["cases"]
        selected = [case for case in cases if "superseded_by" not in case]
        assert len(selected) == count
        active.extend({**case, "id": prefix + case["id"]} for case in selected)
    assert len(active) == len({case["id"] for case in active}) == 69
    print("Deferred M0 cases (not counted as passing): " + ", ".join(deferred))
    return active


if __name__ == "__main__":
    main(fixtures, "typed-core")
