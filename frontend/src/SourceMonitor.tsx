import { useEffect, useState } from "react";
import { AlertTriangle, Clock3, ExternalLink, Globe, Pause, Play, Plus, RefreshCw, Trash2 } from "lucide-react";
import { api } from "./api";
import type { MonitoredSource, SourceCrawlResult } from "./types";

const RBI_URL = "https://www.rbi.org.in/Scripts/NotificationUser.aspx";

function formatDate(value: string | null): string {
  if (!value) return "Not yet checked";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Not yet checked" : date.toLocaleString();
}

export default function SourceMonitor({ onCrawlComplete }: { onCrawlComplete: () => void }) {
  const [items, setItems] = useState<MonitoredSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [interval, setInterval] = useState(60);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function reload() {
    setLoading(true);
    try { const result = await api.listSourceMonitors(); setItems(result.items); setError(""); }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to load sources."); }
    finally { setLoading(false); }
  }
  useEffect(() => { void reload(); }, []);

  async function add(kind: "rbi_notifications" | "custom") {
    setBusyId("add"); setError(""); setNotice("");
    try {
      const result = await api.createSourceMonitor({
        name: kind === "rbi_notifications" ? "RBI Notifications" : (name.trim() || "Custom source"),
        url: kind === "rbi_notifications" ? RBI_URL : url.trim(),
        source_kind: kind, poll_interval_minutes: interval
      });
      setItems(current => [result, ...current]); setName(""); setUrl("");
      setNotice("Source added. It will be checked automatically; use Check now for the initial crawl.");
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to add source."); }
    finally { setBusyId(""); }
  }
  async function crawl(source: MonitoredSource) {
    setBusyId(source.id); setError(""); setNotice("");
    try {
      const result: SourceCrawlResult = await api.crawlSourceMonitor(source.id);
      setItems(current => current.map(item => item.id === source.id ? result : item));
      if (result.last_error) {
        setError(result.last_error);
      } else {
        setNotice("Check complete: " + result.documents_ingested + " new or updated document(s) ingested; " + result.duplicates_skipped + " duplicate(s) skipped.");
      }
      if (result.documents_ingested > 0) onCrawlComplete();
    } catch (e) { setError(e instanceof Error ? e.message : "Source check failed."); }
    finally { setBusyId(""); }
  }
  async function toggle(source: MonitoredSource) {
    setBusyId(source.id);
    try {
      const result = await api.updateSourceMonitor(source.id, { enabled: !source.enabled });
      setItems(current => current.map(item => item.id === source.id ? result : item));
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to update source."); }
    finally { setBusyId(""); }
  }
  async function remove(source: MonitoredSource) {
    if (!window.confirm("Remove " + source.name + " from monitored sources?")) return;
    setBusyId(source.id);
    try { await api.deleteSourceMonitor(source.id); setItems(current => current.filter(item => item.id !== source.id)); }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to remove source."); }
    finally { setBusyId(""); }
  }

  return <div className="source-monitor-page">
    <div className="simple-page-heading">
      <div><div className="eyebrow">AUTOMATED REGULATORY MONITORING</div><h1>Regulatory sources</h1><p>Monitor official publications and detect new or amended documents.</p></div>
      <span className="upload-count-pill"><Globe size={15} />{items.filter(item => item.enabled).length} active</span>
    </div>
    {error && <div className="source-error-banner" role="alert">{error}</div>}
    {notice && <div className="source-message" role="status">{notice}</div>}
    <section className="simple-section">
      <div className="simple-section-header"><div><h2>Add a source</h2><p>Start with RBI or add another public regulatory page or feed.</p></div></div>
      <div className="source-add-grid">
        <div className="source-tile">
          <span className="source-icon"><Globe size={19} /></span>
          <div className="source-copy"><strong>Reserve Bank of India</strong><small>Notifications page · circulars and directions</small><a className="source-url-link" href={RBI_URL} target="_blank" rel="noreferrer">Open RBI page ↗</a></div>
          <button className="button primary" disabled={busyId !== "" || items.some(item => item.url === RBI_URL)} onClick={() => void add("rbi_notifications")}><Plus size={14} />{items.some(item => item.url === RBI_URL) ? "Added" : "Add RBI"}</button>
        </div>
        <form className="source-tile source-form" onSubmit={event => { event.preventDefault(); void add("custom"); }}>
          <strong>Add another source URL</strong>
          <label>Source name<input value={name} onChange={event => setName(event.target.value)} placeholder="e.g. SEBI circulars" maxLength={240} /></label>
          <label>Public URL<input type="url" required value={url} onChange={event => setUrl(event.target.value)} placeholder="https://example.gov.in/notifications" /></label>
          <div className="source-form-bottom">
            <label>Check every<select value={interval} onChange={event => setInterval(Number(event.target.value))}>
              <option value={15}>15 minutes</option><option value={30}>30 minutes</option><option value={60}>1 hour</option><option value={180}>3 hours</option><option value={360}>6 hours</option><option value={720}>12 hours</option><option value={1440}>24 hours</option>
            </select></label>
            <button type="submit" className="button primary" disabled={busyId !== "" || !url.trim()}><Plus size={14} />Add source</button>
          </div>
        </form>
      </div>
    </section>
    <section className="simple-section">
      <div className="simple-section-header"><div><h2>Monitored sources</h2><p>Changes are sent through the document extraction and historical comparison workflow.</p></div><span>{items.length} sources</span></div>
      {loading ? <div className="simple-empty">Loading sources…</div> : items.length === 0 ? <div className="simple-empty"><Globe size={22} /><strong>No sources configured</strong><span>Add RBI Notifications or a custom public URL.</span></div> :
        <div className="source-list">{items.map(source => <article className="source-card" key={source.id}>
          <div className="source-card-top"><div className="source-copy"><strong>{source.name}</strong><small>{source.url}</small></div><span className={"source-status " + (source.enabled ? "enabled" : "disabled")}>{source.enabled ? "Monitoring" : "Paused"}</span></div>
          <div className="source-card-meta"><span><Clock3 size={13} />Every {source.poll_interval_minutes >= 60 ? (source.poll_interval_minutes / 60) + "h" : source.poll_interval_minutes + "m"}</span><span>Last checked: {formatDate(source.last_checked_at)}</span><span>{source.last_changes.length} updates last check</span></div>
          {source.last_error && <div className="source-error"><AlertTriangle size={13} />{source.last_error}</div>}
          {source.last_changes.length > 0 && <div className="source-changes">{source.last_changes.map(change => <div className="source-change" key={change.url}><div><strong>{change.title}</strong><small>{change.status === "new_version" ? "Updated document" : "New document"} · {change.finding_count} comparison finding(s)</small></div><a href={change.url} target="_blank" rel="noreferrer" aria-label="Open source document"><ExternalLink size={14} /></a></div>)}</div>}
          <div className="source-card-actions">
            <button className="button secondary" disabled={busyId === source.id} onClick={() => void crawl(source)}><RefreshCw size={14} className={busyId === source.id ? "spin" : ""} />Check now</button>
            <button className="button secondary" disabled={busyId === source.id} onClick={() => void toggle(source)}>{source.enabled ? <Pause size={14} /> : <Play size={14} />}{source.enabled ? "Pause" : "Resume"}</button>
            <button className="button danger-quiet" disabled={busyId === source.id} onClick={() => void remove(source)}><Trash2 size={14} />Remove</button>
          </div>
        </article>)}</div>}
    </section>
  </div>;
}
