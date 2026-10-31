from __future__ import annotations

import hashlib
import uuid

import pytest

from app.db.models import MonitoredSource, User
from app.db.session import get_session_factory
from app.services import source_monitor
from app.services.auth import create_session_token
from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app, base_url="https://testserver")


def test_validate_source_url_rejects_unsafe_targets(monkeypatch):
    monkeypatch.setattr(source_monitor, "_assert_public_host", lambda host: (_ for _ in ()).throw(ValueError("Private address is not allowed.")) if host == "127.0.0.1" else None)
    assert source_monitor.validate_source_url("https://example.org/notices?year=2026") == "https://example.org/notices?year=2026"
    with pytest.raises(ValueError):
        source_monitor.validate_source_url("file:///etc/passwd")
    with pytest.raises(ValueError):
        source_monitor.validate_source_url("https://user:pass@example.org/notices")
    with pytest.raises(ValueError):
        source_monitor.validate_source_url("https://example.org:8443/notices")
    with pytest.raises(ValueError):
        source_monitor.validate_source_url("http://127.0.0.1/admin")


def test_rbi_notification_detail_page_resolves_document_links(monkeypatch):
    root_url = source_monitor.RBI_NOTIFICATIONS_PAGE_URL
    root_html = b'<html><a href="/Scripts/NotificationUser.aspx?Id=123&amp;Mode=0">RBI Circular</a></html>'
    detail_url = "https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=123&Mode=0"
    detail_html = b'<html><a href="https://rbidocs.rbi.org.in/rdocs/notification/PDFs/circular.pdf">Download PDF</a></html>'

    def fake_get(url, **kwargs):
        if url == detail_url:
            return detail_html, "text/html", detail_url, {}
        raise AssertionError(f"Unexpected fetch: {url}")

    monkeypatch.setattr(source_monitor, "_safe_get", fake_get)
    discovered = source_monitor._discover_document_links(root_url, root_html, "text/html")
    assert discovered == [("RBI Circular", "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/circular.pdf")]


def test_source_monitor_api_is_scoped_to_signed_in_user(monkeypatch):
    client.cookies.clear()
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SESSION_SECRET", "source-monitor-test-secret-that-is-long-enough")
    monkeypatch.setattr("app.api.routes.validate_source_url", lambda url: url)
    factory = get_session_factory()
    assert factory is not None
    with factory() as session:
        user = User(google_sub="source-owner-" + uuid.uuid4().hex, email="source@example.com", display_name="Source owner")
        session.add(user)
        session.commit()
        owner_id = user.id
        token = create_session_token(user.id)
    client.cookies.set("regulens_session", token)
    headers = {"X-ReguLens-Request": "browser"}
    created = client.post(
        "/api/v1/source-monitors",
        headers=headers,
        json={"name": "Custom test", "url": "https://example.org/notices", "source_kind": "custom", "poll_interval_minutes": 120},
    )
    assert created.status_code == 200
    source_id = created.json()["id"]
    assert created.json()["poll_interval_minutes"] == 120
    assert client.get("/api/v1/source-monitors").json()["total"] == 1
    updated = client.patch(f"/api/v1/source-monitors/{source_id}", headers=headers, json={"enabled": False})
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False

    with factory() as session:
        other = User(google_sub="other-source-" + uuid.uuid4().hex, email="other-source@example.com", display_name="Other")
        session.add(other)
        session.commit()
        other_token = create_session_token(other.id)
    client.cookies.set("regulens_session", other_token)
    assert client.get("/api/v1/source-monitors").json()["total"] == 0
    forbidden = client.patch(f"/api/v1/source-monitors/{source_id}", headers=headers, json={"enabled": True})
    assert forbidden.status_code == 404
    client.cookies.clear()


def test_crawler_detects_new_and_changed_document_bytes(monkeypatch):
    monkeypatch.setattr(source_monitor, "_assert_public_host", lambda host: None)
    factory = get_session_factory()
    assert factory is not None
    with factory() as session:
        user = User(google_sub="crawl-user-" + uuid.uuid4().hex, email="crawl@example.com", display_name="Crawler")
        session.add(user)
        session.flush()
        source = MonitoredSource(
            owner_user_id=user.id,
            name="Test regulator",
            url="https://regulator.example/notices",
            source_kind="custom",
            poll_interval_minutes=60,
        )
        session.add(source)
        session.commit()

        current_bytes = {"value": b"first regulatory issue"}
        detail_url = "https://regulator.example/notice?id=1"
        document_url = "https://regulator.example/files/circular.txt"
        root_html = b'<a href="/notice?id=1">Circular 1</a>'
        detail_html = b'<a href="/files/circular.txt">Download</a>'

        def fake_get(url, **kwargs):
            if url == source.url:
                return root_html, "text/html", url, {}
            if url == detail_url:
                return detail_html, "text/html", url, {}
            if url == document_url:
                return current_bytes["value"], "text/plain", url, {"content-type": "text/plain"}
            raise AssertionError("Unexpected fetch " + url)

        def fake_analyze(filename, content):
            digest = hashlib.sha256(content).hexdigest()
            return {
                "publication": {"id": "CRAWL-" + digest[:8], "title": "Circular 1", "authority": "Test regulator", "country": "India", "area": "General", "status": "Awaiting review", "source_url": document_url},
                "document": {"filename": filename, "extension": "txt", "size_bytes": len(content), "sha256": digest},
                "extraction": {"method": "test", "model": None, "metadata": {"authority": "Test regulator", "jurisdiction": "India"}, "obligations": [], "clauses": [], "references": []},
                "_persistence": {"extracted_text": content.decode(), "source_sections": [{"reference": "Page 1", "text": content.decode()}]},
            }

        monkeypatch.setattr(source_monitor, "_safe_get", fake_get)
        monkeypatch.setattr(source_monitor, "analyze_document", fake_analyze)
        monkeypatch.setattr(source_monitor, "persist_document_intelligence", lambda *args, **kwargs: {})
        monkeypatch.setattr(source_monitor, "run_repository_comparison", lambda *args, **kwargs: {"finding_count": 2})

        first = source_monitor.crawl_monitored_source(session, source)
        assert first["documents_ingested"] == 1
        assert first["changes"][0]["status"] == "new_document"

        current_bytes["value"] = b"amended regulatory issue with new clause"
        second = source_monitor.crawl_monitored_source(session, source)
        assert second["documents_ingested"] == 1
        assert second["changes"][0]["status"] == "new_version"
        assert second["changes"][0]["finding_count"] == 2


def test_rbi_monitor_uses_notifications_rss_and_upgrades_existing_rows(monkeypatch):
    monkeypatch.setattr(source_monitor, "_assert_public_host", lambda host: None)
    factory = get_session_factory()
    assert factory is not None
    with factory() as session:
        user = User(google_sub="rbi-rss-" + uuid.uuid4().hex, email="rbi-rss@example.com", display_name="RBI RSS")
        session.add(user)
        session.flush()
        source = MonitoredSource(
            owner_user_id=user.id,
            name="RBI Notifications",
            url=source_monitor.RBI_NOTIFICATIONS_PAGE_URL,
            source_kind="rbi_notifications",
            poll_interval_minutes=60,
        )
        session.add(source)
        session.commit()
        seen = {}

        def fake_get(url, **kwargs):
            seen["url"] = url
            return b'<rss><channel></channel></rss>', "text/xml", url, {}

        monkeypatch.setattr(source_monitor, "_safe_get", fake_get)
        result = source_monitor.crawl_monitored_source(session, source)
        assert seen["url"] == source_monitor.RBI_NOTIFICATIONS_URL
        assert result["url"] == source_monitor.RBI_NOTIFICATIONS_URL
        assert result["last_error"] is None


def test_rss_parser_prefers_document_enclosures():
    feed = b\'''<?xml version="1.0"?><rss><channel><item><title>RBI circular</title><link>https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12</link><enclosure url="https://rbidocs.rbi.org.in/circular.pdf" type="application/pdf" /></item></channel></rss>\'''
    assert source_monitor._feed_items(feed) == [("RBI circular", "https://rbidocs.rbi.org.in/circular.pdf")]
