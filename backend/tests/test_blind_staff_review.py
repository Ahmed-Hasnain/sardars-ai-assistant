import json

import pytest

from app.evaluation.blind_staff_review import make_packet


def _report(model: str, answer: str, fingerprint: str = "same") -> dict:
    return {
        "metadata": {
            "chat_model": model,
            "question_sha256": "question-hash",
            "data_fingerprint_before": fingerprint,
            "data_fingerprint_after": fingerprint,
        },
        "cases": [{
            "message_id": 17, "question": "What does Sardars offer?",
            "answer": answer, "sources": [],
        }],
    }


def test_blind_packet_hides_model_names_and_keeps_key_separate(tmp_path):
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    first.write_text(json.dumps(_report("small-model", "Answer one")))
    second.write_text(json.dumps(_report("large-model", "Answer two")))
    packet, key_path = tmp_path / "packet.md", tmp_path / "key.json"

    make_packet(first, second, packet, key_path)

    sheet = packet.read_text()
    labels = json.loads(key_path.read_text())["model_labels"]["17"]
    assert "small-model" not in sheet and "large-model" not in sheet
    assert "Answer one" in sheet and "Answer two" in sheet
    assert set(labels.values()) == {"small-model", "large-model"}


def test_blind_packet_rejects_different_database_facts(tmp_path):
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    first.write_text(json.dumps(_report("small-model", "Answer one")))
    second.write_text(json.dumps(_report("large-model", "Answer two", "changed")))

    with pytest.raises(ValueError, match="same stable questions and database facts"):
        make_packet(first, second, tmp_path / "packet.md", tmp_path / "key.json")
    assert not (tmp_path / "packet.md").exists()
