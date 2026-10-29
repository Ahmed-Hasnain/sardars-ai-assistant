# Phase 7: catalog search with cited product descriptions

For staff and admins, a combined product query goes through the registered `search_products` read tool. PostgreSQL selects active, visible product rows by exact handle/SKU or bounded words from the title, vendor, category, mounting field and variant options. Price limits are applied to the same variant that is returned. Color requests require a matching variant option or an unambiguous product title; a multi-color product metafield alone cannot establish the displayed SKU's finish. At most three products are returned, with the lowest qualifying variant's SKU, price, recorded currency and specific catalog-listed options. More matches prompt narrowing.

After the database search, the application constructs each product URL from its Shopify handle and fetches only chunks for that exact URL from Qdrant. Every chunk must pass the existing PostgreSQL source registration, generation, checksum, visibility and readiness checks before use. The answer cites a short sentence from the matching product page and returns machine-readable product records and source IDs. A missing, removed, hidden, or unavailable description index leaves the exact database result intact and prevents a description-based recommendation. Raw page text and catalog fields remain lower-trust data; the product path does not run instructions found in them.

Precedence is explicit: PostgreSQL supplies SKU, price, currency and catalog-listed specifications at query time. Product pages supply descriptive evidence and its fetch timestamp. Page statements about price, stock, discounts or availability are excluded from the displayed description. The response does not claim current stock or Shopify/ERP synchronization. If a question names a currency, the tool requires that currency on the matching price row. The current database has no recorded currency, so a PKR filter returns an explanation rather than treating unlabelled numbers as rupees.

Example requests to authenticated `POST /api/v1/chat`:

```json
{"message":"Recommend black wall mounted basin mixers under 1000"}
```

The response has `route: "product_search"`, a `products` array with exact database values, `sources` for the descriptions actually shown, and `product_handles`. For a follow-up, send the returned handles back with the new question:

```json
{"message":"Which of these is cheaper?","product_handles":["first-handle","second-handle"]}
```

The app does not retain a conversation for this checkpoint. Handles supplied by a client are treated as untrusted and are checked against the authenticated user's visibility on every request. The comparison uses the displayed lowest qualifying variants; a product with multiple variants may have other prices. The general conversation-memory system remains Phase 9 work.

Verification on 2026-10-16: isolated tests cover finish and price belonging to the same variant, inclusive/exclusive numeric bounds, brand/category filtering, exact SKU and two-name comparisons, explicit, unknown and mixed currency, staff/admin visibility, archived products, unrelated/disabled/injected/missing descriptions, conflicting webpage price claims, follow-up comparison and API routing. The final authenticated local API check returned one black basin mixer with its exact black variant SKU, price and product-page citation; compared two SKUs on one product; answered a two-product follow-up; explained the unknown PKR currency; and returned 401 without a session. The temporary staff account and session were deleted. Local PostgreSQL contains 2,009 handles; all 967 ready indexed product-page registrations join exactly to a catalog handle. The full backend suite passed **404 tests**, with three skipped and one existing dependency warning. `alembic check` reported no schema drift.

Run the relevant checks from the repository root:

```bash
PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests/test_product_discovery.py backend/tests/test_chat.py backend/tests/test_product_tool.py backend/tests/test_tools.py
PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests
backend/.venv/bin/alembic check
```

Phase 7 exit (2026-10-17): the developer chose a numeric price limit without an assumed currency. The verified black wall-mounted basin mixer search and product-page citation satisfy this exit; explicit PKR filtering is deferred until the current prices have a verified, recorded currency. The full backend suite was rerun after starting local PostgreSQL: 404 passed, 3 skipped, 1 existing warning; `alembic check` found no drift.

Current limits: product names and filter terms are matched conservatively, so unfamiliar wording may ask for a clearer name or handle. The query returns at most three products and 32 variants per product and does not assert a single preferred product when its description is missing. Product-page fetches are bounded to 16 chunks per product. The existing Phase 5 full-corpus retrieval evaluation still has unresolved failures.
