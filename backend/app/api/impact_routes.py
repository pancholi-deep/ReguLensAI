from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AssessmentEvent, DocumentVersion, ImpactAssessment, ImpactMapping,
    InternalAsset, Obligation, Recommendation, RemediationAction, User,
)
from app.db.session import get_db
from app.services.auth import get_current_user, require_browser_request

router = APIRouter(prefix="/api/v1", tags=["Internal controls and impact"])


def _id() -> str:
    return str(uuid4())


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]{3,}", (value or "").lower())
            if token not in {"shall", "must", "should", "will", "with", "from", "that", "this", "their", "into", "under", "within", "entity", "entities"}}


def _score(requirement: str, asset: InternalAsset) -> float:
    required = _tokens(requirement)
    available = _tokens(" ".join([asset.name, asset.description, asset.content, asset.department or "", asset.system_name or ""]))
    if not required or not available:
        return 0.0
    overlap = len(required & available)
    return overlap / max(1, len(required))


def _asset_dict(item: InternalAsset) -> dict[str, Any]:
    return {
        "id": item.id, "asset_type": item.asset_type, "name": item.name,
        "description": item.description, "content": item.content,
        "department": item.department, "owner_name": item.owner_name,
        "system_name": item.system_name, "criticality": item.criticality,
        "metadata": item.metadata_json or {}, "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _action_dict(item: RemediationAction) -> dict[str, Any]:
    return {
        "id": item.id, "assessment_id": item.assessment_id, "impact_mapping_id": item.impact_mapping_id,
        "recommendation_id": item.recommendation_id, "title": item.title, "description": item.description,
        "owner_name": item.owner_name, "department": item.department,
        "due_date": item.due_date.isoformat() if item.due_date else None,
        "priority": item.priority, "status": item.status,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _assessment_detail(session: Session, assessment: ImpactAssessment, owner_id: str) -> dict[str, Any]:
    mappings = session.scalars(select(ImpactMapping).where(ImpactMapping.assessment_id == assessment.id)).all()
    rows = []
    for mapping in mappings:
        obligation = session.get(Obligation, mapping.obligation_id)
        asset = session.get(InternalAsset, mapping.internal_asset_id) if mapping.internal_asset_id else None
        recommendation = session.scalar(select(Recommendation).where(Recommendation.impact_mapping_id == mapping.id))
        actions = session.scalars(select(RemediationAction).where(
            RemediationAction.impact_mapping_id == mapping.id, RemediationAction.owner_user_id == owner_id
        )).all()
        rows.append({
            "id": mapping.id, "obligation_id": mapping.obligation_id,
            "requirement": obligation.requirement if obligation else "Obligation unavailable",
            "classification": obligation.classification if obligation else "",
            "source_reference": obligation.source_reference if obligation else "",
            "source_excerpt": obligation.source_excerpt if obligation else "",
            "evidence_verified": obligation.evidence_verified if obligation else False,
            "asset": _asset_dict(asset) if asset else None,
            "gap_status": mapping.gap_status, "match_score": mapping.match_score,
            "rationale": mapping.rationale, "evidence": mapping.evidence or {},
            "reviewed": mapping.reviewed,
            "recommendation": ({
                "id": recommendation.id, "recommendation": recommendation.recommendation,
                "draft_wording": recommendation.draft_wording, "priority": recommendation.priority,
                "status": recommendation.status,
            } if recommendation else None),
            "actions": [_action_dict(action) for action in actions],
        })
    events = session.scalars(select(AssessmentEvent).where(
        AssessmentEvent.assessment_id == assessment.id
    ).order_by(AssessmentEvent.created_at.desc())).all()
    return {
        "id": assessment.id, "document_version_id": assessment.document_version_id,
        "status": assessment.status, "summary": assessment.summary,
        "created_at": assessment.created_at.isoformat() if assessment.created_at else None,
        "mappings": rows,
        "events": [{
            "id": event.id, "actor_user_id": event.actor_user_id,
            "event_type": event.event_type, "details": event.details or {},
            "created_at": event.created_at.isoformat() if event.created_at else None,
        } for event in events],
        "counts": {key: sum(1 for row in rows if row["gap_status"] == key) for key in
                   ["addressed", "partially_addressed", "not_addressed", "unassessable"]},
    }


@router.get("/internal-assets")
def list_internal_assets(session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    items = session.scalars(select(InternalAsset).where(InternalAsset.owner_user_id == user.id)
                            .order_by(InternalAsset.updated_at.desc())).all()
    return {"items": [_asset_dict(item) for item in items], "total": len(items)}


@router.post("/internal-assets")
def create_internal_asset(payload: dict[str, Any], request: Request,
                          session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_browser_request(request)
    asset_type = str(payload.get("asset_type") or "policy").strip().lower()
    if asset_type not in {"policy", "procedure", "control", "system", "process", "standard"}:
        raise HTTPException(status_code=422, detail="Asset type must be policy, procedure, control, system, process or standard.")
    name = str(payload.get("name") or "").strip()
    if not name or len(name) > 300:
        raise HTTPException(status_code=422, detail="A name of 1–300 characters is required.")
    criticality = str(payload.get("criticality") or "medium").lower()
    if criticality not in {"low", "medium", "high", "critical"}:
        raise HTTPException(status_code=422, detail="Criticality must be low, medium, high or critical.")
    item = InternalAsset(
        owner_user_id=user.id, asset_type=asset_type, name=name,
        description=str(payload.get("description") or "")[:10000],
        content=str(payload.get("content") or "")[:100000],
        department=str(payload.get("department") or "").strip()[:160] or None,
        owner_name=str(payload.get("owner_name") or "").strip()[:240] or None,
        system_name=str(payload.get("system_name") or "").strip()[:240] or None,
        criticality=criticality, metadata_json=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return _asset_dict(item)


@router.patch("/internal-assets/{asset_id}")
def update_internal_asset(asset_id: str, payload: dict[str, Any], request: Request,
                          session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_browser_request(request)
    item = session.scalar(select(InternalAsset).where(InternalAsset.id == asset_id, InternalAsset.owner_user_id == user.id))
    if item is None:
        raise HTTPException(status_code=404, detail="Internal asset not found.")
    allowed = {"name", "description", "content", "department", "owner_name", "system_name", "criticality", "metadata"}
    for key in allowed & payload.keys():
        value = payload[key]
        if key == "metadata":
            item.metadata_json = value if isinstance(value, dict) else {}
        elif key == "criticality":
            if value not in {"low", "medium", "high", "critical"}:
                raise HTTPException(status_code=422, detail="Invalid criticality.")
            item.criticality = value
        else:
            setattr(item, key, str(value or "").strip() or None if key in {"department", "owner_name", "system_name"} else str(value or ""))
    item.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(item)
    return _asset_dict(item)


@router.delete("/internal-assets/{asset_id}")
def delete_internal_asset(asset_id: str, request: Request,
                          session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_browser_request(request)
    item = session.scalar(select(InternalAsset).where(InternalAsset.id == asset_id, InternalAsset.owner_user_id == user.id))
    if item is None:
        raise HTTPException(status_code=404, detail="Internal asset not found.")
    session.delete(item)
    session.commit()
    return {"success": True}


@router.get("/impact-assessments")
def list_impact_assessments(session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    items = session.scalars(select(ImpactAssessment).where(ImpactAssessment.owner_user_id == user.id)
                            .order_by(ImpactAssessment.created_at.desc())).all()
    return {"items": [{
        "id": item.id, "document_version_id": item.document_version_id,
        "status": item.status, "summary": item.summary,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    } for item in items], "total": len(items)}


@router.post("/documents/{document_version_id}/impact-assessments")
def run_impact_assessment(document_version_id: str, request: Request,
                          session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_browser_request(request)
    document = session.scalar(select(DocumentVersion).where(
        DocumentVersion.id == document_version_id, DocumentVersion.owner_user_id == user.id))
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    obligations = session.scalars(select(Obligation).where(Obligation.document_version_id == document.id)).all()
    if not obligations:
        raise HTTPException(status_code=422, detail="This document has no extracted obligations to assess.")
    assets = session.scalars(select(InternalAsset).where(InternalAsset.owner_user_id == user.id)).all()
    assessment = ImpactAssessment(owner_user_id=user.id, document_version_id=document.id,
                                  status="completed", summary="")
    session.add(assessment)
    session.flush()
    for obligation in obligations:
        ranked = sorted((( _score(obligation.requirement, asset), asset) for asset in assets), key=lambda pair: pair[0], reverse=True)
        best_score, best_asset = ranked[0] if ranked else (0.0, None)
        if not assets:
            status, rationale = "unassessable", "No internal policies, controls or systems have been added to the repository."
        elif best_score >= 0.45:
            status, rationale = "addressed", "Strong textual overlap with the internal evidence; reviewer confirmation is still required."
        elif best_score >= 0.2:
            status, rationale = "partially_addressed", "Some related internal evidence was found, but coverage may be incomplete."
        else:
            status, rationale = "not_addressed", "No sufficiently relevant internal evidence was found."
        mapping = ImpactMapping(
            assessment_id=assessment.id, obligation_id=obligation.id,
            internal_asset_id=best_asset.id if best_asset and best_score >= 0.2 else None,
            gap_status=status, match_score=round(best_score, 4), rationale=rationale,
            evidence={"obligation_source": obligation.source_reference,
                      "obligation_excerpt": obligation.source_excerpt,
                      "asset_name": best_asset.name if best_asset and best_score >= 0.2 else None,
                      "matching_method": "token_overlap_v1"},
        )
        session.add(mapping)
        session.flush()
        if status in {"partially_addressed", "not_addressed", "unassessable"}:
            recommendation = (
                f"Review and update internal {best_asset.asset_type if best_asset else 'policy/control'} coverage for this obligation."
                if best_asset else "Assign an accountable owner and create or update a policy/control to address this obligation."
            )
            draft = f"Proposed control statement: The organisation shall define, document, operate and periodically review controls that satisfy: {obligation.requirement}"
            priority = "high" if status == "not_addressed" else "medium"
            session.add(Recommendation(impact_mapping_id=mapping.id, recommendation=recommendation,
                                       draft_wording=draft, priority=priority, status="pending_review"))
    assessment.summary = (
        f"Assessed {len(obligations)} extracted obligations against {len(assets)} internal assets. "
        "Text matching is an initial triage signal; it does not establish legal or operational compliance."
    )
    session.add(AssessmentEvent(assessment_id=assessment.id, actor_user_id=user.id,
                                event_type="assessment_created",
                                details={"obligation_count": len(obligations), "asset_count": len(assets)}))
    session.commit()
    session.refresh(assessment)
    return _assessment_detail(session, assessment, user.id)


@router.get("/impact-assessments/{assessment_id}")
def get_impact_assessment(assessment_id: str, session: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    assessment = session.scalar(select(ImpactAssessment).where(
        ImpactAssessment.id == assessment_id, ImpactAssessment.owner_user_id == user.id))
    if assessment is None:
        raise HTTPException(status_code=404, detail="Impact assessment not found.")
    return _assessment_detail(session, assessment, user.id)


@router.patch("/impact-mappings/{mapping_id}")
def review_impact_mapping(mapping_id: str, payload: dict[str, Any], request: Request,
                          session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_browser_request(request)
    mapping = session.scalar(select(ImpactMapping).join(ImpactAssessment).where(
        ImpactMapping.id == mapping_id, ImpactAssessment.owner_user_id == user.id))
    if mapping is None:
        raise HTTPException(status_code=404, detail="Impact mapping not found.")
    status = payload.get("gap_status", mapping.gap_status)
    if status not in {"addressed", "partially_addressed", "not_addressed", "unassessable"}:
        raise HTTPException(status_code=422, detail="Invalid gap status.")
    mapping.gap_status = status
    mapping.reviewed = True
    if "internal_asset_id" in payload:
        asset_id = payload.get("internal_asset_id")
        if asset_id:
            asset = session.scalar(select(InternalAsset).where(InternalAsset.id == asset_id, InternalAsset.owner_user_id == user.id))
            if asset is None:
                raise HTTPException(status_code=422, detail="Selected internal asset is not in your repository.")
        mapping.internal_asset_id = asset_id or None
    assessment = session.get(ImpactAssessment, mapping.assessment_id)
    session.add(AssessmentEvent(assessment_id=assessment.id, actor_user_id=user.id, event_type="mapping_reviewed",
                                details={"mapping_id": mapping.id, "gap_status": status}))
    session.commit()
    return {"id": mapping.id, "gap_status": mapping.gap_status, "reviewed": mapping.reviewed}


@router.patch("/recommendations/{recommendation_id}")
def review_recommendation(recommendation_id: str, payload: dict[str, Any], request: Request,
                          session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_browser_request(request)
    item = session.scalar(select(Recommendation).join(ImpactMapping).join(ImpactAssessment).where(
        Recommendation.id == recommendation_id, ImpactAssessment.owner_user_id == user.id))
    if item is None:
        raise HTTPException(status_code=404, detail="Recommendation not found.")
    status = payload.get("status")
    if status not in {"approved", "rejected", "pending_review"}:
        raise HTTPException(status_code=422, detail="Status must be approved, rejected or pending_review.")
    item.status = status
    if "draft_wording" in payload:
        item.draft_wording = str(payload["draft_wording"])[:20000]
    session.commit()
    return {"id": item.id, "status": item.status, "draft_wording": item.draft_wording}


@router.get("/remediation-actions")
def list_remediation_actions(session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    items = session.scalars(select(RemediationAction).where(RemediationAction.owner_user_id == user.id)
                            .order_by(RemediationAction.updated_at.desc())).all()
    return {"items": [_action_dict(item) for item in items], "total": len(items)}


@router.post("/remediation-actions")
def create_remediation_action(payload: dict[str, Any], request: Request,
                              session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_browser_request(request)
    mapping = session.scalar(select(ImpactMapping).join(ImpactAssessment).where(
        ImpactMapping.id == payload.get("impact_mapping_id"), ImpactAssessment.owner_user_id == user.id))
    if mapping is None:
        raise HTTPException(status_code=404, detail="Impact mapping not found.")
    recommendation_id = payload.get("recommendation_id")
    if recommendation_id:
        recommendation = session.scalar(select(Recommendation).where(
            Recommendation.id == recommendation_id, Recommendation.impact_mapping_id == mapping.id))
        if recommendation is None:
            raise HTTPException(status_code=422, detail="Recommendation does not belong to this impact mapping.")
    due_date = None
    if payload.get("due_date"):
        try:
            due_date = date.fromisoformat(str(payload["due_date"]))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Due date must use YYYY-MM-DD.") from exc
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="Action title is required.")
    item = RemediationAction(
        owner_user_id=user.id, assessment_id=mapping.assessment_id, impact_mapping_id=mapping.id,
        recommendation_id=recommendation_id, title=title[:300],
        description=str(payload.get("description") or "")[:10000],
        owner_name=str(payload.get("owner_name") or "").strip()[:240] or None,
        department=str(payload.get("department") or "").strip()[:160] or None,
        due_date=due_date, priority=str(payload.get("priority") or "medium"),
        status="open",
    )
    if item.priority not in {"low", "medium", "high", "critical"}:
        raise HTTPException(status_code=422, detail="Invalid priority.")
    session.add(item)
    session.add(AssessmentEvent(assessment_id=mapping.assessment_id, actor_user_id=user.id,
                                event_type="remediation_created", details={"title": title, "mapping_id": mapping.id}))
    session.commit()
    session.refresh(item)
    return _action_dict(item)


@router.patch("/remediation-actions/{action_id}")
def update_remediation_action(action_id: str, payload: dict[str, Any], request: Request,
                              session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_browser_request(request)
    item = session.scalar(select(RemediationAction).where(
        RemediationAction.id == action_id, RemediationAction.owner_user_id == user.id))
    if item is None:
        raise HTTPException(status_code=404, detail="Remediation action not found.")
    if "status" in payload:
        if payload["status"] not in {"open", "in_progress", "blocked", "completed", "cancelled"}:
            raise HTTPException(status_code=422, detail="Invalid action status.")
        item.status = payload["status"]
    if "owner_name" in payload:
        item.owner_name = str(payload["owner_name"] or "").strip()[:240] or None
    if "department" in payload:
        item.department = str(payload["department"] or "").strip()[:160] or None
    if "due_date" in payload:
        try:
            item.due_date = date.fromisoformat(str(payload["due_date"])) if payload["due_date"] else None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Due date must use YYYY-MM-DD.") from exc
    item.updated_at = datetime.now(timezone.utc)
    session.add(AssessmentEvent(assessment_id=item.assessment_id, actor_user_id=user.id,
                                event_type="remediation_updated",
                                details={"action_id": item.id, "status": item.status}))
    session.commit()
    session.refresh(item)
    return _action_dict(item)
