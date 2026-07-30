"""Validation for opaque, server-provided OData continuation URLs."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit, urlunsplit

from sap_knowledge.errors import UnsafeContinuationUrlError


def _origin(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    return parsed.scheme.lower(), parsed.netloc.lower()


@dataclass(frozen=True)
class ContinuationPolicy:
    """Resolve continuation links while preventing credential leakage and SSRF."""

    service_root: str
    allowed_origins: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    allow_http: bool = False

    def __post_init__(self) -> None:
        parsed = urlsplit(self.service_root)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("service_root must be an absolute URL")
        if parsed.username or parsed.password:
            raise ValueError("service_root must not contain credentials")
        if parsed.scheme.lower() != "https" and not self.allow_http:
            raise ValueError("service_root must use HTTPS unless allow_http=True")

    @property
    def origins(self) -> frozenset[tuple[str, str]]:
        """Return explicitly allowed origins plus the service root origin."""

        return self.allowed_origins | {_origin(self.service_root)}

    def resolve(self, continuation: str) -> str:
        """Resolve and validate an opaque continuation URL."""

        resolved = urljoin(self.service_root, continuation)
        parsed = urlsplit(resolved)

        if parsed.username or parsed.password:
            raise UnsafeContinuationUrlError("continuation URL must not contain credentials")
        if parsed.scheme.lower() not in {"https", "http"}:
            raise UnsafeContinuationUrlError("continuation URL must use HTTP or HTTPS")
        if parsed.scheme.lower() == "http" and not self.allow_http:
            raise UnsafeContinuationUrlError("continuation URL attempted to downgrade HTTPS")
        if _origin(resolved) not in self.origins:
            raise UnsafeContinuationUrlError(
                f"continuation URL origin {_origin(resolved)!r} is not approved"
            )

        # Fragments are not sent to servers and have no place in an OData cursor.
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
