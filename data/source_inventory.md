# Source inventory for the retrieval prototype

| Source | Visibility | Approval/provenance | Status |
| --- | --- | --- | --- |
| `https://sardarandco.com/sitemap.xml` and its public page, article, and product links | Public | Supplied by the project owner in chat on 2026-10-12; site owner/production approval still to be confirmed | Full local crawl: 13 pages, 25 articles, and 970 product descriptions; all pending content review. 142 product links lacked useful descriptive text or were otherwise skipped. |
| `data/sources/company_profile.md` | Public prototype | Text supplied by the project owner in chat on 2026-10-12; business owner review still to be confirmed | Local copy ready for review |
| Staff documents | Staff-only | Developer has no access yet (confirmed 2026-10-12); no document or approver supplied | Deferred; do not index or expose |

The public website and the pasted profile may duplicate each other. Deduplicate before embedding. The extractor omits structured product offer data, but 17 extracted records were heuristically flagged for possible price, stock, or promotion language in their descriptive text; see `data/extracted/public_site_audit.md` locally. Do not treat this heuristic as a complete review. Authoritative sources and freshness rules remain undecided.
