import type { ChangeItem, DocumentAnalysis, DocumentRecord, GeminiDiagnostics, MonitoredSource, Overview, Publication, Source, SourceCrawlResult } from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const BROWSER_HEADER = { "X-ReguLens-Request": "browser" };

export interface AuthUser {
  id: string;
  email: string;
  name: string | null;
  picture: string | null;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (method !== "GET" && method !== "HEAD") {
    headers.set("X-ReguLens-Request", "browser");
  }
  const response = await fetch(`${API_BASE}/api/v1${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = typeof payload.detail === "string" ? payload.detail : `API request failed (${response.status}) for ${path}`;
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

async function listDocuments(): Promise<{ items: DocumentRecord[]; total: number; persistence_available: boolean; access_enabled?: boolean; message?: string }> {
  return request<{ items: DocumentRecord[]; total: number; persistence_available: boolean; access_enabled?: boolean; message?: string }>("/documents");
}

async function documentDetail(documentVersionId: string): Promise<DocumentAnalysis> {
  return request<DocumentAnalysis>(`/documents/${encodeURIComponent(documentVersionId)}`);
}

async function analyzeDocument(file: File): Promise<DocumentAnalysis> {
  const body = new FormData();
  body.append("file", file);
  return request<DocumentAnalysis>("/documents/analyze", { method: "POST", headers: BROWSER_HEADER, body });
}

async function googleLogin(credential: string): Promise<{ user: AuthUser; expires_in: number }> {
  return request<{ user: AuthUser; expires_in: number }>("/auth/google", {
    method: "POST",
    headers: { ...BROWSER_HEADER, "Content-Type": "application/json" },
    body: JSON.stringify({ credential }),
  });
}

export const api = {
  overview: () => request<Overview>("/overview"),
  publications: () => request<{ items: Publication[]; total: number }>("/publications"),
  changes: () => request<{ items: ChangeItem[]; total: number }>("/changes"),
  updateFindingStatus: (findingId: string, status: "open" | "in_progress" | "compliant") =>
    request<{ id: string; compliance_status: string }>(`/findings/${encodeURIComponent(findingId)}/status`, {
      method: "PATCH",
      headers: { ...BROWSER_HEADER, "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    }),
  sources: () => request<{ items: Source[]; total: number }>("/sources"),
  listSourceMonitors: () => request<{ items: MonitoredSource[]; total: number }>("/source-monitors"),
  createSourceMonitor: (payload: { name: string; url: string; source_kind: "rbi_notifications" | "custom"; poll_interval_minutes: number }) => request<MonitoredSource>("/source-monitors", { method: "POST", headers: { ...BROWSER_HEADER, "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
  crawlSourceMonitor: (id: string) => request<SourceCrawlResult>("/source-monitors/" + encodeURIComponent(id) + "/crawl", { method: "POST", headers: BROWSER_HEADER }),
  updateSourceMonitor: (id: string, payload: { enabled?: boolean; poll_interval_minutes?: number }) => request<MonitoredSource>("/source-monitors/" + encodeURIComponent(id), { method: "PATCH", headers: { ...BROWSER_HEADER, "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
  deleteSourceMonitor: (id: string) => request<{ success: boolean }>("/source-monitors/" + encodeURIComponent(id), { method: "DELETE", headers: BROWSER_HEADER }),
  geminiDiagnostics: () => request<GeminiDiagnostics>("/diagnostics/gemini"),
  listDocuments,
  documentDetail,
  analyzeDocument,
  currentUser: () => request<{ user: AuthUser }>("/auth/me"),
  oauthNonce: () => request<{ nonce: string }>("/auth/nonce", { method: "POST", headers: BROWSER_HEADER }),
  googleLogin,
  logout: () => request<{ success: boolean }>("/auth/logout", { method: "POST", headers: BROWSER_HEADER }),
  listInternalAssets: () => request<{ items: any[]; total: number }>("/internal-assets"),
  createInternalAsset: (payload: Record<string, unknown>) => request<any>("/internal-assets", { method: "POST", headers: { ...BROWSER_HEADER, "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
  updateInternalAsset: (id: string, payload: Record<string, unknown>) => request<any>("/internal-assets/" + encodeURIComponent(id), { method: "PATCH", headers: { ...BROWSER_HEADER, "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
  deleteInternalAsset: (id: string) => request<{ success: boolean }>("/internal-assets/" + encodeURIComponent(id), { method: "DELETE", headers: BROWSER_HEADER }),
  listImpactAssessments: () => request<{ items: any[]; total: number }>("/impact-assessments"),
  runImpactAssessment: (documentVersionId: string) => request<any>("/documents/" + encodeURIComponent(documentVersionId) + "/impact-assessments", { method: "POST", headers: BROWSER_HEADER }),
  impactAssessment: (id: string) => request<any>("/impact-assessments/" + encodeURIComponent(id)),
  reviewImpactMapping: (id: string, payload: Record<string, unknown>) => request<any>("/impact-mappings/" + encodeURIComponent(id), { method: "PATCH", headers: { ...BROWSER_HEADER, "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
  reviewRecommendation: (id: string, payload: Record<string, unknown>) => request<any>("/recommendations/" + encodeURIComponent(id), { method: "PATCH", headers: { ...BROWSER_HEADER, "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
  listRemediationActions: () => request<{ items: any[]; total: number }>("/remediation-actions"),
  createRemediationAction: (payload: Record<string, unknown>) => request<any>("/remediation-actions", { method: "POST", headers: { ...BROWSER_HEADER, "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
  updateRemediationAction: (id: string, payload: Record<string, unknown>) => request<any>("/remediation-actions/" + encodeURIComponent(id), { method: "PATCH", headers: { ...BROWSER_HEADER, "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
};
