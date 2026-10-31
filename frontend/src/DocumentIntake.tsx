import { useEffect, useRef, useState, type DragEvent } from "react";
import {
  Activity, AlertCircle, CheckCircle2, CloudUpload, FileSearch, FileText, LoaderCircle,
  ShieldCheck, Sparkles, Upload, XCircle,
} from "lucide-react";
import { api } from "./api";
import type { DocumentAnalysis, DocumentRecord, GeminiDiagnostics } from "./types";

interface DocumentIntakeProps {
  analysis: DocumentAnalysis | null;
  onAnalyzed: (result: DocumentAnalysis, fromRepository?: boolean) => void;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export default function DocumentIntake({ analysis, onAnalyzed }: DocumentIntakeProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const comparisonResultsRef = useRef<HTMLDivElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [geminiConfig, setGeminiConfig] = useState<GeminiDiagnostics | null>(null);
  const [recentDocuments, setRecentDocuments] = useState<DocumentRecord[]>([]);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyError, setHistoryError] = useState("");

  async function loadRecentDocuments() {
    setHistoryBusy(true);
    setHistoryError("");
    try {
      const result = await api.listDocuments();
      setRecentDocuments(result.items);
      if (!result.persistence_available) {
        setHistoryError("Persistent storage is not configured on this API.");
      }
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : "Unable to load saved documents.");
    } finally {
      setHistoryBusy(false);
    }
  }

  useEffect(() => {
    api.geminiDiagnostics().then(setGeminiConfig).catch(() => setGeminiConfig(null));
    void loadRecentDocuments();
  }, []);

  // Bring the comparison summary into view after upload or reopening a saved document.
  useEffect(() => {
    if (!analysis) return;
    window.requestAnimationFrame(() => {
      comparisonResultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }, [analysis]);

  function selectFile(candidate?: File) {
    setError("");
    if (!candidate) return;
    const extension = candidate.name.split(".").pop()?.toLowerCase();
    if (!["pdf", "docx", "txt"].includes(extension ?? "")) {
      setFile(null);
      setError("Choose a PDF, DOCX or TXT document.");
      return;
    }
    if (candidate.size > 10 * 1024 * 1024) {
      setFile(null);
      setError("The maximum file size is 10 MB.");
      return;
    }
    setFile(candidate);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    selectFile(event.dataTransfer.files[0]);
  }

  async function handleAnalyze() {
    if (!file || busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await api.analyzeDocument(file);
      onAnalyzed(result);
      await loadRecentDocuments();
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Document analysis failed.");
    } finally {
      setBusy(false);
    }
  }

  async function openSavedDocument(documentVersionId: string) {
    setError("");
    setHistoryError("");
    setHistoryBusy(true);
    try {
      const result = await api.documentDetail(documentVersionId);
      onAnalyzed(result, true);
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : "Unable to open saved analysis.");
    } finally {
      setHistoryBusy(false);
    }
  }

  return <div className="intake-layout">
    <section className="panel intake-panel">
      <div className="panel-heading">
        <div><h2>Upload a regulatory publication</h2>
          <p>Start with a circular, guideline, directive or consultation paper.</p></div>
        <span className="intake-step">STEP 01</span>
      </div>
      <div className={"dropzone " + (dragging ? "dragging" : "")}
        onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}>
        <input ref={inputRef} type="file" accept=".pdf,.docx,.txt"
          onChange={(event) => selectFile(event.target.files?.[0])} />
        <div className="dropzone-icon"><CloudUpload size={25} /></div>
        <strong>Drag and drop your document here</strong>
        <span>or browse from your device</span>
        <button className="button secondary" type="button" onClick={() => inputRef.current?.click()}>
          <Upload size={14} /> Browse files
        </button>
        <small>PDF, DOCX or TXT · Maximum 10 MB · Text-readable documents only</small>
      </div>
      {file && <div className="selected-file">
        <FileText size={18} />
        <div><strong>{file.name}</strong><small>{formatBytes(file.size)}</small></div>
        <button className="icon-button" aria-label="Remove selected file" onClick={() => {
          setFile(null); if (inputRef.current) inputRef.current.value = "";
        }}><XCircle size={16} /></button>
      </div>}
      {error && <div className="intake-error"><AlertCircle size={16} /><span>{error}</span></div>}
      <div className="intake-actions">
        <div><ShieldCheck size={15} /><span>Analysis is persisted. Original file storage is not enabled yet.</span></div>
        <button className="button primary" onClick={() => void handleAnalyze()} disabled={!file || busy}>
          {busy ? <><LoaderCircle size={15} className="spin" /> Analyzing…</> : <><Sparkles size={15} /> Analyze document</>}
        </button>
      </div>
    </section>

    <section className="panel">
      <div className="panel-heading">
        <div><h2>Saved documents</h2><p>Persisted analyses that can be reopened after refresh.</p></div>
        <button className="text-button" onClick={() => void loadRecentDocuments()} disabled={historyBusy}>
          {historyBusy ? "Loading…" : "Refresh"}
        </button>
      </div>
      {historyError && <div className="intake-error"><AlertCircle size={16} /><span>{historyError}</span></div>}
      {recentDocuments.length > 0 ? recentDocuments.map((item) => <div className="source-row" key={item.document_version_id}>
        <div className="source-icon"><FileText size={18} /></div>
        <div className="source-info">
          <strong>{item.publication.title}</strong>
          <small>{item.filename} · {item.publication.country} · {item.extraction_method}</small>
        </div>
        <span className="pill green"><i />Saved</span>
        <button className="text-button" onClick={() => void openSavedDocument(item.document_version_id)} disabled={historyBusy}>Open</button>
      </div>) : <div className="empty-state"><FileText size={22} /><strong>No saved documents yet</strong><span>Uploaded and analyzed documents will appear here.</span></div>}
    </section>

    <section className="panel intake-process">
      <div className="panel-heading"><div><h2>What happens next?</h2><p>Document-to-evidence workflow</p></div></div>
      <div className="process-step"><span>1</span><div><strong>Text extraction</strong><small>Read PDF pages, Word paragraphs and text lines.</small></div></div>
      <div className="process-step"><span>2</span><div><strong>Metadata identification</strong><small>Identify regulator, jurisdiction, dates and reference number.</small></div></div>
      <div className="process-step"><span>3</span><div><strong>Document intelligence</strong><small>Extract clauses, obligations, deadlines and explicit historical references.</small></div></div>
      <div className="process-step"><span>4</span><div><strong>Historical comparison</strong><small>Match saved regulatory documents and compare relevant clauses.</small></div></div>
      <div className="process-step"><span>5</span><div><strong>Human review</strong><small>Verify changes and potential impacts before treating them as compliance actions.</small></div></div>
      <div className={"process-note " + (geminiConfig?.configured ? "gemini-ready" : "gemini-missing")}>
        {geminiConfig ? <>
          <strong>{geminiConfig.configured ? "Gemini key detected by this API" : "Gemini key not detected by this API"}</strong>
          <span>{geminiConfig.configured
            ? `Model: ${geminiConfig.model} · Source: ${geminiConfig.key_source}`
            : "Check the repository-root .env file or backend/.env, then restart FastAPI."}</span>
        </> : <span>Unable to read Gemini configuration from the API. Check the backend URL and try again.</span>}
      </div>
    </section>

    {analysis && <section className="panel analysis-result">
      <div className="analysis-result-header">
        <div><div className="eyebrow">LATEST UPLOAD · {analysis.publication.id}</div>
          <h2>{analysis.publication.title}</h2><p>{analysis.document.filename} · {formatBytes(analysis.document.size_bytes)} · {analysis.document.source_sections} source sections</p></div>
        <span className={"pill " + (analysis.extraction.gemini_status === "used" ? "green" : "amber")}><i />{analysis.extraction.method}</span>
      </div>
      <div className="result-summary"><Sparkles size={16} /><p>{analysis.extraction.summary}</p></div>
      {analysis.comparison ? (
        <div ref={comparisonResultsRef} className="detail-section comparison-results">
          <h3><Activity size={16} /> Historical comparison</h3>
          <div className="history-summary">
            <span className="pill neutral">{analysis.comparison.status === "compared" ? "Compared" : analysis.comparison.status === "no_history" ? "No history" : analysis.comparison.status === "no_relevant_match" ? "No match" : analysis.comparison.status.replace(/_/g, " ")}</span>
            <span>{analysis.comparison.documents_matched} matched · {analysis.comparison.finding_count ?? 0} findings</span>
            {analysis.comparison.status === "no_relevant_match" && <span>{analysis.comparison.documents_considered ?? 0} documents scanned</span>}
          </div>
          {analysis.comparison.status === "no_history" && <p>No earlier documents in this repository yet.</p>}
          {analysis.comparison.status === "no_relevant_match" && <p>No related historical document was found.</p>}
          {analysis.comparison.status === "failed" && <p>{analysis.comparison.message ?? "Comparison failed. Try again or check the API logs."}</p>}
          {(analysis.comparison.comparisons ?? []).map((comparison) => (
            <article className="obligation-card" key={comparison.id}>
              <div className="obligation-top">
                <span>HISTORICAL MATCH</span>
                <span className="pill neutral">{comparison.relationship_type}</span>
              </div>
              <strong>{comparison.historical_title}</strong>
              <div className="obligation-tags">
                <span>Match confidence: {(comparison.match_confidence * 100).toFixed(0)}%</span>
                <span>Matched by: {comparison.matching_method.replace(/_/g, " ")}</span>
                <span>Analysis: {comparison.analysis_method}</span>
              </div>
              <p>{comparison.summary}</p>
              {comparison.findings.length > 0 && <details className="historical-findings">
                <summary>View {comparison.findings.length} clause findings</summary>
                {comparison.findings.map((finding) => (
                <div className="change-finding" key={finding.id}>
                  <div className="obligation-top">
                    <span>{finding.previous_clause_number || finding.updated_clause_number
                      ? `CLAUSE ${finding.updated_clause_number || finding.previous_clause_number}`
                      : "CLAUSE CHANGE"}</span>
                    <span className="pill neutral">{finding.classification}</span>
                  </div>
                  <div className="clause-grid">
                    <article className="clause-card previous">
                      <span>PREVIOUS VERSION · {finding.previous_source_reference || "Not identified"}</span>
                      <p>{finding.previous_text || "No historical clause identified."}</p>
                    </article>
                    <article className="clause-card updated">
                      <span>NEW VERSION · {finding.updated_source_reference || "Not identified"}</span>
                      <p>{finding.updated_text || "No updated clause identified."}</p>
                    </article>
                  </div>
                  <p><strong>What changed:</strong> {finding.change_summary}</p>
                  {finding.why_it_matters && <p><strong>Why it matters:</strong> {finding.why_it_matters}</p>}
                  {(finding.affected_business_areas.length > 0 || finding.affected_departments.length > 0) && (
                    <div className="obligation-tags">
                      {finding.affected_business_areas.map((area) => <span key={area}>{area}</span>)}
                      {finding.affected_departments.map((department) => <span key={department}>{department}</span>)}
                    </div>
                  )}
                  {finding.recommended_actions.length > 0 && <div className="detail-section">
                    <strong>Suggested review actions</strong>
                    <ul>{finding.recommended_actions.map((action) => <li key={action}>{action}</li>)}</ul>
                  </div>}
                  <div className="evidence-footer">
                    <span className={finding.evidence_verified ? "evidence-verified" : "evidence-unverified"}>
                      {finding.evidence_verified ? "Both source clauses verified" : "Source evidence needs review"}
                    </span>
                    <span>{finding.needs_review ? "Human review required" : "No review flag"}</span>
                    <span>Confidence: {(finding.confidence * 100).toFixed(0)}%</span>
                  </div>
                </div>
              ))}
              </details>}
              {comparison.findings.length === 0 && <p className="muted">No material findings for this document.</p>}
            </article>
          ))}
        </div>
      ) : (
        <div ref={comparisonResultsRef} className="detail-section comparison-results">
          <h3><Activity size={16} /> Historical comparison unavailable</h3>
          <p>The API response did not include a repository comparison. Confirm that both the frontend and backend are running the Milestone B branch, then upload the amendment again.</p>
        </div>
      )}
      <div className="metadata-grid">
        <div><small>AUTHORITY</small><strong>{analysis.publication.authority}</strong></div>
        <div><small>JURISDICTION</small><strong>{analysis.publication.country}</strong></div>
        <div><small>PUBLICATION DATE</small><strong>{analysis.publication.published}</strong></div>
        <div><small>EFFECTIVE DATE</small><strong>{analysis.publication.effective}</strong></div>
        <div><small>REFERENCE NUMBER</small><strong>{analysis.extraction.metadata.reference_number}</strong></div>
        <div><small>BUSINESS AREA</small><strong>{analysis.publication.area}</strong></div>
      </div>
      <div className="obligation-heading"><div><h3>Extracted obligations</h3><p>{analysis.extraction.obligation_count} candidate clauses · publication status: awaiting review</p></div>
        <span className="pill neutral">{analysis.document.text_characters.toLocaleString()} characters read</span></div>
      {analysis.extraction.obligations.length > 0 ? <div className="obligation-list">
        {analysis.extraction.obligations.map((item, index) => <article className="obligation-card" key={index}>
          <div className="obligation-top"><span>OBLIGATION {String(index + 1).padStart(2, "0")}</span>
            <span className="pill neutral">{item.classification}</span></div>
          <p className="obligation-text">{item.requirement}</p>
          <div className="obligation-tags">{item.applies_to.map((tag) => <span key={tag}>{tag}</span>)}
            {item.deadline !== "Not identified" && <span>Deadline: {item.deadline}</span>}</div>
          <blockquote className="evidence-quote">“{item.source_excerpt}”</blockquote>
          <div className="evidence-footer"><span><FileText size={13} /> {item.source_reference}</span>
            <span className={item.evidence_verified ? "evidence-verified" : "evidence-unverified"}>
              {item.evidence_verified ? <CheckCircle2 size={13} /> : <AlertCircle size={13} />}
              {item.evidence_verified ? "Evidence matched" : "Evidence needs verification"}
            </span></div>
        </article>)}
      </div> : <div className="empty-obligations"><FileText size={20} /><strong>No candidate obligations identified</strong>
        <span>Review the document manually. The parser may not identify tables, scanned text or unusual legal phrasing.</span></div>}
      <div className="extraction-note"><AlertCircle size={15} /><span>{analysis.extraction.note}</span></div>
      {(analysis.extraction.clauses?.length ?? 0) > 0 && <div className="detail-section">
        <h3><FileText size={16} /> Structured regulatory clauses ({analysis.extraction.clause_count ?? analysis.extraction.clauses?.length ?? 0})</h3>
        <div className="obligation-list">
          {(analysis.extraction.clauses ?? []).slice(0, 8).map((clause, index) => <article className="obligation-card" key={index}>
            <div className="obligation-top">
              <span>{clause.clause_number && clause.clause_number !== "Not identified" ? `CLAUSE ${clause.clause_number}` : `CLAUSE ${String(index + 1).padStart(2, "0")}`}</span>
              <span className="pill neutral">{clause.clause_type}</span>
            </div>
            {clause.heading && <strong>{clause.heading}</strong>}
            <p className="obligation-text">{clause.text}</p>
            <div className="evidence-footer">
              <span><FileText size={13} /> {clause.source_reference}</span>
              <span className={clause.evidence_verified ? "evidence-verified" : "evidence-unverified"}>
                {clause.evidence_verified ? "Evidence matched" : "Evidence needs verification"}
              </span>
            </div>
          </article>)}
        </div>
        {((analysis.extraction.clauses?.length ?? 0) > 8) && <p className="muted">Showing the first 8 of {analysis.extraction.clauses?.length ?? 0} extracted clauses.</p>}
      </div>}
      {(analysis.extraction.references?.length ?? 0) > 0 && <div className="detail-section">
        <h3><FileSearch size={16} /> Historical references ({analysis.extraction.reference_count ?? analysis.extraction.references?.length ?? 0})</h3>
        {(analysis.extraction.references ?? []).map((reference, index) => <div className="source-row" key={index}>
          <div className="source-icon"><FileText size={17} /></div>
          <div className="source-info">
            <strong>{reference.reference_number || reference.referenced_title || "Referenced instrument"}</strong>
            <small>{reference.relationship_type} · {reference.source_reference}</small>
          </div>
          <span className={reference.evidence_verified ? "evidence-verified" : "evidence-unverified"}>
            {reference.evidence_verified ? "Verified" : "Unverified"}
          </span>
        </div>)}
      </div>}
      <div className="retention-note"><ShieldCheck size={15} /><span>Extracted text, metadata, source sections, obligations and analysis results are stored in the configured database. The original uploaded binary is not retained in this milestone. You can reopen this analysis from Saved documents.</span></div>
    </section>}
  </div>;
}
