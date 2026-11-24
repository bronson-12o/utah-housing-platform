# Utah Housing Data Platform

Build an original, source-supported public-data platform. All service fees must remain zero: local Docker and local kind only, no paid clouds, providers or APIs. No source keys, private property documents or account data in Git.

Agents own separate files; preserve concurrent changes. The coordinator integrates and runs combined checks. Do not publish or deploy independently.

Keep Census reference period, annual/monthly/YTD basis, county/state FIPS, building counts, units and valuation distinct. Units authorized are not completed homes. Validate raw schema and amounts; never infer zeros from missing/unreported values. A rerun must not duplicate records; revisions must be versioned and bad input visibly rejected. Derive expected checks independently of application answers. Synthetic fixtures are explicitly synthetic. Record source URL, retrieval time and SHA256; do not invent accuracy certification.

Architecture and data-model figures must match implemented behavior. Maps must use actual geometry or clearly be labeled schematic. Preserve all existing pictures in other repositories. No AI-generated evidence, maps with invented boundaries, fabricated model scores, or fake screenshots.

Run appropriate unit/integration and isolated actual Docker/PostgreSQL flows. Verify a fresh offline fixture path, live source fetch, safe reruns, revisions, backfill and failure reporting. Never stop or attach to existing owner services/data. Local Kubernetes must use a distinct cluster, explicit context and isolated resources.
