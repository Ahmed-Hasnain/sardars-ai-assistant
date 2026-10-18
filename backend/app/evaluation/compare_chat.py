"""Compare two saved chat evaluations without calling services or exposing answers."""

import argparse
import json
from pathlib import Path


def load_report(path: Path) -> dict:
    with path.open("rb") as stream:
        raw = stream.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("Evaluation report exceeds the size limit")
    try:
        report = json.loads(raw)
        definitions = report["case_definitions"]
        rows = report["cases"]
        if (not isinstance(definitions, list) or not isinstance(rows, list)
            or not definitions or len(definitions) != len(rows)
            or len({case["id"] for case in definitions}) != len(definitions)
            or len({row["id"] for row in rows}) != len(rows)):
            raise ValueError
        if {case["id"] for case in definitions} != {row["id"] for row in rows}:
            raise ValueError
        if not all(isinstance(row["passed"], bool) for row in rows):
            raise ValueError
        if not isinstance(report["metadata"]["protocol_version"], int):
            raise ValueError
        return report
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise ValueError("Invalid chat evaluation report") from exc


def compare(before: dict, after: dict) -> dict:
    old_meta, new_meta = before["metadata"], after["metadata"]
    old_cases = {case["id"]: case for case in before["case_definitions"]}
    new_cases = {case["id"]: case for case in after["case_definitions"]}
    old_rows = {row["id"]: row for row in before["cases"]}
    new_rows = {row["id"]: row for row in after["cases"]}
    common = old_cases.keys() & new_cases.keys()
    same_cases = sorted(identifier for identifier in common if old_cases[identifier] == new_cases[identifier])
    changed = sorted(identifier for identifier in common if old_cases[identifier] != new_cases[identifier])
    checks = {
        "same_protocol": old_meta["protocol_version"] == new_meta["protocol_version"],
        "same_evaluator": old_meta.get("evaluator_sha256") == new_meta.get("evaluator_sha256"),
        "same_case_definitions": not changed and old_cases.keys() == new_cases.keys(),
        "stable_data_in_each_run": all(report["summary"].get("data_stable_during_run") is True
                                       for report in (before, after)),
        "same_data_fingerprint": bool(old_meta.get("data_fingerprint_after")) and
                                 old_meta.get("data_fingerprint_after") == new_meta.get("data_fingerprint_before"),
        "same_model_and_collection": all(old_meta.get(key) == new_meta.get(key)
                                         for key in ("chat_model", "embedding_model", "collection")),
    }
    return {
        "controlled_comparison": all(value for name, value in checks.items()
                                     if name != "same_model_and_collection"),
        "comparability_checks": checks,
        "added_case_ids": sorted(new_cases.keys() - old_cases.keys()),
        "removed_case_ids": sorted(old_cases.keys() - new_cases.keys()),
        "changed_case_ids": changed,
        "unchanged_case_count": len(same_cases),
        "unchanged_case_passes_before": sum(old_rows[identifier]["passed"] for identifier in same_cases),
        "unchanged_case_passes_after": sum(new_rows[identifier]["passed"] for identifier in same_cases),
        "improved_case_ids": [identifier for identifier in same_cases
                              if not old_rows[identifier]["passed"] and new_rows[identifier]["passed"]],
        "regressed_case_ids": [identifier for identifier in same_cases
                               if old_rows[identifier]["passed"] and not new_rows[identifier]["passed"]],
        "note": ("Outcome changes may be attributed to the tested application or model change only after reviewing environment and run variance."
                 if all(value for name, value in checks.items() if name != "same_model_and_collection") else
                 "Runs differ in cases, evaluator, data or model; outcome counts are descriptive, not a controlled quality change."),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(compare(load_report(args.before), load_report(args.after)), indent=2))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
