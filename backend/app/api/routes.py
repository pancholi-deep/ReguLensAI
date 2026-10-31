from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.data.demo_data import CHANGES, PUBLICATIONS, SOURCES
from app.core.config import gemini_configuration
from app.api.auth_routes import router as auth_router
from app.api.impact_routes import router as impact_router
from app.db.models import User, MonitoredSource
from app.services.auth import auth_configuration, get_current_user, get_optional_user, require_browser_request
from app.db.models import ChangeFinding, DocumentComparison, DocumentVersion, Publication, RegulatoryAuthority
from app.db.session import get_db, get_optional_db, resolve_database_url
from app.repositories.document_repository import (
    duplicate_persistence_result,
    find_document_by_hash,
    get_document_detail,
    list_documents,
    persist_analysis,
    publication_to_dict,
)
from app.repositories.document_intelligence_repository import persist_document_intelligence
from app.services.repository_comparison import (
    get_comparison_detail,
    get_document_comparison_summary,
    run_repository_comparison,
)
from app.services.source_monitor import (
    RBI_NOTIFICATIONS_URL,
    crawl_monitored_source,
    validate_source_url,
    _source_dict,
)
from app.services.document_ingestion import (
    MAX_UPLOAD_BYTES,
    DocumentIngestionError,
    analyze_document,
)

router = APIRouter(prefix="/api/v1", tags=["Regulatory intelligence"])
router.include_router(auth_router)
router.include_router(impact_router)

def _comparison_for_duplicate(
    session: Session, document_version_id: str, owner_user_id: str
) -> dict[str, Any]:
    """Reuse stored comparisons, or retry when the document was uploaded before history existed."""
    summary = get_document_comparison_summary(session, document_version_id, owner_user_id)
    if summary.get("comparisons"):
        return summary
    try:
        return run_repository_comparison(session, document_version_id, owner_user_id)
    except Exception:
        session.rollback()
        import logging
        logging.getLogger(__name__).exception(
            "Repository comparison retry failed for document_version_id=%s",
            document_version_id,
        )
        return {
            "status": "failed",
            "documents_considered": summary.get("documents_considered", 0),
            "documents_matched": 0,
            "finding_count": 0,
            "classification_counts": {},
            "comparisons": [],
            "message": "The document was already saved, but repository comparison could not be completed. Review the server logs.",
        }



def _database_publications(session: Session | None, owner_user_id: str | None) -> list[dict[str, Any]]:
    if session is None or owner_user_id is None:
        return []
    rows = session.execute(
        select(Publication, RegulatoryAuthority)
        .join(DocumentVersion, DocumentVersion.publication_id == Publication.id)
        .outerjoin(RegulatoryAuthority, RegulatoryAuthority.id == Publication.authority_id)
        .where(DocumentVersion.owner_user_id == owner_user_id)
        .order_by(Publication.created_at.desc())
    ).all()
    return [publication_to_dict(publication, authority.name if authority else None) for publication, authority in rows]


@router.get("/health")
def health() -> dict[str, Any]:
    database_url = resolve_database_url()
    return {
        "status": "ok",
        "service": "regulens-api",
        "version": "1.1.0",
        "persistence_configured": bool(database_url),
        "auth_configured": all(auth_configuration().values()),
        "document_data_access_enabled": all(auth_configuration().values()),
        "database_backend": "postgresql" if database_url and database_url.startswith("postgresql") else ("sqlite" if database_url else None),
    }


@router.get("/diagnostics/gemini")
def gemini_diagnostics() -> dict:
    """Report Gemini configuration state without exposing the API key."""
    return gemini_configuration()


@router.get("/diagnostics/storage")
def storage_diagnostics() -> dict[str, Any]:
    database_url = resolve_database_url()
    configured = bool(database_url)
    backend = "postgresql" if database_url and database_url.startswith("postgresql") else ("sqlite" if database_url else "missing")
    auth_ready = all(auth_configuration().values())
    return {
        "configured": configured,
        "backend": backend,
        "durable_storage_expected": backend == "postgresql",
        "auth_configured": auth_ready,
        "document_data_access_enabled": auth_ready,
        "message": (
            "Database is configured. Google OAuth and session signing must also be configured before private document APIs can be used."
            if configured and not auth_ready
            else ("Database and authentication configuration detected. Verify the database migration and Google OAuth origin settings."
                  if configured else "DATABASE_URL is missing. Set it to a PostgreSQL connection string in production.")
        ),
    }


@router.get("/overview")
def overview(
    session: Session | None = Depends(get_optional_db),
    user: User | None = Depends(get_optional_user),
) -> dict:
    publications = _database_publications(session, user.id if user else None) + PUBLICATIONS
    status_counts: dict[str, int] = {}
    country_counts: dict[str, int] = {}
    for item in publications:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
        country_counts[item["country"]] = country_counts.get(item["country"], 0) + 1
    return {
        "total_publications": len(publications),
        "new_or_unreviewed": sum(item["status"] in {"New", "Awaiting review", "Relationship unresolved"} for item in publications),
        "awaiting_review": status_counts.get("Awaiting review", 0),
        "regions_represented": len(country_counts),
        "coverage": [{"country": country, "count": count} for country, count in sorted(country_counts.items())],
        "recent_publications": publications[:5],
    }


@router.get("/publications")
def publications(
    q: str = Query(default="", description="Search title, authority, ID or business area"),
    country: str = Query(default=""),
    status: str = Query(default=""),
    session: Session | None = Depends(get_optional_db),
    user: User | None = Depends(get_optional_user),
) -> dict:
    items = _database_publications(session, user.id if user else None) + PUBLICATIONS
    if q.strip():
        term = q.strip().casefold()
        items = [item for item in items if term in " ".join(str(value) for value in item.values()).casefold()]
    if country:
        items = [item for item in items if item["country"] == country]
    if status:
        items = [item for item in items if item["status"] == status]
    return {"items": items, "total": len(items)}


@router.get("/documents")
def documents(
    q: str = Query(default=""),
    jurisdiction: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    result = list_documents(
        session, owner_user_id=user.id, q=q, jurisdiction=jurisdiction,
        limit=limit, offset=offset,
    )
    result["persistence_available"] = True
    result["access_enabled"] = True
    return result


@router.get("/documents/{document_version_id}")
def document_detail(
    document_version_id: str,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    result = get_document_detail(session, document_version_id, owner_user_id=user.id)
    if result is None:
        raise HTTPException(status_code=404, detail="Document version was not found.")
    result["comparison"] = get_document_comparison_summary(session, document_version_id, user.id)
    return result


@router.get("/documents/{document_version_id}/comparisons")
def document_comparisons(
    document_version_id: str,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    owned = session.scalar(select(DocumentVersion).where(
        DocumentVersion.id == document_version_id,
        DocumentVersion.owner_user_id == user.id,
    ))
    if owned is None:
        raise HTTPException(status_code=404, detail="Document version was not found.")
    return get_document_comparison_summary(session, document_version_id, user.id)


@router.get("/comparisons/{comparison_id}")
def comparison_detail(
    comparison_id: str,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    owned = session.scalar(
        select(DocumentComparison)
        .join(DocumentVersion, DocumentVersion.id == DocumentComparison.new_document_version_id)
        .where(DocumentComparison.id == comparison_id, DocumentVersion.owner_user_id == user.id)
    )
    if owned is None:
        raise HTTPException(status_code=404, detail="Document comparison was not found.")
    result = get_comparison_detail(session, comparison_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Document comparison was not found.")
    return result


def _finding_severity(classification: str) -> str:
    if classification in {"New obligation", "Withdrawn / superseded", "Deadline extended / shortened"}:
        return "high"
    if classification == "No material change":
        return "low"
    return "medium"


@router.get("/changes")
def changes(
    session: Session | None = Depends(get_optional_db),
    user: User | None = Depends(get_optional_user),
) -> dict:
    if session is None or user is None:
        return {"items": [{**item, "is_demo": True} for item in CHANGES], "total": len(CHANGES)}
    rows = session.execute(
        select(ChangeFinding, DocumentComparison, DocumentVersion, Publication)
        .join(DocumentComparison, DocumentComparison.id == ChangeFinding.comparison_id)
        .join(DocumentVersion, DocumentVersion.id == DocumentComparison.new_document_version_id)
        .join(Publication, Publication.id == DocumentVersion.publication_id)
        .where(DocumentVersion.owner_user_id == user.id)
        .order_by(ChangeFinding.created_at.desc())
    ).all()
    stored = []
    for finding, comparison, version, publication in rows:
        stored.append({
            "id": finding.id,
            "publication": publication.title,
            "country": publication.jurisdiction,
            "classification": finding.classification,
            "priority": "High" if _finding_severity(finding.classification) == "high" else "Medium",
            "severity": _finding_severity(finding.classification),
            "confidence": finding.confidence,
            "compliance_status": finding.compliance_status,
            "previous": finding.previous_text or "No historical clause identified.",
            "updated": finding.updated_text or "No updated clause identified.",
            "impact": finding.why_it_matters or finding.change_summary,
            "actions": finding.recommended_actions or ["Review the source clauses and confirm business impact"],
            "source": f"Previous: {finding.previous_source_reference or 'Not identified'}; Updated: {finding.updated_source_reference or 'Not identified'}",
            "comparison_id": comparison.id,
            "evidence_verified": finding.evidence_verified,
            "needs_review": finding.needs_review,
            "is_demo": False,
        })
    demo_items = [{**item, "is_demo": True} for item in CHANGES]
    return {"items": stored + demo_items, "total": len(stored) + len(demo_items)}


@router.patch("/findings/{finding_id}/status")
def update_finding_compliance_status(
    finding_id: str,
    payload: dict[str, str],
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    require_browser_request(request)
    status = payload.get("status", "")
    if status not in {"open", "in_progress", "compliant"}:
        raise HTTPException(status_code=422, detail="Status must be open, in_progress or compliant.")
    finding = session.scalar(
        select(ChangeFinding)
        .join(DocumentComparison, DocumentComparison.id == ChangeFinding.comparison_id)
        .join(DocumentVersion, DocumentVersion.id == DocumentComparison.new_document_version_id)
        .where(
            ChangeFinding.id == finding_id,
            DocumentVersion.owner_user_id == user.id,
        )
    )
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding was not found.")
    finding.compliance_status = status
    session.commit()
    return {"id": finding.id, "compliance_status": finding.compliance_status}


@router.get("/sources")
def sources() -> dict:
    return {"items": SOURCES, "total": len(SOURCES)}


@router.get("/source-monitors")
def list_source_monitors(
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    items = session.scalars(
        select(MonitoredSource)
        .where(MonitoredSource.owner_user_id == user.id)
        .order_by(MonitoredSource.created_at.desc())
    ).all()
    return {"items": [_source_dict(item) for item in items], "total": len(items)}


@router.post("/source-monitors")
def create_source_monitor(
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    require_browser_request(request)
    url = str(payload.get("url") or "").strip()
    try:
        url = validate_source_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if len(url) > 2000:
        raise HTTPException(status_code=422, detail="Source URL must be 2,000 characters or fewer.")
    existing = session.scalar(
        select(MonitoredSource).where(
            MonitoredSource.owner_user_id == user.id,
            MonitoredSource.url == url,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="This source URL is already being monitored.")
    source_kind = str(payload.get("source_kind") or "custom")
    if source_kind not in {"custom", "rbi_notifications"}:
        source_kind = "custom"
    if source_kind == "rbi_notifications" and url != RBI_NOTIFICATIONS_URL:
        raise HTTPException(status_code=422, detail="RBI monitoring must use the official RBI Notifications URL.")
    interval = payload.get("poll_interval_minutes", 60)
    try:
        interval = int(interval)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Polling interval must be a whole number of minutes.")
    if interval < 15 or interval > 1440:
        raise HTTPException(status_code=422, detail="Polling interval must be between 15 minutes and 24 hours.")
    from urllib.parse import urlsplit
    default_name = "RBI Notifications" if source_kind == "rbi_notifications" else (urlsplit(url).hostname or "Custom source")
    source = MonitoredSource(
        owner_user_id=user.id,
        name=str(payload.get("name") or default_name).strip()[:240] or default_name,
        url=url,
        source_kind=source_kind,
        enabled=True,
        poll_interval_minutes=interval,
    )
    session.add(source)
    session.commit()
    session.refresh(source)
    return _source_dict(source)


@router.post("/source-monitors/{source_id}/crawl")
def crawl_source_now(
    source_id: str,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    require_browser_request(request)
    source = session.scalar(
        select(MonitoredSource).where(
            MonitoredSource.id == source_id,
            MonitoredSource.owner_user_id == user.id,
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Monitored source was not found.")
    result = crawl_monitored_source(session, source)
    result["rbi_notifications_url"] = RBI_NOTIFICATIONS_URL if source.source_kind == "rbi_notifications" else None
    return result


@router.patch("/source-monitors/{source_id}")
def update_source_monitor(
    source_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    require_browser_request(request)
    source = session.scalar(
        select(MonitoredSource).where(
            MonitoredSource.id == source_id,
            MonitoredSource.owner_user_id == user.id,
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Monitored source was not found.")
    if "enabled" in payload:
        if not isinstance(payload["enabled"], bool):
            raise HTTPException(status_code=422, detail="Enabled must be true or false.")
        source.enabled = payload["enabled"]
    if "poll_interval_minutes" in payload:
        try:
            interval = int(payload["poll_interval_minutes"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="Polling interval must be a whole number of minutes.")
        if interval < 15 or interval > 1440:
            raise HTTPException(status_code=422, detail="Polling interval must be between 15 minutes and 24 hours.")
        source.poll_interval_minutes = interval
    if "name" in payload:
        source.name = str(payload["name"]).strip()[:240] or source.name
    source.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(source)
    return _source_dict(source)


@router.delete("/source-monitors/{source_id}")
def delete_source_monitor(
    source_id: str,
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, bool]:
    require_browser_request(request)
    source = session.scalar(
        select(MonitoredSource).where(
            MonitoredSource.id == source_id,
            MonitoredSource.owner_user_id == user.id,
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Monitored source was not found.")
    session.delete(source)
    session.commit()
    return {"success": True}


@router.post("/documents")
@router.post("/documents/analyze", include_in_schema=False)
async def analyze_uploaded_document(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    require_browser_request(request)
    filename = file.filename or "uploaded-document"
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if f".{extension}" not in {".pdf", ".docx", ".txt"}:
        raise HTTPException(status_code=415, detail="Supported formats: PDF, DOCX and TXT.")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 10 MB upload limit.")

    checksum = hashlib.sha256(content).hexdigest()
    existing = find_document_by_hash(session, checksum, user.id)
    if existing:
        response = deepcopy(existing.extraction_result or {})
        response["persistence"] = duplicate_persistence_result(existing)
        response["persistence"]["original_file_stored"] = bool(existing.storage_uri)
        response["comparison"] = _comparison_for_duplicate(session, existing.id, user.id)
        return response

    try:
        result = await run_in_threadpool(analyze_document, filename, content)
        persistence_context = result.pop("_persistence", {})
        persistence = persist_analysis(
            session,
            analysis=result,
            extracted_text=str(persistence_context.get("extracted_text") or ""),
            source_sections=persistence_context.get("source_sections") or [],
            mime_type=file.content_type,
            owner_user_id=user.id,
        )
        intelligence_counts = persist_document_intelligence(
            session,
            persistence["document_version_id"],
            result["extraction"],
        )
        persistence.update(intelligence_counts)
        persistence["original_file_stored"] = False
        result["persistence"] = persistence
        try:
            result["comparison"] = run_repository_comparison(session, persistence["document_version_id"], user.id)
        except Exception:
            session.rollback()
            import logging
            logging.getLogger(__name__).exception(
                "Repository comparison failed for document_version_id=%s",
                persistence["document_version_id"],
            )
            result["comparison"] = {
                "status": "failed",
                "documents_considered": 0,
                "documents_matched": 0,
                "finding_count": 0,
                "classification_counts": {},
                "comparisons": [],
                "message": "Document intelligence was saved, but historical comparison failed. Review the server logs before retrying.",
            }
        return result
    except DocumentIngestionError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError:
        session.rollback()
        existing = find_document_by_hash(session, checksum, user.id)
        if existing:
            response = deepcopy(existing.extraction_result or {})
            response["persistence"] = duplicate_persistence_result(existing)
            response["persistence"]["original_file_stored"] = bool(existing.storage_uri)
            response["comparison"] = _comparison_for_duplicate(session, existing.id, user.id)
            return response
        raise HTTPException(status_code=409, detail="A document with this content already exists; retry the request.")
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail="Document analysis or persistence failed unexpectedly.") from exc
