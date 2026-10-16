# Phase 6 — Shopify CSV database proof of concept

Scope agreed 2026-10-16: use the developer's Sardars Shopify product export as a dated database snapshot. ERP access is unavailable and is not required for this proof of concept. Demonstrate one controlled product lookup from PostgreSQL, then verify model tool calling. This is not a live price/inventory integration.

This page records the **initial import checkpoint**. All **4,983 CSV rows / 2,009 handles** were committed in `public.products`; replay skipped all 4,983. At that checkpoint, the original 15 populated SKUs and exported prices were unchanged. The developer later edited SKUs and prices, then designated the current table values as valid for internal-assistant product answers. The current authority, classification and read tool are documented in [the Phase 6 product-tool guide](phase6_product_tool.md). Export/as-of time and currency remain unknown.

## Checkpoint 1: table creation

`public.products` stores one CSV data record per database row. The supplied header has **88 named columns**, all represented. The two unnamed trailing spreadsheet columns are ignored. SQL identifiers use lowercase snake case; `Product` column `info.csv_header` and `SHOPIFY_COLUMN_MAP` retain exact original header spelling, including long metafield names. `Type` maps to `product_type`, `Body (HTML)` to `body_html`, and long discovery/metafield names have shorter unambiguous SQL names.

Shopify can represent one product with multiple rows for variants and extra images. Handles and SKUs are indexed but **not unique**. Continuation rows may have null titles, prices, SKUs and other fields. Do not interpret every row as a distinct product or fill missing values with invented defaults. A future lookup must group/disambiguate variants and avoid treating an image-only row as a sellable variant. The supplied schema has no Shopify product/variant ID; local `id` is a row identifier, not an external product identity.

| Data | Storage |
| --- | --- |
| Prices, compare-at prices, cost, weights, measures, packed dimensions | PostgreSQL `NUMERIC`, without a fixed scale; use Python `Decimal` |
| Inventory quantity | Signed `BIGINT`; null is unknown and negative values are retained |
| Published, shipping/taxable, gift-card and Google Shopping custom-product flags | Nullable `BOOLEAN` |
| Image position | Nullable `INTEGER` |
| SKU, barcodes, titles, descriptions, options, tags, URLs, categories and metafields | `TEXT`; identifiers preserve leading zeros, raw lists and serialized metafields are not guessed apart |

All exported fields except `handle` are nullable. Original HTML remains untrusted data; storing it neither executes it nor authorizes rendering it. Image URLs are stored strings, not fetched by this schema. `Cost per item` is retained for source completeness; a later tool must use an explicit output allowlist and agreed field permissions, rather than expose the whole row.

Eight technical columns were added by the initial migration (96 columns at that checkpoint). The later Phase 6 provenance migration adds `source_row_kind`, `price_origin`, and `sku_origin`, bringing the current table to 99 columns:

| Column | Meaning |
| --- | --- |
| `id` | Database-generated local row key |
| `source_file_name` | Required original CSV filename |
| `source_file_sha256` | Required original-file checksum |
| `source_row_number` | Required one-based data-record number, excluding the header; multiline fields still count as one CSV record |
| `source_exported_at` | Nullable timezone-aware export/as-of time, supplied when known |
| `imported_at` | Database-recorded import time; does not establish the source's freshness |
| `snapshot_currency` | Nullable explicitly supplied three-letter uppercase currency; the CSV price header alone does not identify currency |
| `visibility` | Internal `staff` by default or `admin`; application code must enforce it before any future tool output |

`(source_file_sha256, source_row_number)` is unique to prevent accidental duplicate records from the same file. The table can represent different files with the same handle/SKU; the first importer intentionally permits only one verified file snapshot and refuses a different one. A later replacement/removal policy must be agreed explicitly; simply accumulating snapshots is not a synchronization policy.

Migration: `c83d7a16e902`, following `b61c9e42d703`. Reproduce table creation with:

```bash
backend/.venv/bin/alembic upgrade head
backend/.venv/bin/alembic check
```

The migration creates only the new table, constraints and lookup indexes. Its downgrade removes that table and its data; use rollback only in an intentionally disposable environment or after a backup.

Verification: the full backend suite passed 354 tests with three opt-in integrations skipped; 15 isolated storage tests passed. An opt-in real PostgreSQL test verified migration upgrade/downgrade/re-upgrade in a disposable schema, no SQLAlchemy/Alembic drift, exact high-precision decimals, leading-zero identifiers, repeated handles/image rows and timezone-aware import timestamps. The disposable schema was removed afterward. The migration was applied locally: `public.products` has 96 columns, the expected indexes/constraints and zero rows, with no Alembic metadata drift; test rows are never imported into the application table.

## Checkpoint 2: named-header CSV import

`app.ingestion.shopify_products` is a trusted local-operator CLI, not an upload endpoint or model tool. It maps all 88 fields by their exact CSV header names, even when reordered, supplies provenance itself, parses typed fields without floats and rejects malformed/unknown/duplicate headers or bad records before database writes. Empty cells become null; existing text/HTML, SKU/barcode formatting and variant/image rows remain intact. Boolean fields accept true/false case-insensitively. Integer range and finite decimal checks precede insertion.

Bounds: 25 MiB per file, 10,000 records, 250,000 characters per field and insert batches of 250 records. PostgreSQL uses transaction-local fifteen-second statement and two-second lock limits. A table write lock serializes this short import against other writers while readers continue. All batches and value verification share one transaction; a statement or verification failure rolls back the import. A connection failure during commit needs inspection/replay because client acknowledgment may be uncertain. No automatic retries are performed.

Preview is offline and prints the original checksum. Apply requires that checksum to match the current input. The exact original bytes are retained under the checksum in the Git-ignored `data/extracted/shopify_products/originals/` directory with file permissions `0600`. All source row numbers refer to logical CSV data records, excluding the header; embedded HTML newlines do not create extra records.

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.shopify_products "/home/ahmed-hasnain/Downloads/products_export_1.csv"
PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.shopify_products "/home/ahmed-hasnain/Downloads/products_export_1.csv" --apply --expected-sha256 b03d59c12c3f1caa3b0c52164977b8253846ee265022d51f650a60a1fc25d6f5
```

Optional `--exported-at` requires an explicitly known timezone-aware timestamp, `--currency` an explicitly supplied uppercase three-letter code, and `--visibility` staff/admin. Omitted currency/export time remain null, not inferred from filesystem/import time or store location. Retrying with different provenance options cannot silently relabel an existing snapshot.

An exact repeat verifies all stored export/provenance fields and skips without writes. Edited or incomplete snapshots are refused, preserving existing rows; another file is refused until a replacement workflow is agreed. This deliberately protects later manual edits from being overwritten. Random SKU/price test overrides are not generated here and must be clearly distinguished from actual exported values in a later checkpoint. This is an initial snapshot loader, not a completed update/delete synchronization service.

Observed live outcome: 4,983 rows, 2,009 handles, 3,090 price-bearing rows, 1,893 image-only rows and 15 populated SKUs. All rows have staff visibility; all currency/export timestamps remain null. Post-commit verification matched every exported field and provenance value, and a repeated apply returned `inserted_rows: 0`, `skipped_rows: 4983`. Local evidence is `data/extracted/shopify_products/import_verification.json`. The full backend suite passed 382 tests with three opt-in integrations skipped. Focused import/storage tests passed 43/43, including wrong mappings/types, bounds, rollback, repeat verification, conflict preservation and metadata handling; a real PostgreSQL importer/precision/replay check passed in a disposable schema.

Refresh the table in DataGrip to inspect it. This read-only query should return `4983` and `2009`:

```sql
SELECT count(*) AS csv_rows, count(DISTINCT handle) AS product_handles
FROM public.products;
```

## Remaining checkpoints require the developer's go-ahead

1. Read-only CSV structure inspection is complete: all 88 headers match, all 4,983 data records have the right width and compatible basic values, and 2,009 handles identify product groups. There are 3,090 price-bearing variant candidates and 1,893 image-only candidates. Only 15 rows have SKUs; choose handle/option lookup rather than requiring a SKU. See [the validation report](phase6_shopify_csv_validation.md). Export time/currency remain unknown until supplied.
2. Initial single-snapshot import and unchanged replay are complete. Agree any future replacement/removal workflow before adding a different file; synthetic overrides are a separate decision. Do not claim exported prices/stock are live.
3. Implement one narrow read-only product tool with strict inputs/results, authorization, explicit field allowlists, bounded results and safe missing/ambiguous outcomes. Verify it directly against imported real records.
4. Connect that verified tool to local-model tool requests; test argument validation, tool choice, permissions, timeouts and the final answer. No arbitrary SQL or model-controlled function execution is allowed.

## Internet access is a separate tool

A registered application tool can call an approved web-search service or controlled web fetcher when explicitly implemented. The database product tool will query PostgreSQL only. Internet search is not automatically granted to a model or every tool. A later search tool needs bounded requests/results, approved network access, safe URL handling and citations; retrieved pages remain untrusted data. Public search cannot certify current Sardars ERP inventory or supersede the agreed source for business facts. No internet-search tool is added here.

Shopify reference: [Using CSV files to import and export products](https://help.shopify.com/en/manual/products/import-export/using-csv), especially variant/option fields and multiple-image rows. The database mapping follows the developer's pasted header; newer Shopify header labels are not substituted silently.
