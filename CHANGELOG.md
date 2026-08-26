# Changelog

All notable changes to SAP Knowledge Pipeline are documented here. The project
uses semantic versioning and publishes pre-releases while the public API is
still evolving.

## [Unreleased]

### Added

- Recipe-controlled retrieval metadata that stays outside embedded document text.
- Qdrant metadata filters and repeatable CLI `--filter KEY=VALUE` options for scoped search and
  grounded prompts.
- Bounded retries with jitter and `Retry-After` support for transient OData failures.
- TOML-driven HANA snapshot synchronization through the main `sap-knowledge sync`
  command.

### Security

- CLI HTTP diagnostics now remove URL credentials, query strings, and response bodies.
- HANA connection and query execution errors now avoid echoing passwords or SQL parameter
  values in package-facing exception messages.

## [0.1.0a1] - 2026-08-01

### Added

- OData V2 and V4 clients with safe server-driven pagination.
- EDMX metadata inspection and validated Business Partner recipes.
- Allow-listed document rendering, deterministic chunking, and citations.
- Resumable OData synchronization with JSONL upsert/delete events.
- Local FastEmbed embeddings, Qdrant indexing, search, and grounded prompts.
- Certificate-validated SAP HANA connectivity and explicit snapshot datasets.
- Privilege-filtered HANA catalog discovery for schemas, objects, and columns.
- HANA snapshot conversion into the portable knowledge-event format.
- Python 3.11 through 3.14 support and a fully offline automated test suite.

[Unreleased]: https://github.com/yassinbahri/sap-knowledge-pipeline/compare/0.1.0a1...HEAD
[0.1.0a1]: https://github.com/yassinbahri/sap-knowledge-pipeline/releases/tag/0.1.0a1
