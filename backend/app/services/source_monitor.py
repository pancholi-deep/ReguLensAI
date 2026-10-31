from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import MonitoredSource
from app.db.session import get_session_factory
from app.repositories.document_repository import find_document_by_hash, persist_analysis
from app.repositories.document_intelligence_repository import persist_document_intelligence
from app.services.document_ingestion import MAX_UPLOAD_BYTES, DocumentIngestionError, analyze_document
from app.services.repository_comparison import run_repository_comparison

logger = logging.getLogger(__name__)

RBI_NOTIFICATIONS_URL = "https://www.rbi.org.in/Scripts/NotificationUser.aspx"
MAX_PAGE_BYTES = 3 * 1024 * 1024
MAX_DOCUMENTS_PER_CRAWL = 12
MAX_DETAIL_PAGES_PER_CRAWL = 20
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
USER_AGENT = "ReguLensAI-SourceMonitor/1.0 (+https://www.rbi.org.in/)"


class SourceFetchError(RuntimeError):
    pass


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            label = " ".join(" ".join(self._text).split())
            self.links.append((label, self._href))
            self._href = None
            self._text = []


def validate_source_url(url: str) -> str:
    """Accept public HTTP(S) URLs only; block localhost, private and link-local targets."""
    value = (url or "").strip()
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("Enter a valid public http:// or https:// source URL.")
    if parts.username or parts.password:
        raise ValueError("Source URLs must not contain embedded credentials.")
    if parts.port not in (None, 80, 443):
        raise ValueError("Source URLs may only use standard HTTP or HTTPS ports.")
    _assert_public_host(parts.hostname)
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def _assert_public_host(host: str) -> None:
    try:
        addresses = {result[4][0] for result in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise ValueError("The source host could not be resolved.") from exc
    if not addresses:
        raise ValueError("The source host could not be resolved.")
    for raw_address in addresses:
        address = ipaddress.ip_address(raw_address)
        if not address.is_global:
            raise ValueError("Private, local and reserved network addresses cannot be crawled.")


def _safe_get(url: str, *, max_bytes: int = MAX_PAGE_BYTES) -> tuple[bytes, str, str, dict[str, str]]:
    current = validate_source_url(url)
    with requests.Session() as client:
        client.trust_env = False
        for _ in range(4):
            parts = urlsplit(current)
            _assert_public_host(parts.hostname or "")
            try:
                response = client.get(
                    current,
                    headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf,application/rss+xml,application/atom+xml,*/*;q=0.8"},
                    timeout=(8, 25),
                    allow_redirects=False,
                    stream=True,
                )
            except requests.RequestException as exc:
                raise SourceFetchError(f"Unable to fetch source URL: {exc}") from exc
            if response.is_redirect:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise SourceFetchError("The source returned a redirect without a Location header.")
                current = validate_source_url(urljoin(current, location))
                continue
            if response.status_code < 200 or response.status_code >= 300:
                status = response.status_code
                response.close()
                raise SourceFetchError(f"Source returned HTTP {status}.")
            content_length = response.headers.get("Content-Length")
            if content_length and content_length.isdigit() and int(content_length) > max_bytes:
                response.close()
                raise SourceFetchError("The source response exceeds the allowed size.")
            body = bytearray()
            try:
                for chunk in response.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise SourceFetchError("The source response exceeds the allowed size.")
                headers = {key.lower(): value for key, value in response.headers.items()}
                return bytes(body), response.headers.get("Content-Type", ""), current, headers
            finally:
                response.close()
    raise SourceFetchError("The source redirected too many times.")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _feed_items(body: bytes) -> list[tuple[str, str]]:
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return []
    items: list[tuple[str, str]] = []
    for element in root.iter():
        if _local_name(element.tag) not in {"item", "entry"}:
            continue
        title = ""
        link = ""
        for child in list(element):
            name = _local_name(child.tag)
            if name == "title":
                title = " ".join("".join(child.itertext()).split())
            elif name == "link":
                link = child.attrib.get("href") or (child.text or "").strip()
        if title and link:
            items.append((title, link))
    return items


def _html_links(body: bytes) -> list[tuple[str, str]]:
    text = body.decode("utf-8", errors="replace")
    parser = LinkParser()
    parser.feed(text)
    return parser.links


def _is_document_url(url: str) -> bool:
    return PurePosixPath(urlsplit(url).path.lower()).suffix in ALLOWED_EXTENSIONS


def _is_detail_url(url: str) -> bool:
    parts = urlsplit(url)
    query = {key.lower(): value for key, value in parse_qs(parts.query).items()}
    return (
        PurePosixPath(parts.path.lower()).suffix in {".aspx", ".html", ".htm"}
        and any(key in query for key in {"id", "prid", "documentid", "docid"})
    )


def _filename_from_response(url: str, headers: dict[str, str]) -> str:
    disposition = headers.get("content-disposition", "")
    filename = ""
    for part in disposition.split(";"):
        if "filename=" in part.lower():
            filename = part.split("=", 1)[1].strip().strip('"')
            break
    if not filename:
        filename = PurePosixPath(urlsplit(url).path).name
    filename = filename.split("?", 1)[0] or "regulatory-document.pdf"
    if not PurePosixPath(filename).suffix:
        content_type = headers.get("content-type", "").lower()
        suffix = ".pdf" if "pdf" in content_type else (".docx" if "wordprocessingml" in content_type else ".txt")
        filename += suffix
    return filename[:500]


def _discover_document_links(
    source_url: str, root_body: bytes, content_type: str
) -> list[tuple[str, str]]:
    """Resolve feed/list/detail pages to downloadable PDF, DOCX or TXT documents."""
    root_suffix = PurePosixPath(urlsplit(source_url).path.lower()).suffix
    if root_suffix in ALLOWED_EXTENSIONS or "application/pdf" in content_type.lower():
        return [(PurePosixPath(urlsplit(source_url).path).name or "source.pdf", source_url)]

    feed = _feed_items(root_body)
    root_links = _html_links(root_body)
    discovered: list[tuple[str, str]] = []
    detail_pages: list[tuple[str, str]] = []

    if feed:
        for title, href in feed[:MAX_DETAIL_PAGES_PER_CRAWL]:
            absolute = urljoin(source_url, href)
            if _is_document_url(absolute):
                discovered.append((title, absolute))
            elif _is_detail_url(absolute):
                detail_pages.append((title, absolute))
    else:
        for title, href in root_links:
            absolute = urljoin(source_url, href)
            if _is_document_url(absolute):
                discovered.append((title or PurePosixPath(urlsplit(absolute).path).name, absolute))
            elif _is_detail_url(absolute):
                detail_pages.append((title or absolute, absolute))

    for title, detail_url in detail_pages[:MAX_DETAIL_PAGES_PER_CRAWL]:
        try:
            detail_body, detail_type, final_url, _ = _safe_get(detail_url)
        except (SourceFetchError, ValueError) as exc:
            logger.info("Skipping source detail page %s: %s", detail_url, exc)
            continue
        if "html" not in detail_type.lower() and not detail_type.lower().startswith("text/"):
            if _is_document_url(final_url):
                discovered.append((title, final_url))
            continue
        for label, href in _html_links(detail_body):
            absolute = urljoin(final_url, href)
            if _is_document_url(absolute):
                discovered.append((title or label or PurePosixPath(urlsplit(absolute).path).name, absolute))

    unique: dict[str, tuple[str, str]] = {}
    for title, url in discovered:
        unique[url] = (title.strip() or PurePosixPath(urlsplit(url).path).name, url)
    return list(unique.values())[:MAX_DOCUMENTS_PER_CRAWL]


def _source_dict(source: MonitoredSource) -> dict[str, Any]:
    return {
        "id": source.id,
        "name": source.name,
        "url": source.url,
        "source_kind": source.source_kind,
        "enabled": source.enabled,
        "poll_interval_minutes": source.poll_interval_minutes,
        "last_checked_at": source.last_checked_at.isoformat() if source.last_checked_at else None,
        "last_success_at": source.last_success_at.isoformat() if source.last_success_at else None,
        "last_error": source.last_error,
        "last_changes": source.last_changes or [],
        "created_at": source.created_at.isoformat() if source.created_at else None,
    }


def crawl_monitored_source(session: Session, source: MonitoredSource) -> dict[str, Any]:
    """Fetch a source, detect changed document bytes, ingest versions and compare them."""
    now = datetime.now(timezone.utc)
    source.last_checked_at = now
    source.last_error = None
    changes: list[dict[str, Any]] = []
    try:
        safe_url = validate_source_url(source.url)
        root_body, content_type, final_url, headers = _safe_get(safe_url)
        candidates = _discover_document_links(final_url, root_body, content_type)
        known_items = dict(source.known_items or {})
        processed = 0
        duplicates = 0

        for title, document_url in candidates:
            try:
                content, document_type, final_document_url, document_headers = _safe_get(
                    document_url, max_bytes=MAX_UPLOAD_BYTES
                )
            except (SourceFetchError, ValueError) as exc:
                logger.warning("Unable to fetch document from %s: %s", document_url, exc)
                continue

            filename = _filename_from_response(final_document_url, document_headers)
            extension = PurePosixPath(filename.lower()).suffix
            if extension not in ALLOWED_EXTENSIONS:
                continue
            checksum = hashlib.sha256(content).hexdigest()
            if known_items.get(final_document_url) == checksum:
                continue
            existing = find_document_by_hash(session, checksum, source.owner_user_id)
            if existing:
                known_items[final_document_url] = checksum
                duplicates += 1
                continue

            try:
                analysis = analyze_document(filename, content)
            except DocumentIngestionError as exc:
                logger.warning("Skipping unsupported source document %s: %s", final_document_url, exc)
                continue
            publication = analysis["publication"]
            extraction = analysis["extraction"]
            if title and (not publication.get("title") or publication.get("title") == PurePosixPath(filename).stem):
                publication["title"] = title[:180]
            if source.source_kind == "rbi_notifications" or "rbi.org.in" in (urlsplit(final_document_url).hostname or ""):
                publication["authority"] = "Reserve Bank of India"
                publication["country"] = "India"
                extraction["metadata"]["authority"] = "Reserve Bank of India"
                extraction["metadata"]["jurisdiction"] = "India"
            publication["source_url"] = final_document_url
            persistence_context = analysis.pop("_persistence", {})
            persisted = persist_analysis(
                session,
                analysis=analysis,
                extracted_text=str(persistence_context.get("extracted_text") or ""),
                source_sections=persistence_context.get("source_sections") or [],
                mime_type=document_type or None,
                owner_user_id=source.owner_user_id,
            )
            version_id = persisted["document_version_id"]
            if not persisted.get("duplicate"):
                persist_document_intelligence(session, version_id, extraction)
                try:
                    comparison = run_repository_comparison(session, version_id, source.owner_user_id)
                except Exception:
                    session.rollback()
                    logger.exception("Comparison failed for crawled document %s", final_document_url)
                    comparison = {"status": "failed", "finding_count": 0}
                processed += 1
                changes.append({
                    "title": publication.get("title") or title,
                    "url": final_document_url,
                    "status": "new_version" if known_items.get(final_document_url) else "new_document",
                    "document_version_id": version_id,
                    "finding_count": int(comparison.get("finding_count") or 0),
                    "detected_at": now.isoformat(),
                })
            else:
                duplicates += 1
            known_items[final_document_url] = checksum

        # Retain a bounded hash map so long-lived monitors do not grow without limit.
        source.known_items = dict(list(known_items.items())[-1000:])
        source.last_changes = changes[:50]
        source.last_success_at = now
        source.last_error = None
        session.commit()
        return {
            **_source_dict(source),
            "documents_discovered": len(candidates),
            "documents_ingested": processed,
            "duplicates_skipped": duplicates,
            "changes": changes,
        }
    except Exception as exc:
        session.rollback()
        source.last_checked_at = now
        source.last_error = str(exc)[:2000]
        source.last_changes = []
        session.commit()
        logger.exception("Source crawl failed for %s", source.url)
        return {**_source_dict(source), "documents_discovered": 0, "documents_ingested": 0, "duplicates_skipped": 0, "changes": []}


_scheduler_thread: threading.Thread | None = None
_scheduler_stop = threading.Event()
_scheduler_lock = threading.Lock()


def _due(source: MonitoredSource, now: datetime) -> bool:
    if source.last_checked_at is None:
        return True
    last = source.last_checked_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return now >= last + timedelta(minutes=source.poll_interval_minutes)


def _scheduler_loop() -> None:
    while not _scheduler_stop.is_set():
        factory = get_session_factory()
        if factory and _scheduler_lock.acquire(blocking=False):
            try:
                with factory() as session:
                    now = datetime.now(timezone.utc)
                    sources = session.scalars(
                        select(MonitoredSource).where(MonitoredSource.enabled.is_(True))
                    ).all()
                    for source in sources:
                        if _scheduler_stop.is_set():
                            break
                        if _due(source, now):
                            crawl_monitored_source(session, source)
            except Exception:
                logger.exception("Scheduled source-monitor cycle failed")
            finally:
                _scheduler_lock.release()
        _scheduler_stop.wait(60)


def start_source_monitor_scheduler() -> None:
    global _scheduler_thread
    if os.getenv("SOURCE_CRAWLER_ENABLED", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        return
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    _scheduler_stop.clear()
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop, name="regulens-source-monitor", daemon=True
    )
    _scheduler_thread.start()


def stop_source_monitor_scheduler() -> None:
    _scheduler_stop.set()
    if _scheduler_thread and _scheduler_thread.is_alive():
        _scheduler_thread.join(timeout=2)
