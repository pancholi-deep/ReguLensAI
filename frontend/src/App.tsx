import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, AlertTriangle, CheckCircle2, ChevronRight, FileText,
  LayoutDashboard, LogOut, PanelLeftClose, PanelLeftOpen, RefreshCw,
  ShieldCheck, UploadCloud, type LucideIcon,
} from "lucide-react";
import { api, type AuthUser } from "./api";
import type { ChangeItem, DocumentAnalysis, DocumentRecord } from "./types";
import DocumentIntake from "./DocumentIntake";
import GoogleSignInButton from "./GoogleSignInButton";

type Page = "Dashboard" | "Documents";
type DashboardFilter = "actions" | "documents" | "compliant";
type FindingSeverity = "high" | "medium" | "low";
type RiskTone = "red" | "yellow" | "green";

function getSeverity(item: ChangeItem): "high" | "medium" | "low" {
  if (item.severity) return item.severity;
  if (["New obligation", "Withdrawn / superseded", "Deadline extended / shortened"].includes(item.classification)) return "high";
  if (item.classification === "No material change") return "low";
  return "medium";
}

function getRiskTone(item: ChangeItem): RiskTone {
  if (item.compliance_status === "compliant") return "green";
  const confidence = item.confidence ?? 0;
  return getSeverity(item) === "high" && confidence >= 0.7 ? "red" : "yellow";
}

function riskLabel(item: ChangeItem): string {
  const tone = getRiskTone(item);
  if (tone === "green") return "Compliant";
  if (tone === "red") return "High risk";
  return "Review required";
}

function formatDate(value?: string | null): string {
  if (!value) return "Date unavailable";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "Date unavailable" : parsed.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function Metric({ label, value, caption, tone, icon: Icon, selected, onClick }: {
  label: string; value: number; caption: string; tone: RiskTone | "blue"; icon: LucideIcon;
  selected: boolean; onClick: () => void;
}) {
  return <button type="button" className={`simple-metric ${selected ? "selected" : ""}`}
    aria-pressed={selected} onClick={onClick}>
    <span className="simple-metric-top"><span>{label}</span><span className={`simple-metric-icon ${tone}`}><Icon size={17} /></span></span>
    <strong>{value}</strong><small>{caption}</small>
  </button>;
}

export default function App() {
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [authError, setAuthError] = useState("");
  const [page, setPage] = useState<Page>("Dashboard");
  const [activeFilter, setActiveFilter] = useState<DashboardFilter>("actions");
  const [severityFilter, setSeverityFilter] = useState<FindingSeverity | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [documentCount, setDocumentCount] = useState(0);
  const [findings, setFindings] = useState<ChangeItem[]>([]);
  const [workspaceBusy, setWorkspaceBusy] = useState(false);
  const [workspaceError, setWorkspaceError] = useState("");
  const [latestAnalysis, setLatestAnalysis] = useState<DocumentAnalysis | null>(null);
  const [updatingFinding, setUpdatingFinding] = useState("");

  const loadWorkspace = useCallback(async (showBusy = true) => {
    if (showBusy) setWorkspaceBusy(true);
    setWorkspaceError("");
    try {
      const [documentResult, changeResult] = await Promise.all([api.listDocuments(), api.changes()]);
      setDocuments(documentResult.items);
      setDocumentCount(documentResult.total);
      setFindings(changeResult.items.filter((item) => item.is_demo !== true));
    } catch (error) {
      setWorkspaceError(error instanceof Error ? error.message : "Unable to load your compliance workspace.");
    } finally {
      if (showBusy) setWorkspaceBusy(false);
    }
  }, []);

  useEffect(() => {
    api.currentUser()
      .then(async (session) => {
        setCurrentUser(session.user);
        await loadWorkspace(false);
      })
      .catch(() => setCurrentUser(null))
      .finally(() => setAuthReady(true));
  }, [loadWorkspace]);

  const handleGoogleCredential = useCallback(async (credential: string) => {
    setAuthError("");
    try {
      const session = await api.googleLogin(credential);
      setCurrentUser(session.user);
      setPage("Dashboard");
      await loadWorkspace();
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Google sign-in failed. Please try again.");
    }
  }, [loadWorkspace]);

  async function handleSignOut() {
    try {
      await api.logout();
    } catch {
      // Clear the local workspace even if the session has already expired.
    }
    setCurrentUser(null);
    setDocuments([]);
    setFindings([]);
    setDocumentCount(0);
    setLatestAnalysis(null);
    setPage("Dashboard");
  }

  async function handleComplianceStatus(item: ChangeItem) {
    const nextStatus = item.compliance_status === "compliant" ? "open" : "compliant";
    setUpdatingFinding(item.id);
    try {
      await api.updateFindingStatus(item.id, nextStatus);
      setFindings((current) => current.map((finding) =>
        finding.id === item.id ? { ...finding, compliance_status: nextStatus } : finding
      ));
    } catch (error) {
      setWorkspaceError(error instanceof Error ? error.message : "Unable to update compliance status.");
    } finally {
      setUpdatingFinding("");
    }
  }

  function handleDocumentAnalyzed(result: DocumentAnalysis) {
    setLatestAnalysis(result);
    void loadWorkspace();
  }

  const openActions = useMemo(
    () => findings.filter((item) => item.compliance_status !== "compliant"),
    [findings],
  );
  const compliantCount = findings.filter(
    (item) => item.compliance_status === "compliant",
  ).length;
  const needsReviewCount = openActions.length;
  const compliantFindings = findings.filter((item) => item.compliance_status === "compliant");
  const severityCounts: Record<FindingSeverity, number> = {
    high: openActions.filter((item) => getSeverity(item) === "high").length,
    medium: openActions.filter((item) => getSeverity(item) === "medium").length,
    low: openActions.filter((item) => getSeverity(item) === "low").length,
  };
  const visibleFindings = activeFilter === "compliant"
    ? compliantFindings
    : severityFilter
      ? openActions.filter((item) => getSeverity(item) === severityFilter)
      : openActions;

  if (!authReady) {
    return <main className="login-screen"><div className="login-card"><div className="login-mark"><ShieldCheck size={25} /></div><strong>ReguLens<span>AI</span></strong><p>Checking your secure session…</p><div className="login-spinner" /></div></main>;
  }

  if (!currentUser) {
    return <main className="login-screen">
      <section className="login-card">
        <div className="login-mark"><ShieldCheck size={27} /></div>
        <div className="eyebrow">REGULATORY COMPLIANCE WORKSPACE</div>
        <h1>Welcome to ReguLensAI</h1>
        <p>Sign in to review regulatory changes, track recommended actions and manage your documents.</p>
        {authError && <div className="auth-error-banner" role="alert">{authError}</div>}
        <GoogleSignInButton onCredential={handleGoogleCredential} />
        <small>Your documents and compliance workspace are private to your account.</small>
      </section>
    </main>;
  }

  return <div className={`app-shell simple-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
    <aside className="sidebar simple-sidebar">
      <div className="brand">
        <div className="brand-mark"><ShieldCheck size={21} /></div>
        {!sidebarCollapsed && <div className="brand-copy"><strong>ReguLens<span>AI</span></strong><small>COMPLIANCE WORKSPACE</small></div>}
      </div>
      <nav className="nav-list simple-nav" aria-label="Main navigation">
        <button className={`nav-item ${page === "Dashboard" ? "active" : ""}`} onClick={() => setPage("Dashboard")}
          title={sidebarCollapsed ? "Dashboard" : undefined}>
          <LayoutDashboard size={18} />{!sidebarCollapsed && <span>Dashboard</span>}
          {page === "Dashboard" && !sidebarCollapsed && <ChevronRight size={15} className="nav-chevron" />}
        </button>
        <button className={`nav-item ${page === "Documents" ? "active" : ""}`} onClick={() => setPage("Documents")}
          title={sidebarCollapsed ? "Documents" : undefined}>
          <UploadCloud size={18} />{!sidebarCollapsed && <span>Documents</span>}
          {page === "Documents" && !sidebarCollapsed && <ChevronRight size={15} className="nav-chevron" />}
        </button>
      </nav>
      <div className="sidebar-bottom simple-sidebar-bottom">
        <div className="user-row">
          <div className="avatar">{currentUser.picture ? <img src={currentUser.picture} alt="" /> : (currentUser.name?.slice(0, 2).toUpperCase() ?? "RL")}</div>
          {!sidebarCollapsed && <div><strong>{currentUser.name ?? "Account"}</strong><small>{currentUser.email}</small></div>}
          {!sidebarCollapsed && <button className="icon-button user-signout" title="Sign out" aria-label="Sign out" onClick={() => void handleSignOut()}><LogOut size={15} /></button>}
        </div>
      </div>
    </aside>

    <main className="main-area">
      <header className="topbar simple-topbar">
        <div className="breadcrumb">
          <button className="icon-button sidebar-toggle-top" onClick={() => setSidebarCollapsed((value) => !value)}
            title={sidebarCollapsed ? "Expand navigation" : "Collapse navigation"}
            aria-label={sidebarCollapsed ? "Expand navigation" : "Collapse navigation"}>
            {sidebarCollapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
          </button>
          <strong>{page}</strong>
        </div>
        <div className="topbar-actions">
          <button className="icon-button" onClick={() => void loadWorkspace()} disabled={workspaceBusy} aria-label="Refresh dashboard" title="Refresh">
            <RefreshCw size={17} className={workspaceBusy ? "spin" : ""} />
          </button>
          <span className="signed-in-label">{currentUser.email}</span>
          <button className="icon-button topbar-signout" onClick={() => void handleSignOut()} aria-label="Sign out" title="Sign out"><LogOut size={17} /></button>
        </div>
      </header>

      <div className="content simple-content">
        {workspaceError && <div className="error-banner"><AlertTriangle size={16} /><span>{workspaceError}</span></div>}
        {page === "Dashboard" && <>
          <div className="simple-page-heading">
            <div><div className="eyebrow">OVERVIEW</div><h1>Compliance dashboard</h1><p>Your documents and actions at a glance.</p></div>
            <button className="button primary" onClick={() => setPage("Documents")}><UploadCloud size={15} /> Upload document</button>
          </div>

          <section className="simple-metric-grid" aria-label="Dashboard filters">
            <Metric label="Documents uploaded" value={documentCount} caption="View saved documents" tone="blue" icon={FileText}
              selected={activeFilter === "documents"} onClick={() => { setActiveFilter("documents"); setSeverityFilter(null); }} />
            <Metric label="Actions to review" value={needsReviewCount} caption="Open or in progress" tone="yellow" icon={Activity}
              selected={activeFilter === "actions"} onClick={() => { setActiveFilter("actions"); setSeverityFilter(null); }} />
            <Metric label="Marked compliant" value={compliantCount} caption="Confirmed by your team" tone="green" icon={CheckCircle2}
              selected={activeFilter === "compliant"} onClick={() => { setActiveFilter("compliant"); setSeverityFilter(null); }} />
          </section>

          <section className="simple-section dashboard-results">
            <div className="simple-section-header">
              <div>
                <h2>{activeFilter === "documents" ? "Uploaded documents" : activeFilter === "compliant" ? "Marked compliant" : "Actions to review"}</h2>
                <p>{activeFilter === "documents" ? "Your saved document history." : activeFilter === "compliant" ? "Items your team has explicitly marked compliant." : "Prioritized items that still need attention."}</p>
              </div>
              <span>{activeFilter === "documents" ? `${documentCount} documents` : `${visibleFindings.length} items`}</span>
            </div>
            {activeFilter === "actions" && <div className="severity-filters" aria-label="Filter actions by severity">
              <span>Severity</span>
              {(["high", "medium", "low"] as FindingSeverity[]).map((severity) => (
                <button
                  type="button"
                  key={severity}
                  className={`severity-filter-button ${severity} ${severityFilter === severity ? "selected" : ""}`}
                  aria-pressed={severityFilter === severity}
                  onClick={() => setSeverityFilter((current) => current === severity ? null : severity)}
                >
                  {severity[0].toUpperCase() + severity.slice(1)}
                  <span>{severityCounts[severity]}</span>
                </button>
              ))}
            </div>}
            {activeFilter === "documents" ? (
              workspaceBusy ? <div className="simple-empty">Loading documents…</div>
                : documents.length === 0 ? <div className="simple-empty"><FileText size={22} /><strong>No documents uploaded</strong><span>Upload a circular to build your repository.</span></div>
                  : <div className="simple-upload-list">{documents.map((item) => <div className="simple-upload-row" key={item.document_version_id}>
                      <span className="simple-file-icon"><FileText size={17} /></span>
                      <div><strong>{item.publication.title}</strong><small>{item.filename}</small></div>
                      <time>{formatDate(item.created_at)}</time>
                    </div>)}</div>
            ) : workspaceBusy ? <div className="simple-empty">Loading findings…</div>
              : visibleFindings.length === 0 ? (
                <div className="simple-empty">
                  <ShieldCheck size={22} />
                  <strong>{activeFilter === "compliant" ? "No items marked compliant" : severityFilter ? `No ${severityFilter} severity findings` : "Nothing to review"}</strong>
                  <span>{activeFilter === "actions" ? (severityFilter ? "Try another severity filter or clear the selected filter." : "Upload a circular to generate recommended actions.") : "Your results will appear here when available."}</span>
                </div>
              ) : <div className="simple-action-list">{visibleFindings.slice().sort((a, b) => {
                  const rank = (item: ChangeItem) => item.compliance_status === "compliant" ? 3 : getRiskTone(item) === "red" ? 0 : 1;
                  return rank(a) - rank(b) || (b.confidence ?? 0) - (a.confidence ?? 0);
                }).map((item) => {
                  const tone = getRiskTone(item);
                  const actionText = item.actions?.[0] ?? item.impact ?? "Review the updated regulatory requirement.";
                  return <article className={`simple-action-card ${tone}`} key={item.id}>
                    <div className="simple-action-main">
                      <span className={`risk-chip ${tone}`}>{riskLabel(item)}</span>
                      <h3>{item.publication}</h3>
                      <p>{actionText}</p>
                      <div className="simple-action-meta">
                        <span>{item.classification}</span><span>{getSeverity(item)} severity</span>
                        <span>Confidence: {item.confidence == null ? "Not scored" : `${Math.round(item.confidence * 100)}%`}</span>
                      </div>
                    </div>
                    <button className={`compliance-toggle ${item.compliance_status === "compliant" ? "is-compliant" : ""}`}
                      disabled={updatingFinding === item.id}
                      onClick={() => void handleComplianceStatus(item)}>
                      {updatingFinding === item.id ? "Saving…" : item.compliance_status === "compliant" ? "Reopen" : "Mark compliant"}
                    </button>
                  </article>;
                })}</div>}
          </section>
        </>}

        {page === "Documents" && <>
          <div className="simple-page-heading">
            <div><div className="eyebrow">DOCUMENT REPOSITORY</div><h1>Documents</h1><p>{documentCount} saved uploads in your account.</p></div>
            <span className="upload-count-pill"><FileText size={15} />{documentCount} uploaded</span>
          </div>
          <DocumentIntake analysis={latestAnalysis} onAnalyzed={handleDocumentAnalyzed} />
        </>}
        <footer className="footer simple-footer"><span>© 2026 ReguLensAI</span><span>Private workspace · Human-reviewed compliance status</span></footer>
      </div>
    </main>
  </div>;
}
