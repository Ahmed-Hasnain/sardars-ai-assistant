# Source inventory for the internal retrieval prototype

Policy decision, 2026-10-13: the project owner authorized the supplied sources below for the admin/staff-only prototype. Future files, documents, and URLs supplied or registered by authorized admins/staff are eligible for internal retrieval at the source level; individual pages do not require manual approval. Record who supplied a source, its allowed roles, and its version. Source approval is not verification of changing business facts.

| Source | Visibility | Approval/provenance | Status |
| --- | --- | --- | --- |
| `https://sardarandco.com/sitemap.xml` and its public page, article, and product links | Internal users; source itself is public | Supplied 2026-10-12 and authorized by the project owner 2026-10-13 for internal retrieval | Full local crawl: 13 pages, 25 articles, and 970 product descriptions. The raw extracted records still say `pending`; the three indexed seed points now inherit source approval and have `review_status: approved`, `prototype_only: false`. 142 product links lacked useful descriptive text or were otherwise skipped. |
| `data/sources/company_profile.md` | Internal users; supplied as public profile text | Supplied 2026-10-12 and authorized by the project owner 2026-10-13 for internal retrieval | Local copy available; not yet indexed. |
| Staff-only documents | Authorized internal roles only | No document has been supplied yet (confirmed 2026-10-12); future authorized admin/staff uploads follow the source-level policy above | Deferred until actual documents and role scope are available. |

The public website and the pasted profile may duplicate each other. Deduplicate before embedding. The extractor omits structured product offer data, but 17 extracted records were heuristically flagged for possible price, stock, or promotion language in their descriptive text; see `data/extracted/public_site_audit.md` locally. Internal source approval does not make those claims current. Use an authoritative lookup or an explicit as-of/uncertainty statement for changing facts. Authoritative sources and freshness rules remain undecided.
