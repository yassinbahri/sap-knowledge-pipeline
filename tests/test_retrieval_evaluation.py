from __future__ import annotations

from sap_knowledge.knowledge import Citation
from sap_knowledge.vector import SearchHit, evaluate_retrieval


def _hit(company_code: str, roles: list[str], *, suffix: str) -> SearchHit:
    return SearchHit(
        chunk_id=f"chunk-{suffix}",
        document_id=f"document-{suffix}",
        text="Synthetic maintenance record",
        score=0.9,
        citation=Citation(entity_set="MaintenanceOrders", key={"OrderID": suffix}),
        metadata={"sap_company_code": company_code, "security_roles": roles},
    )


def test_evaluation_accepts_cited_hits_within_all_scopes() -> None:
    report = evaluate_retrieval(
        (_hit("1000", ["MAINTENANCE", "AUDIT"], suffix="1"),),
        allowed_scopes={
            "sap_company_code": {"1000"},
            "security_roles": {"MAINTENANCE"},
        },
    )

    assert report.passed
    assert report.checked == 1
    assert report.missing_citations == ()
    assert report.scope_leaks == ()


def test_evaluation_reports_cross_company_and_role_leaks() -> None:
    report = evaluate_retrieval(
        (
            _hit("1000", ["MAINTENANCE"], suffix="allowed"),
            _hit("2000", ["PROCUREMENT"], suffix="leaked"),
        ),
        allowed_scopes={
            "sap_company_code": {"1000"},
            "security_roles": {"MAINTENANCE"},
        },
    )

    assert not report.passed
    assert report.scope_leaks == (
        "chunk-leaked:sap_company_code",
        "chunk-leaked:security_roles",
    )


def test_evaluation_fails_closed_when_scope_metadata_is_missing() -> None:
    hit = _hit("1000", ["MAINTENANCE"], suffix="missing")
    hit = hit.model_copy(update={"metadata": {"sap_company_code": "1000"}})

    report = evaluate_retrieval(
        (hit,),
        allowed_scopes={"security_roles": {"MAINTENANCE"}},
    )

    assert report.scope_leaks == ("chunk-missing:security_roles",)


def test_evaluation_rejects_empty_scope_configuration() -> None:
    try:
        evaluate_retrieval((), allowed_scopes={"sap_company_code": set()})
    except ValueError as exc:
        assert str(exc) == "each scope must allow at least one value"
    else:
        raise AssertionError("empty scopes should fail closed")
