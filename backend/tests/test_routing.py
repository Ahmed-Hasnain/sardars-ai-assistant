from app.rag.routing import route_question


def test_clear_educational_questions_use_general_model() -> None:
    assert route_question("What is a thermostatic mixer?") == "general"
    assert route_question("How does a shower mixer work?") == "general"
    assert route_question("Explain what a database is in one sentence.") == "general"
    assert route_question("Hello") == "general"


def test_company_and_ambiguous_questions_use_grounded_sources() -> None:
    assert route_question("Which brands does Sardars mention?") == "company"
    assert route_question("What is your return policy?") == "company"
    assert route_question("What is the current price of the Shower Niche?") == "company"
    assert route_question("Which bathroom fittings do you sell?") == "company"
    assert route_question("Tell me about Grohe") == "company"
