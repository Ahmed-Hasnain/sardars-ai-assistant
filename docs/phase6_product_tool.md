# Phase 6 product-price and SKU tool

On 2026-10-16 the developer designated the prices and SKUs currently stored in `public.products` as valid values for the internal assistant. On 2026-10-18 the developer populated and similarly authorized `variant_inventory_qty` for the internal proof of concept. The application reads PostgreSQL for each product question; it does not cache those values in Qdrant or the model. Historical `price_origin` and `sku_origin` flags still record how values were created. They do not reject the developer's current data-authority decision.

`/api/v1/chat` routes staff/admin questions about an exact SKU's price or stock, variants, cost, or “how much” to the allowlisted `get_product_details` tool. This application decision makes the read dependable even when a small local model does not emit a tool call. The existing Ollama tool-call interface remains available for other uses. General questions retain local-model chat; descriptive company questions retain authorized RAG.

The tool accepts exactly one of:

```json
{"name":"get_product_details","arguments":{"identifier":"TEST-1"}}
```

```json
{"name":"get_product_details","arguments":{"question":"What is the price and SKU for Sculptural Flush Plate OLI Voronoi?"}}
```

An exact SKU returns one matching row. A handle or clearly matched product name returns its variants, up to 32. Image-only CSV continuation rows have current database SKUs/prices because the developer filled every row; an exact SKU on such a row is returned with `row_kind: image_only` and an explicit note that it is not a product variant. Several matching product names produce up to five handle/title choices and ask staff to narrow the question. Missing or hidden products return the same safe response. Duplicate SKUs, invalid input, large results, database errors and timeouts fail safely.

The tool returns only title, vendor, handle, SKU, variant options, price, variant stock quantity, row kind and source/timing metadata. It never returns cost, raw HTML, other inventory fields, metafields or model-supplied SQL. Results identify `developer_authorized_products_table`, `observed_at`, `database_values_verified: true`, and `external_sync_verified: false`. The chat response sets `company_data_verified: true` for a successful PostgreSQL product read. `current_stock_verified: true` means all displayed variants have a recorded quantity at query time, including zero; missing or image-only quantities remain unverified. Currency, stock reservations and external synchronization remain unknown. The original CSV hash identifies import provenance, not the later manual edits; import time is not a price or stock update time.

The previously applied migration `d74ab9e6c501` classifies 3,090 original variants and 1,893 image-only rows. The developer's price/SKU edits remain untouched. The old import command still refuses to overwrite edited rows with the original CSV.

Verification commands:

```bash
PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests/test_product_tool.py backend/tests/test_tools.py backend/tests/test_chat.py
PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests
backend/.venv/bin/alembic check
```

An authenticated local API check covered a real variant SKU, a natural product-name question, an image-row SKU and a missing SKU. The first three returned HTTP 200 with a source and verified database values; the missing SKU returned no source, and a request without a bearer token returned 401. The temporary staff account/session were removed. Catalog checks found all 4,983 SKUs populated, no case-insensitive duplicates or whitespace SKUs, no fields beyond response limits, and a maximum of 24 variants per handle. A full registered-tool handle audit and final full-suite results are recorded in `IMPLEMENTATION_STATUS.md`.

This authority is scoped to the current internal PostgreSQL table. There is no ERP/Shopify synchronization, verified currency or external stock feed. Product-name matching is conservative: ambiguous or unsupported wording asks for a more specific name, handle or SKU. Internet search is not part of this tool.
