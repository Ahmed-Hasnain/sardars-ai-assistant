# Phase 6 — source discovery and read-only access

Started: 2026-10-15 at the developer's request. Phase 5 ingestion/replay has completed; its full-corpus retrieval/answer regressions remain unresolved (expanded 28/40, seed 4/7).

## Confirmed state

Updated scope, 2026-10-16: the developer has a Sardars Shopify product CSV and chose a PostgreSQL-backed lookup proof of concept without ERP access. The authorized schema checkpoint created `public.products` with its 88 named headers and eight provenance/identity fields. The developer then supplied `products_export_1.csv` for read-only structure verification: all 88 headers match, with 4,983 records and 2,009 handles, but only 15 nonempty SKUs. See `phase6_shopify_csv_validation.md`. The developer subsequently authorized importing the file: all 4,983 rows / 2,009 handles are committed and verified, and replay skips all 4,983. Building the product tool and model integration are the next checkpoints to agree with the developer. See [the Shopify snapshot plan](phase6_shopify_products.md) for schema, provenance, limitations and verification. ERP discovery below remains relevant to a later live integration, rather than blocking this snapshot proof of concept.

Sardars has an ERP and a website. The developer currently has no ERP access and will ask the company for it. ERP identity, supported interfaces and ERP-to-website synchronization are unknown. The existing website crawl supplies dated descriptive evidence; it does not establish current prices or inventory. The application's PostgreSQL tables hold authentication, permissions, sources, ingestion jobs and the imported Shopify file snapshot. The snapshot is not a live authoritative ERP catalogue.

Internal proof-of-concept update (2026-10-18): the developer populated `public.products.variant_inventory_qty` and designated those stored quantities as valid alongside the previously authorized prices/SKUs. The assistant now reports the role-visible PostgreSQL variant quantity with a query-time observation timestamp, including zero. This authorization applies to the local database snapshot, not to ERP synchronization, reservations, inventory location, or guaranteed sellable availability. The original ERP questions below remain open.

The current `ChatModel.chat()` interface returns text only. The first application tool checkpoint now implements an explicit read-tool registry and authenticated single execution for `get_source_status`, backed by existing PostgreSQL source records. Model tool requests, an execution loop and ERP read tools are not implemented. ERP source discovery remains open.

## Verified first checkpoint: source-status read tool

`POST /api/v1/tools/execute` accepts one explicit tool name and strict arguments. `get_source_status` takes a sixty-four-character lowercase hexadecimal `source_id`; source IDs are available from the authenticated existing `/api/v1/ingestion/sources` listing or answer citations. Staff can see public/staff metadata; admins can also see admin metadata. The same visibility policy applies to source status, including nonready records; this endpoint returns no document body or uploaded file. Hidden and nonexistent sources both return `source_not_found`.

The result reports source URL/title, visibility, active/index state, registry readiness, original fetch/index/sync times and the observation time. Its authority is `application_source_registry`, with `company_facts_verified: false`. Registry readiness reports metadata; this tool does not scan Qdrant, prove answerability or certify source truth/freshness. Missing dates remain null. Observing a registry row does not refresh its content timestamp. Titles/URLs are source data and must remain untrusted if a later model consumes this result.

The API authenticates before reading a bounded body (8 KiB, thirty-second read limit). Arguments have a 4 KiB limit and results an 8 KiB limit. Each request executes at most one allowlisted lookup, without retries or a model. PostgreSQL queries have transaction-local two-second statement and one-second lock limits, reset on session close/rollback. Authentication uses the existing database connection behavior; there is no newly claimed end-to-end network deadline. Execution logs contain the registered tool name, outcome and latency, excluding arguments, source content, credentials and raw errors. Lookup/validation/timeout errors use safe structured results.

Verification: the full backend suite passed 339 tests with two opt-in integration tests skipped; the focused tools/ingestion API/chat run passed 71 tests. The suite retains the existing Starlette/httpx deprecation warning. A real local PostgreSQL/API smoke check verified staff/admin success, preserved fetch timestamps, rejected invalid arguments/unknown tools, HTTP 401 before authentication and after session revocation, actual transaction-local limits and reset, and unchanged source/ingestion-job records. Temporary smoke accounts were removed. This verifies direct invocation only; it does not prove LLM tool calling or ERP integration.

## Information to request from Sardars

1. ERP name/version and the technical contact responsible for integration.
2. A supported read-only API and documentation, or read-only database views/schema. A representative dated CSV/Excel export is an alternative first checkpoint if direct access is unavailable. Ask whether a test environment is available. Keep credentials out of chat and Git; configure them locally when access exists.
3. A small product/variant sample with stable IDs/SKUs and field definitions. Identify how these IDs map to website products. Product titles alone are not reliable identifiers.
4. Which system owns each fact: product identity, selling price and stock. Ask whether website prices and stock sync from the ERP or are maintained separately, and how often updates happen.
5. Price currency, tax treatment and price-list rules; inventory location and whether quantities mean on-hand, reserved or available-to-sell; update timestamps, acceptable age and which admin/staff roles may see the fields.

These are discovery questions, not assumptions about the ERP schema. Authority may differ by field. Choose the first lookup after inspecting the actual source and its owner's rules.

## Next small runnable checkpoints

1. Inspect the documented schema/sample and agree the minimum source identity, permissions, ID mapping and freshness rules for one lookup. A supported read-only API or database view can provide fresher data; a dated export is simpler to start with but needs explicit age limits.
2. Implement one exact read-only service/repository lookup, strict Pydantic input/output schemas, bounded calls and structured safe errors. Verify it directly before model integration. A price/stock tool must reject missing or stale evidence under the agreed policy.
3. Extend the first verified read-tool boundary to the concrete ERP tool and extend the model interface/Ollama adapter for tool requests. Application code validates names and arguments and enforces authorization. Bound execution time and tool iterations (maximum five); do not execute arbitrary model-supplied SQL/code/functions. Test permission denial, invalid/unknown requests, missing/stale data and timeouts. Model tool-request behavior can first be checked with the existing source-status tool while ERP access is pending.
4. Verify an authorized exact-fact question end to end, including actual local-model tool behavior, and record the result and limitations. Phase 7 later combines structured filtering with descriptive RAG.

No ERP connector or company product tables have been created from assumptions. Synthetic tests verify failure behavior; they cannot prove real ERP integration or current company facts. The first registry is exercised by a working exact metadata read, rather than unused infrastructure.
