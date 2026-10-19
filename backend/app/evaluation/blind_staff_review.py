"""Make a local, model-blinded review sheet from two staff-question reports.

Both output files contain internal conversation content; keep them in the
Git-ignored evaluation directory and share only with an authorized reviewer.
"""

import argparse
import json
from pathlib import Path
from secrets import randbelow


def load_report(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ValueError(f"Invalid staff-question report: {path}")
    return data


def make_packet(baseline_path: Path, candidate_path: Path, packet: Path, key_path: Path) -> None:
    if packet.exists() or key_path.exists():
        raise ValueError("Output already exists; choose new packet and key paths")
    baseline = load_report(baseline_path)
    candidate = load_report(candidate_path)
    before = baseline["metadata"]
    after = candidate["metadata"]
    if (before["question_sha256"] != after["question_sha256"]
        or before["data_fingerprint_before"] != before["data_fingerprint_after"]
        or after["data_fingerprint_before"] != after["data_fingerprint_after"]
        or before["data_fingerprint_before"] != after["data_fingerprint_before"]
        or before["chat_model"] == after["chat_model"]
        or len(baseline["cases"]) != len(candidate["cases"])):
        raise ValueError("Reports do not use the same stable questions and database facts")

    lines = [
        "# E2 blinded internal-question review",
        "",
        "Compare each pair without checking the model key. For each answer, score support "
        "from the shown source (1–5), usefulness (1–5), and mark any unsupported "
        "company claim. Choose A, B, or tie. An honest abstention can be preferable "
        "when the available evidence is insufficient.",
        "",
        "These are standalone replays of prior internal questions; saved conversation "
        "history was deliberately excluded. The sheet contains internal chat content.",
        "",
    ]
    key = {"question_sha256": before["question_sha256"], "model_labels": {}}
    for first, second in zip(baseline["cases"], candidate["cases"], strict=True):
        if first["message_id"] != second["message_id"] or first["question"] != second["question"]:
            raise ValueError("Question order or content differs between reports")
        baseline_first = randbelow(2) == 0
        labeled = {"A": first if baseline_first else second,
                   "B": second if baseline_first else first}
        key["model_labels"][str(first["message_id"])] = {
            "A": before["chat_model"] if baseline_first else after["chat_model"],
            "B": after["chat_model"] if baseline_first else before["chat_model"],
        }
        lines.extend([f"## Question {first['message_id']}", "", first["question"], ""])
        for label, row in labeled.items():
            lines.extend([f"### Answer {label}", "", row["answer"], ""])
            if row["sources"]:
                lines.append("Cited sources: " + ", ".join(
                    source["url"] for source in row["sources"]
                ))
            else:
                lines.append("Cited sources: none")
            lines.append("")
        lines.extend(["Scores: A support __/5, usefulness __/5, unsupported claim? __; "
                      "B support __/5, usefulness __/5, unsupported claim? __; "
                      "preferred: A / B / tie.", ""])

    packet.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    with packet.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    with key_path.open("x", encoding="utf-8") as stream:
        json.dump(key, stream, indent=2)
        stream.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    args = parser.parse_args()
    try:
        make_packet(args.baseline, args.candidate, args.packet, args.key)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
