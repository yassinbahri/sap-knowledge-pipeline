# Product research: SAP grounding gaps

This is a living, evidence-backed input to the roadmap. It records needs rather than copying SAP's
product design. Revisit links and assumptions before starting a major feature.

## Findings as of August 2026

### Authorization and sensitive data must be explicit

SAP's Document Grounding Pipelines API warns that the service does not determine whether content
is confidential or privileged and does not filter it automatically. SAP's vector search API also
supports collection-, document-, and chunk-level metadata filters, including nested logical
conditions. For structured SAP business data, the package should therefore preserve security
attributes separately from embedded text and make scoped retrieval easy and testable.

- [SAP Pipelines API](https://help.sap.com/docs/sap-ai-core/sap-ai-core-service-guide/pipelines-api-07adea99628146a68867a9d2fad5305d)
- [SAP Vector Search metadata filtering](https://help.sap.com/docs/sap-ai-core/generative-ai/vector-search)

### Operators need actionable diagnostics

Community reports show opaque 400/500 responses caused by missing headers, unavailable repository
identifiers, and incomplete secret configuration. Other reports describe pipelines stuck in a
pending state or completing with per-document errors. Our connector should classify retryable and
configuration failures, retain safe operational context, and never expose secrets or record data.

- [Missing Content-Type surfaced as an internal server error](https://community.sap.com/t5/technology-q-a/ai-core-internal-server-error-when-calling-document-grounding-api/qaq-p/14105968)
- [Unavailable grounding repository produced repeated HTTP 400 errors](https://community.sap.com/t5/artificial-intelligence-forum/ai-developer-challenge-week-1-grounding-with-sap-generative-ai-hub/m-p/14369255)
- [Grounding pipeline troubleshooting and per-document status](https://community.sap.com/t5/technology-blog-posts-by-sap/enhance-sap-joule-for-consultants-with-custom-knowledge-grounding/ba-p/14404721)

### Structured operational data is our useful niche

SAP's managed pipeline primarily fetches unstructured files from supported repositories, refreshes
them daily, and documents an 8,000-document limit per pipeline. This package should remain focused
on controlled extraction from OData and HANA, resumable updates, deterministic provenance, and
provider-neutral output rather than becoming another file-ingestion framework.

- [SAP Document Grounding Pipelines API](https://help.sap.com/docs/sap-ai-core/sap-ai-core-service-guide/pipelines-api-07adea99628146a68867a9d2fad5305d)

### Extraction quality and evaluation are visible pain points

Users report weak retrieval when source files contain images and charts without suitable OCR. OCR
is outside the package's structured-data scope, but the underlying lesson applies: successful
ingestion does not prove retrieval quality. We need recipe fixtures, retrieval evaluation datasets,
and measurable citation/recall checks before calling a domain recipe production ready.

- [SAP Community discussion about OCR and poor grounding results](https://community.sap.com/t5/artificial-intelligence-forum/ocr-for-grounding-management/td-p/14328166)

## Prioritized implications

1. Metadata-based retrieval scopes and clear authorization guidance.
2. Retry policy, rate-limit handling, sanitized diagnostics, and structured run telemetry.
3. Incremental HANA watermarks and explicit deletion reconciliation.
4. Evaluation tooling for retrieval relevance, citation integrity, and access-control leakage.
5. Optional SAP AI Core/HANA Cloud vector targets only behind stable provider protocols.

Feedback should be linked to a public source or a reproducible user report. Security reports and
customer-specific SAP data must never be copied into public issues.
