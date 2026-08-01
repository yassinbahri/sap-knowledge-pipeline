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
