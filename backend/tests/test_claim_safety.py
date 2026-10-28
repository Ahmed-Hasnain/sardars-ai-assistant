from app.rag.claim_safety import unsafe_descriptive_claim


def test_qualified_faq_language_does_not_assert_a_live_value():
    assert not unsafe_descriptive_claim("Company materials address homeowners and architects.")
    assert not unsafe_descriptive_claim("A complete design requires checking availability.")
    assert not unsafe_descriptive_claim("The published slogan does not by itself prove stock position.")
    assert unsafe_descriptive_claim("The showroom address is at Example Street.")
    assert unsafe_descriptive_claim("Address: Example Street.")
    assert unsafe_descriptive_claim("Stock is in stock, but not verified: 12 units.")
    assert unsafe_descriptive_claim("The product is available now.")
    assert unsafe_descriptive_claim("We guarantee delivery, but check the contract.")
    assert not unsafe_descriptive_claim("The limited review sample includes price criticism.")
    assert unsafe_descriptive_claim("The review includes price criticism and the current price is 100.")
    assert not unsafe_descriptive_claim(
        "Eligibility depends on the current written policy and your order terms. "
        "This FAQ does not establish a general return window or unconditional acceptance."
    )
    assert unsafe_descriptive_claim("A 30-day return window is guaranteed, but it depends on the current written policy.")
