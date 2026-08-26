# Security Policy

## Reporting a vulnerability

Do not report suspected vulnerabilities in a public issue. Use GitHub's
**Security** tab to submit a private vulnerability report. If private reporting
is temporarily unavailable, contact the maintainer through the address listed
on their GitHub profile and include only enough information to establish a
secure follow-up channel.

Please include the affected version, impact, reproduction conditions, and any
suggested mitigation. Do not include real SAP credentials, internal hostnames,
customer data, continuation URLs, database contents, or production logs.

## Supported versions

Until the first stable release, only the latest published pre-release receives
security fixes.

## Deployment responsibilities

This package does not replace SAP authorization. Deployments must use
least-privilege technical users, approved field allow-lists, protected
checkpoint and event storage, and application-level authorization when
retrieving indexed content. HANA ingestion principals should have `SELECT`
only on curated views whenever possible.

## Error redaction

Package-facing HANA connection and query execution errors do not echo
passwords or SQL parameter values. OData CLI HTTP diagnostics remove URL
credentials, query strings, response bodies, and authorization headers from the
message printed to stderr.

Applications should still avoid logging raw upstream SDK exceptions,
environment variables, full request objects, connection strings, checkpoints,
or event files unless those logs are protected as sensitive data.
