from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    AnalysisJob, DocumentSection, DocumentVersion, Obligation, Publication,
    RegulatoryAuthority,
)


def parse_regulatory_date(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.casefold() in {"not identified", "unknown", "n/a"}:
        return None
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(cleaned, pattern).date()
        except ValueError:
            continue
    return None


def find_document_by_hash(
    session: Session, sha256: str, owner_user_id: str | None = None
) -> DocumentVersion | None:
    query = select(DocumentVersion).where(DocumentVersion.sha256 == sha256)
    if owner_user_id is None:
        query = query.where(DocumentVersion.owner_user_id.is_(None))
    else:
        query = query.where(DocumentVersion.owner_user_id == owner_user_id)
    return session.scalar(query)


def _get_or_create_authority(session: Session, name: str, jurisdiction: str) -> RegulatoryAuthority | None:
    if not name or name.casefold() in {"not identified", "unknown"}:
        return None
    authority = session.scalar(
        select(RegulatoryAuthority).where(
            func.lower(RegulatoryAuthority.name) == name.casefold(),
            func.lower(RegulatoryAuthority.jurisdiction) == jurisdiction.casefold(),
        )
    )
    if authority:
        return authority
    authority = RegulatoryAuthority(name=name[:240], jurisdiction=(jurisdiction or "Unknown")[:120])
    session.add(authority)
    session.flush()
    return authority


def persist_analysis(
    session: Session,
    *,
    analysis: dict[str, Any],
    extracted_text: str,
    source_sections: list[dict[str, str]],
    mime_type: str | None,
    owner_user_id: str | None = None,
) -> dict[str, Any]:
    publication_data = analysis["publication"]
    document_data = analysis["document"]
    extraction = analysis["extraction"]
    sha256 = str(document_data["sha256"])

    existing = find_document_by_hash(session, sha256, owner_user_id)
    if existing:
        return duplicate_persistence_result(existing)

    publication_id = str(publication_data.get("id") or f"UPL-{uuid4().hex[:8].upper()}")
    jurisdiction = str(publication_data.get("country") or "Unknown")
    authority = _get_or_create_authority(
        session, str(publication_data.get("authority") or ""), jurisdiction
    )
    publication = Publication(
        id=publication_id,
        authority_id=authority.id if authority else None,
        title=str(publication_data.get("title") or document_data.get("filename") or "Uploaded publication")[:500],
        reference_number=str(extraction.get("metadata", {}).get("reference_number") or "")[:240] or None,
        jurisdiction=jurisdiction[:120],
        publication_date=parse_regulatory_date(publication_data.get("published")),
        effective_date=parse_regulatory_date(publication_data.get("effective")),
        document_type=str(extraction.get("metadata", {}).get("document_type") or "Regulatory publication")[:120],
        business_areas=[str(publication_data.get("area") or "General regulatory")],
        status=str(publication_data.get("status") or "Awaiting review")[:80],
        source_url=str(publication_data.get("source_url") or "")[:2000] or None,
    )
    session.add(publication)
    session.flush()

    document_version_id = str(uuid4())
    stored_result = deepcopy(analysis)
    stored_result.pop("_persistence", None)
    version = DocumentVersion(
        id=document_version_id,
        owner_user_id=owner_user_id,
        publication_id=publication.id,
        filename=str(document_data.get("filename") or "uploaded-document")[:500],
        extension=str(document_data.get("extension") or "")[:20],
        mime_type=mime_type or None,
        size_bytes=int(document_data.get("size_bytes") or 0),
        sha256=sha256,
        extracted_text=extracted_text,
        extraction_method=str(extraction.get("method") or "Unknown")[:120],
        extraction_model=str(extraction.get("model") or "")[:160] or None,
        extraction_status="completed",
        extraction_metadata=extraction.get("metadata") or {},
        extraction_result=stored_result,
    )
    session.add(version)
    session.flush()

    section_by_reference: dict[str, str] = {}
    for ordinal, source_section in enumerate(source_sections, start=1):
        reference = str(source_section.get("reference") or f"Section {ordinal}")
        section = DocumentSection(
            document_version_id=version.id,
            ordinal=ordinal,
            source_reference=reference[:240],
            section_type="extracted_segment",
            text=str(source_section.get("text") or ""),
        )
        session.add(section)
        session.flush()
        section_by_reference[reference] = section.id

    for item in extraction.get("obligations", []) or []:
        source_reference = str(item.get("source_reference") or "Unknown")
        session.add(Obligation(
            document_version_id=version.id,
            section_id=section_by_reference.get(source_reference),
            requirement=str(item.get("requirement") or "")[:12000],
            classification=str(item.get("classification") or "Other")[:120],
            applies_to=[str(value) for value in item.get("applies_to", []) if str(value).strip()],
            deadline=str(item.get("deadline") or "Not identified")[:240],
            source_reference=source_reference[:240],
            source_excerpt=str(item.get("source_excerpt") or "")[:12000],
            evidence_verified=bool(item.get("evidence_verified", False)),
        ))

    now = datetime.now(timezone.utc)
    session.add(AnalysisJob(
        publication_id=publication.id,
        document_version_id=version.id,
        job_type="document_intelligence",
        status="completed",
        progress=100,
        attempts=1,
        started_at=now,
        completed_at=now,
    ))
    session.commit()
    return {
        "persisted": True,
        "duplicate": False,
        "publication_id": publication.id,
        "document_version_id": version.id,
        "sha256": sha256,
        "stored_sections": len(source_sections),
        "stored_obligations": len(extraction.get("obligations", []) or []),
    }


def duplicate_persistence_result(version: DocumentVersion) -> dict[str, Any]:
    return {
        "persisted": True,
        "duplicate": True,
        "publication_id": version.publication_id,
        "document_version_id": version.id,
        "sha256": version.sha256,
        "stored_sections": 0,
        "stored_obligations": 0,
    }


def list_documents(
    session: Session, *, owner_user_id: str | None = None,
    q: str = "", jurisdiction: str = "", limit: int = 50, offset: int = 0
) -> dict[str, Any]:
    query = (
        select(DocumentVersion, Publication, RegulatoryAuthority)
        .join(Publication, Publication.id == DocumentVersion.publication_id)
        .outerjoin(RegulatoryAuthority, RegulatoryAuthority.id == Publication.authority_id)
    )
    count_query = select(func.count(DocumentVersion.id)).join(Publication, Publication.id == DocumentVersion.publication_id)
    query = query.where(DocumentVersion.owner_user_id == owner_user_id)
    count_query = count_query.where(DocumentVersion.owner_user_id == owner_user_id)
    if q.strip():
        pattern = f"%{q.strip()}%"
        filters = (Publication.title.ilike(pattern) | DocumentVersion.filename.ilike(pattern) | Publication.reference_number.ilike(pattern))
        query = query.where(filters)
        count_query = count_query.where(filters)
    if jurisdiction.strip():
        query = query.where(Publication.jurisdiction == jurisdiction.strip())
        count_query = count_query.where(Publication.jurisdiction == jurisdiction.strip())
    total = int(session.scalar(count_query) or 0)
    rows = session.execute(query.order_by(DocumentVersion.created_at.desc()).limit(limit).offset(offset)).all()
    items = [
        {
            "document_version_id": version.id,
            "publication_id": publication.id,
            "filename": version.filename,
            "sha256": version.sha256,
            "extraction_status": version.extraction_status,
            "extraction_method": version.extraction_method,
            "created_at": version.created_at.isoformat() if version.created_at else None,
            "publication": publication_to_dict(publication, authority.name if authority else None),
        }
        for version, publication, authority in rows
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def publication_to_dict(publication: Publication, authority_name: str | None = None) -> dict[str, Any]:
    return {
        "id": publication.id,
        "title": publication.title,
        "authority": authority_name or "Not identified",
        "country": publication.jurisdiction,
        "area": ", ".join(publication.business_areas or []) or "General regulatory",
        "published": publication.publication_date.isoformat() if publication.publication_date else "Not identified",
        "effective": publication.effective_date.isoformat() if publication.effective_date else "Not identified",
        "status": publication.status,
        "kind": publication.document_type or "Regulatory publication",
        "reference_number": publication.reference_number,
        "source_url": publication.source_url,
    }


def get_document_detail(
    session: Session, document_version_id: str, owner_user_id: str | None = None
) -> dict[str, Any] | None:
    version = session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.id == document_version_id,
            DocumentVersion.owner_user_id == owner_user_id,
        )
    )
    if not version:
        return None
    publication = session.get(Publication, version.publication_id)
    if not publication:
        return None
    authority = session.get(RegulatoryAuthority, publication.authority_id) if publication.authority_id else None
    result = deepcopy(version.extraction_result or {})
    if result.get("publication"):
        result["publication"]["authority"] = authority.name if authority else "Not identified"
    sections = session.scalars(
        select(DocumentSection).where(DocumentSection.document_version_id == version.id).order_by(DocumentSection.ordinal)
    ).all()
    return {
        "document_version_id": version.id,
        "publication": result.get("publication"),
        "document": result.get("document"),
        "extraction": result.get("extraction"),
        "sections": [
            {"id": section.id, "ordinal": section.ordinal, "source_reference": section.source_reference, "text_characters": len(section.text)}
            for section in sections
        ],
        "persistence": {
            "persisted": True,
            "duplicate": False,
            "publication_id": publication.id,
            "document_version_id": version.id,
            "sha256": version.sha256,
            "stored_sections": len(sections),
            "stored_obligations": len(result.get("extraction", {}).get("obligations", []) or []),
            "original_file_stored": bool(version.storage_uri),
        },
    }
