from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.db.models import DocumentVersion, Obligation, Publication, User
from app.db.session import get_session_factory
from app.main import app
from app.services.auth import create_session_token

client = TestClient(app, base_url="https://testserver")


def test_l2_internal_repository_assessment_and_remediation_workflow(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-that-is-at-least-32-characters")
    client.cookies.clear()
    factory = get_session_factory()
    assert factory is not None
    with factory() as session:
        user = User(google_sub="l2-user-" + uuid.uuid4().hex, email="l2@example.com", display_name="L2 Analyst")
        publication = Publication(
            id="L2-" + uuid.uuid4().hex[:12], title="AI governance circular",
            jurisdiction="India", status="Awaiting review",
        )
        session.add_all([user, publication])
        session.flush()
        document = DocumentVersion(
            owner_user_id=user.id, publication_id=publication.id, filename="circular.txt",
            extension="txt", size_bytes=100, sha256=uuid.uuid4().hex,
            extraction_method="test", extraction_result={}, extracted_text="model inventory annual review",
        )
        session.add(document)
        session.flush()
        session.add(Obligation(
            document_version_id=document.id, requirement="Maintain an inventory of AI systems and review it annually.",
            classification="Mandatory requirement", applies_to=["regulated entities"],
            source_reference="TXT line 2", source_excerpt="Maintain an inventory of AI systems and review it annually.",
            evidence_verified=True,
        ))
        session.commit()
        document_id = document.id
        token = create_session_token(user.id)

    client.cookies.set("regulens_session", token)
    headers = {"X-ReguLens-Request": "browser"}
    asset_response = client.post("/api/v1/internal-assets", headers=headers, json={
        "asset_type": "control", "name": "AI model inventory control",
        "description": "Maintains an inventory of AI systems.",
        "content": "The inventory of AI systems is reviewed annually.",
        "department": "Risk", "owner_name": "AI Governance Lead", "criticality": "high",
    })
    assert asset_response.status_code == 200, asset_response.text
    assert asset_response.json()["asset_type"] == "control"

    assessment_response = client.post(
        f"/api/v1/documents/{document_id}/impact-assessments", headers=headers
    )
    assert assessment_response.status_code == 200, assessment_response.text
    assessment = assessment_response.json()
    assert len(assessment["mappings"]) == 1
    mapping = assessment["mappings"][0]
    assert mapping["asset"]["name"] == "AI model inventory control"
    assert mapping["gap_status"] in {"addressed", "partially_addressed"}

    review_response = client.patch(
        f"/api/v1/impact-mappings/{mapping['id']}", headers=headers,
        json={"gap_status": "addressed"},
    )
    assert review_response.status_code == 200
    assert review_response.json()["reviewed"] is True

    refreshed = client.get(f"/api/v1/impact-assessments/{assessment['id']}")
    assert refreshed.status_code == 200
    assert refreshed.json()["events"]

    client.cookies.clear()
