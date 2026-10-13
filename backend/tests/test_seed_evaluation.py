from app.evaluation.run_seed import check_result
from app.rag.answer_seed import CitedAnswer, CitedSource, FALLBACK


def test_supported_answer_needs_the_expected_source_and_content() -> None:
    answer = CitedAnswer("Bongio and Grohe. [1]", [CitedSource(1, "a" * 64, "About Us", "https://example.test/about", None)])

    assert check_result(answer, "https://example.test/about", ["Bongio", "Grohe"]) == []
    assert check_result(answer, "https://example.test/other", ["Bongio", "Scarabeo"]) == [
        "expected source is missing", "answer is missing 'Scarabeo'"
    ]


def test_unsupported_answer_must_have_no_citation() -> None:
    assert check_result(CitedAnswer(FALLBACK, []), None, []) == []
    assert check_result(CitedAnswer(FALLBACK, [CitedSource(1, "a" * 64, "About Us", "https://example.test/about", None)]), None, []) == [
        "expected an uncited abstention"
    ]
