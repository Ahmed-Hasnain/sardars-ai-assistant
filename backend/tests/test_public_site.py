from app.ingestion.public_site import extract_document, source_type


def test_only_public_descriptive_routes_are_accepted() -> None:
    assert source_type("https://sardarandco.com/pages/about-us") == "pages"
    assert source_type("https://sardarandco.com/blogs/news/example") == "articles"
    assert source_type("https://sardarandco.com/products/example") == "products"
    assert source_type("https://sardarandco.com/pages/request-for-quote") is None
    assert source_type("https://sardarandco.com/pages/quotes-history") is None
    assert source_type("https://sardarandco.com/products/example?variant=123") is None
    assert source_type("https://other.example/products/example") is None
    assert source_type("http://sardarandco.com/products/example") is None


def test_product_extraction_excludes_offer_and_page_chrome() -> None:
    html = b"""
    <html><title>Example | Sardars</title><main>
      <h1>Example Basin</h1><span>Rs. 45,000</span><span>Available now</span>
      <div class="product-description rte not-in-quickbuy">
        <p>Wall-mounted ceramic basin with a glossy white finish.</p>
      </div>
    </main><footer>Private footer details</footer>
    <script type="application/ld+json">
      {"@type":"Product","description":"Ceramic basin for bathrooms.",
       "offers":{"price":"45000","availability":"InStock"}}
    </script></html>
    """
    result = extract_document("https://sardarandco.com/products/example", html)

    assert result is not None
    assert result["visibility"] == "public"
    assert result["review_status"] == "pending"
    assert "Wall-mounted ceramic basin" in result["text"]
    assert "Ceramic basin for bathrooms" in result["text"]
    assert "45,000" not in result["text"]
    assert "Available now" not in result["text"]
    assert "Private footer" not in result["text"]


def test_article_extraction_uses_article_body_only() -> None:
    html = b"""
    <main><h1>Bathroom fitting tips</h1>
      <div class="rte cf spaced-row"><p>Choose durable fittings and clean them
      regularly to maintain their finish over time.</p></div>
      <aside>Sign up for a newsletter</aside>
    </main>
    """
    result = extract_document("https://sardarandco.com/blogs/news/tips", html)

    assert result is not None
    assert "Choose durable fittings" in result["text"]
    assert "newsletter" not in result["text"]


def test_page_extraction_prefers_content_sections_over_page_chrome() -> None:
    html = b"""
    <main><h1>About us</h1><div class="rte">
      Sardars provides luxury sanitary products and bathroom fittings.
    </div><div class="staff-directory">Personal staff information</div></main>
    """
    result = extract_document("https://sardarandco.com/pages/about-us", html)

    assert result is not None
    assert "luxury sanitary products" in result["text"]
    assert "Personal staff information" not in result["text"]
