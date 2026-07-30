from __future__ import annotations

import pytest

from sap_knowledge.errors import UnsafeContinuationUrlError
from sap_knowledge.sources.odata import ContinuationPolicy


def test_resolves_relative_continuation_on_service_origin() -> None:
    policy = ContinuationPolicy("https://sap.example.test/odata/service/")

    assert policy.resolve("Notifications?$skiptoken=abc") == (
        "https://sap.example.test/odata/service/Notifications?$skiptoken=abc"
    )


def test_accepts_absolute_continuation_on_service_origin() -> None:
    policy = ContinuationPolicy("https://sap.example.test/odata/service/")
    url = "https://sap.example.test/odata/service/Notifications?$skiptoken=abc#ignored"

    assert policy.resolve(url) == url.removesuffix("#ignored")


@pytest.mark.parametrize(
    "url",
    [
        "https://attacker.example/steal",
        "http://sap.example.test/odata/service/Notifications",
        "https://user:password@sap.example.test/odata/service/Notifications",
        "file:///etc/passwd",
    ],
)
def test_rejects_unsafe_continuations(url: str) -> None:
    policy = ContinuationPolicy("https://sap.example.test/odata/service/")

    with pytest.raises(UnsafeContinuationUrlError):
        policy.resolve(url)
