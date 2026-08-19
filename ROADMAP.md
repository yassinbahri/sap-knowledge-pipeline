# Roadmap

This roadmap communicates direction rather than a promise of delivery dates. Discussion and
small, focused pull requests are welcome. Before starting a larger item, comment on its GitHub
issue so the design can be agreed upon first.

## `0.1.x` — make the alpha easier to adopt

- Add HANA configuration and catalog discovery to the command-line interface.
- Publish tested, copyable examples for common OData and HANA setups.
- Improve diagnostics without logging credentials or sensitive record values.
- Add more contributor documentation and focused unit-test fixtures.

## `0.2` — safer incremental synchronization

- Carry recipe-approved authorization and business metadata into filterable vector payloads.
- Support watermark-based incremental HANA snapshots.
- Reconcile deleted source records through explicit policies.
- Persist richer run statistics and structured observability events.
- Add opt-in field transformation and redaction hooks before document rendering.
- Add retrieval evaluation for relevance, citation integrity, and access-control leakage.

Product priorities are informed by the linked evidence in
[`docs/product-research.md`](docs/product-research.md).

## `0.3` — extension ecosystem

- Define stable protocols for custom source and vector-store integrations.
- Add maintained recipe packs for selected SAP business domains, beginning with finance.
- Evaluate additional targets such as PostgreSQL/pgvector without coupling the core package to
  one RAG framework.
- Document production deployment patterns and compatibility guarantees.

## Good first contributions

Good first issues are intentionally small and should include an implementation hint, expected
tests, and acceptance criteria. Useful starting areas include documentation examples, metadata
fixtures, error-message tests, and isolated recipe additions that contain no proprietary SAP data.

See the [open issues](https://github.com/yassinbahri/sap-knowledge-pipeline/issues) and filter by
[`good first issue`](https://github.com/yassinbahri/sap-knowledge-pipeline/labels/good%20first%20issue).
