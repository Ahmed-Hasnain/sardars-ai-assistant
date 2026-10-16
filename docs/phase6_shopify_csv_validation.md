# Shopify CSV structure verification — 2026-10-16

Input: `/home/ahmed-hasnain/Downloads/products_export_1.csv`.

SHA-256: `b03d59c12c3f1caa3b0c52164977b8253846ee265022d51f650a60a1fc25d6f5`.

Follow-up on 2026-10-16: the developer authorized the import after the failed DataGrip attempt. All 4,983 rows are now committed and verified; repeat import skips all 4,983 without inserts. See [the import checkpoint](phase6_shopify_products.md). The structural inspection below remains the historical read-only evidence.

This was a read-only inspection. No CSV data was inserted into PostgreSQL, no model was called and the original file was not changed.

| Check | Observed result |
| --- | --- |
| File size | 8,878,112 bytes |
| Encoding | Decodes as UTF-8; no UTF-8 BOM |
| Actual headers | 88 named columns, no blank or duplicate headers |
| Table mapping | All 88 headers match `SHOPIFY_COLUMN_MAP` exactly, in order |
| Missing or unexpected headers | None |
| Nonempty CSV data records | 4,983; CSV parser handles embedded HTML/commas/newlines |
| Row-width mismatches | None |
| Blank handles | None |
| Distinct handles | 2,009 |
| Handles appearing on multiple rows | 962 |
| Blank-title continuation records | 2,974 |
| Image-only candidate records | 1,893: image URL present; SKU, price and option values blank |
| Price-bearing variant candidates | 3,090; handle + option1/2/3 value combinations are distinct within this file, without establishing external variant IDs |
| Integer storage ranges | All checked values fit their PostgreSQL integer column ranges |
| Blank price / inventory fields | 1,893 records each; preserve unknowns rather than filling with zero |
| Nonempty SKU records | Only 15, all distinct |
| Typed-field compatibility | Nonblank booleans are true/false, numeric fields parse as finite decimals, integer quantities/positions parse correctly |
| PostgreSQL text compatibility | No NUL characters found |
| Validation errors in the checks above | Zero |

The two unnamed trailing columns in the pasted Markdown table do not exist in the actual CSV. The existing database schema needs no header changes.

The CSV's low SKU coverage changes the first lookup design: prefer a product handle, returning clearly identified option variants; do not require every product to have a SKU. Grouping/variant identity and snapshot selection must be settled during the next checkpoint. The current local row ID is not a Shopify product/variant ID.

This verifies file structure and basic storage compatibility, not the accuracy, currency, freshness or business meaning of product claims. Export/as-of time, currency and inventory-location semantics still need confirmation. Prices/stock can only be described as snapshot values under an explicit policy. Import behavior, repeat imports and the product tool are not implemented or tested here.
