# Phase 6 — source discovery and read-only access

Started: 2026-10-15 at the developer's request. Phase 5 full-crawl ingestion continues separately and remains incomplete.

## Confirmed state

Sardars has an ERP and a website. The developer currently has no ERP access and will ask the company for it. ERP identity, supported interfaces and ERP-to-website synchronization are unknown. The existing website crawl supplies dated descriptive evidence; it does not establish current prices or inventory. The application's PostgreSQL tables currently hold authentication, permissions, sources and ingestion jobs, not an authoritative company catalogue.

The current `ChatModel.chat()` interface returns text only. A tool registry, model tool requests, execution loop and ERP read tools have not been implemented. Source discovery has started; no integration acceptance criterion is complete.

## Information to request from Sardars

1. ERP name/version and the technical contact responsible for integration.
2. A supported read-only API and documentation, or read-only database views/schema. A representative dated CSV/Excel export is an alternative first checkpoint if direct access is unavailable. Ask whether a test environment is available. Keep credentials out of chat and Git; configure them locally when access exists.
3. A small product/variant sample with stable IDs/SKUs and field definitions. Identify how these IDs map to website products. Product titles alone are not reliable identifiers.
4. Which system owns each fact: product identity, selling price and stock. Ask whether website prices and stock sync from the ERP or are maintained separately, and how often updates happen.
5. Price currency, tax treatment and price-list rules; inventory location and whether quantities mean on-hand, reserved or available-to-sell; update timestamps, acceptable age and which admin/staff roles may see the fields.

These are discovery questions, not assumptions about the ERP schema. Authority may differ by field. Choose the first lookup after inspecting the actual source and its owner's rules.

## Small runnable checkpoints after source discovery

1. Inspect the documented schema/sample and agree the minimum source identity, permissions, ID mapping and freshness rules for one lookup. A supported read-only API or database view can provide fresher data; a dated export is simpler to start with but needs explicit age limits.
2. Implement one exact read-only service/repository lookup, strict Pydantic input/output schemas, bounded calls and structured safe errors. Verify it directly before model integration. A price/stock tool must reject missing or stale evidence under the agreed policy.
3. Register that concrete tool explicitly and extend the model interface/Ollama adapter for tool requests. Application code validates names and arguments and enforces authorization. Bound execution time and tool iterations (maximum five); do not execute arbitrary model-supplied SQL/code/functions. Test permission denial, invalid/unknown requests, missing/stale data and timeouts.
4. Verify an authorized exact-fact question end to end, including actual local-model tool behavior, and record the result and limitations. Phase 7 later combines structured filtering with descriptive RAG.

No company connector, product tables, tool registry or model tool calling is added merely to fill folders before the source is known. Synthetic unit tests later verify failure behavior; they cannot prove real ERP integration or current company facts. Avoid concurrent heavy model tests while the serial website embedding import is running.
