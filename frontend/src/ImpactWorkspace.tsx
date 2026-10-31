import { FormEvent, useEffect, useState } from "react";
import { Activity, AlertCircle, CheckCircle2, ClipboardCheck, FileText, Plus, RefreshCw, Shield, Trash2 } from "lucide-react";
import { api } from "./api";

type Mode = "repository" | "assessments" | "actions";
type Asset = { id: string; asset_type: string; name: string; description: string; content: string; department?: string; owner_name?: string; system_name?: string; criticality: string };
type Mapping = { id: string; requirement: string; source_reference: string; source_excerpt: string; evidence_verified: boolean; gap_status: string; match_score: number; rationale: string; asset: Asset | null; recommendation: { id: string; recommendation: string; draft_wording: string; priority: string; status: string } | null; actions: any[] };
type Assessment = { id: string; document_version_id: string; summary: string; created_at: string; counts?: Record<string, number>; mappings?: Mapping[] };

const emptyAsset = { asset_type: "policy", name: "", description: "", content: "", department: "", owner_name: "", system_name: "", criticality: "medium" };

export default function ImpactWorkspace({ mode }: { mode: Mode }) {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [documents, setDocuments] = useState<any[]>([]);
  const [assessments, setAssessments] = useState<Assessment[]>([]);
  const [actions, setActions] = useState<any[]>([]);
  const [selectedAssessment, setSelectedAssessment] = useState<Assessment | null>(null);
  const [assetForm, setAssetForm] = useState(emptyAsset);
  const [actionForm, setActionForm] = useState({ impact_mapping_id: "", recommendation_id: "", title: "", description: "", owner_name: "", department: "", due_date: "", priority: "medium" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    setBusy(true); setError("");
    try {
      const [assetResult, docResult, assessmentResult, actionResult] = await Promise.all([
        api.listInternalAssets(), api.listDocuments(), api.listImpactAssessments(), api.listRemediationActions(),
      ]);
      setAssets(assetResult.items); setDocuments(docResult.items);
      setAssessments(assessmentResult.items); setActions(actionResult.items);
      if (selectedAssessment) {
        const fresh = await api.impactAssessment(selectedAssessment.id);
        setSelectedAssessment(fresh);
      }
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to load L2 workspace."); }
    finally { setBusy(false); }
  }

  useEffect(() => { void load(); }, []);

  async function submitAsset(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      await api.createInternalAsset(assetForm);
      setAssetForm(emptyAsset); setMessage("Internal evidence added to your repository."); await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to save internal evidence."); }
    finally { setBusy(false); }
  }

  async function runAssessment(documentVersionId: string) {
    if (!documentVersionId) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await api.runImpactAssessment(documentVersionId);
      setSelectedAssessment(result); setMessage("Impact assessment completed. Review every suggested match before relying on it.");
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to run impact assessment."); }
    finally { setBusy(false); }
  }

  async function updateMapping(mapping: Mapping, gap_status: string) {
    try {
      await api.reviewImpactMapping(mapping.id, { gap_status });
      if (selectedAssessment) setSelectedAssessment(await api.impactAssessment(selectedAssessment.id));
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to update mapping."); }
  }

  async function approveRecommendation(mapping: Mapping) {
    if (!mapping.recommendation) return;
    try {
      await api.reviewRecommendation(mapping.recommendation.id, { status: "approved" });
      if (selectedAssessment) setSelectedAssessment(await api.impactAssessment(selectedAssessment.id));
      setMessage("Recommendation approved by reviewer.");
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to approve recommendation."); }
  }

  async function createAction(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      await api.createRemediationAction(actionForm);
      setActionForm({ impact_mapping_id: "", recommendation_id: "", title: "", description: "", owner_name: "", department: "", due_date: "", priority: "medium" });
      setMessage("Remediation action created."); await load();
      if (selectedAssessment) setSelectedAssessment(await api.impactAssessment(selectedAssessment.id));
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to create action."); }
    finally { setBusy(false); }
  }

  async function updateAction(id: string, payload: Record<string, unknown>) {
    try { await api.updateRemediationAction(id, payload); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to update action."); }
  }

  const title = mode === "repository" ? "Internal repository" : mode === "assessments" ? "Impact assessments" : "Remediation actions";
  const subtitle = mode === "repository"
    ? "Bring policies, procedures, controls, systems and accountable owners into one evidence repository."
    : mode === "assessments"
      ? "Map extracted regulatory obligations to internal evidence, identify gaps and review recommended changes."
      : "Assign owners, due dates and priorities to remediation work, then track delivery.";

  return <div className="impact-workspace">
    <div className="simple-page-heading">
      <div><div className="eyebrow">L2 · REGULATORY CHANGE IMPACT</div><h1>{title}</h1><p>{subtitle}</p></div>
      <button className="button secondary" onClick={() => void load()} disabled={busy}><RefreshCw size={14} /> Refresh</button>
    </div>
    {error && <div className="source-error-banner"><AlertCircle size={15} /> {error}</div>}
    {message && <div className="source-message"><CheckCircle2 size={15} /> {message}</div>}

    {mode === "repository" && <>
      <div className="simple-metric-grid">
        <div className="simple-metric"><span className="simple-metric-top">Internal evidence</span><strong>{assets.length}</strong><small>Policies, controls, systems and processes</small></div>
        <div className="simple-metric"><span className="simple-metric-top">Departments represented</span><strong>{new Set(assets.map(a => a.department).filter(Boolean)).size}</strong><small>Based on assigned department metadata</small></div>
        <div className="simple-metric"><span className="simple-metric-top">Critical assets</span><strong>{assets.filter(a => a.criticality === "critical" || a.criticality === "high").length}</strong><small>High or critical importance</small></div>
      </div>
      <section className="panel">
        <div className="panel-heading"><div><h2><Plus size={16} /> Add internal evidence</h2><p>Enter searchable text and ownership metadata. Original files are not uploaded in this L2 increment.</p></div></div>
        <form className="impact-form" onSubmit={submitAsset}>
          <label>Asset type<select value={assetForm.asset_type} onChange={e => setAssetForm({...assetForm, asset_type:e.target.value})}><option value="policy">Policy</option><option value="procedure">Procedure / SOP</option><option value="control">Control</option><option value="system">System</option><option value="process">Process</option><option value="standard">Standard</option></select></label>
          <label>Name<input required maxLength={300} value={assetForm.name} onChange={e => setAssetForm({...assetForm,name:e.target.value})} placeholder="e.g. AI Model Governance Policy" /></label>
          <label>Department<input value={assetForm.department} onChange={e => setAssetForm({...assetForm,department:e.target.value})} placeholder="Risk / Compliance / Technology" /></label>
          <label>Accountable owner<input value={assetForm.owner_name} onChange={e => setAssetForm({...assetForm,owner_name:e.target.value})} placeholder="Owner or role" /></label>
          <label>Related system<input value={assetForm.system_name} onChange={e => setAssetForm({...assetForm,system_name:e.target.value})} placeholder="System / platform (optional)" /></label>
          <label>Criticality<select value={assetForm.criticality} onChange={e => setAssetForm({...assetForm,criticality:e.target.value})}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select></label>
          <label className="wide">Description<textarea rows={2} value={assetForm.description} onChange={e => setAssetForm({...assetForm,description:e.target.value})} placeholder="Purpose, scope and applicability" /></label>
          <label className="wide">Policy / control text<textarea rows={5} value={assetForm.content} onChange={e => setAssetForm({...assetForm,content:e.target.value})} placeholder="Paste relevant clauses, control steps, evidence requirements or system responsibilities" /></label>
          <div className="wide impact-form-actions"><span>Keep content focused on the clauses and controls that demonstrate coverage.</span><button className="button primary" disabled={busy || !assetForm.name.trim()}><Plus size={14} /> Add to repository</button></div>
        </form>
      </section>
      <section className="panel">
        <div className="panel-heading"><div><h2>Repository inventory</h2><p>{assets.length} internal evidence items available for obligation mapping.</p></div></div>
        {assets.length === 0 ? <div className="simple-empty"><Shield size={22}/><strong>Your internal repository is empty</strong><span>Add policies, controls, systems and SOPs to enable L2 gap assessment.</span></div> :
          <div className="impact-asset-list">{assets.map(asset => <article className="impact-asset" key={asset.id}>
            <div className="impact-asset-icon"><FileText size={18}/></div><div className="impact-asset-main"><div className="impact-asset-title"><strong>{asset.name}</strong><span className="pill neutral">{asset.asset_type}</span><span className={"pill " + (asset.criticality === "critical" || asset.criticality === "high" ? "amber" : "neutral")}>{asset.criticality}</span></div>
              <p>{asset.description || asset.content.slice(0,220) || "No description supplied."}</p><small>{[asset.department, asset.owner_name && "Owner: " + asset.owner_name, asset.system_name && "System: " + asset.system_name].filter(Boolean).join(" · ") || "Ownership not assigned"}</small>
            </div><button className="icon-button" title="Delete internal asset" onClick={async()=>{if(confirm("Delete this internal evidence item?")){await api.deleteInternalAsset(asset.id);await load();}}}><Trash2 size={15}/></button>
          </article>)}</div>}
      </section>
    </>}

    {mode === "assessments" && <>
      <section className="panel">
        <div className="panel-heading"><div><h2><Activity size={16}/> Start an impact assessment</h2><p>Select an uploaded regulatory document. The assessment uses its extracted obligations.</p></div></div>
        <div className="impact-run-row"><select id="impact-document-select" defaultValue=""><option value="">Choose a saved regulatory document…</option>{documents.map(doc=><option key={doc.document_version_id} value={doc.document_version_id}>{doc.publication.title} · {doc.filename}</option>)}</select>
          <button className="button primary" disabled={busy || documents.length===0} onClick={()=>{const el=document.getElementById("impact-document-select") as HTMLSelectElement|null;if(el?.value)void runAssessment(el.value);}}>Run assessment <ClipboardCheck size={14}/></button></div>
        {assets.length===0 && <p className="impact-warning"><AlertCircle size={14}/> Add internal policies and controls first. Without them, obligations will be marked unassessable.</p>}
      </section>
      <section className="panel">
        <div className="panel-heading"><div><h2>Assessment history</h2><p>Open an assessment to inspect evidence, gaps and recommendations.</p></div></div>
        {assessments.length===0 ? <div className="simple-empty"><ClipboardCheck size={22}/><strong>No assessments yet</strong><span>Upload a regulatory document and run an impact assessment.</span></div> :
          <div className="impact-asset-list">{assessments.map(item=><button className="impact-assessment-row" key={item.id} onClick={async()=>setSelectedAssessment(await api.impactAssessment(item.id))}>
            <div><strong>Impact assessment · {item.id.slice(0,8)}</strong><small>{item.summary}</small></div><span>{new Date(item.created_at).toLocaleDateString()}</span>
          </button>)}</div>}
      </section>
      {selectedAssessment && <section className="panel">
        <div className="panel-heading"><div><h2>Assessment results</h2><p>{selectedAssessment.summary}</p></div><span className="pill neutral">{selectedAssessment.mappings?.length ?? 0} obligations</span></div>
        <div className="impact-gap-grid">{Object.entries(selectedAssessment.counts ?? {}).map(([key,value])=><div key={key}><strong>{value}</strong><small>{key.replace(/_/g," ")}</small></div>)}</div>
        {(selectedAssessment.mappings ?? []).map(mapping=><article className="impact-mapping" key={mapping.id}>
          <div className="impact-mapping-head"><span className="eyebrow">OBLIGATION · {mapping.source_reference}</span><select value={mapping.gap_status} onChange={e=>void updateMapping(mapping,e.target.value)}><option value="addressed">Addressed</option><option value="partially_addressed">Partially addressed</option><option value="not_addressed">Not addressed</option><option value="unassessable">Unassessable</option></select></div>
          <p className="impact-requirement">{mapping.requirement}</p><blockquote className="evidence-quote">“{mapping.source_excerpt}”</blockquote>
          <div className="impact-match-detail"><span>Internal match: {mapping.asset?.name ?? "No matching internal asset"}</span><span>Text similarity: {(mapping.match_score*100).toFixed(0)}%</span><span>{mapping.evidence_verified ? "Source evidence matched" : "Source evidence needs review"}</span></div>
          <p className="muted">{mapping.rationale}</p>
          {mapping.recommendation && <div className="impact-recommendation"><div><strong>Recommendation · {mapping.recommendation.priority} priority</strong><p>{mapping.recommendation.recommendation}</p><pre>{mapping.recommendation.draft_wording}</pre><small>Status: {mapping.recommendation.status.replace(/_/g," ")}</small></div>
            {mapping.recommendation.status==="pending_review" && <button className="button secondary" onClick={()=>void approveRecommendation(mapping)}>Approve recommendation</button>}</div>}
          <button className="text-button" onClick={()=>setActionForm({...actionForm,impact_mapping_id:mapping.id,recommendation_id:mapping.recommendation?.id ?? "",title:mapping.recommendation?.recommendation ?? "Remediate regulatory obligation",description:mapping.requirement,department:mapping.asset?.department ?? ""})}>Create remediation action</button>
        </article>)}
      </section>}
      {actionForm.impact_mapping_id && <section className="panel"><div className="panel-heading"><div><h2>Create remediation action</h2><p>Assign an accountable person and target date.</p></div></div>
        <form className="impact-form" onSubmit={createAction}>
          <label className="wide">Action title<input required value={actionForm.title} onChange={e=>setActionForm({...actionForm,title:e.target.value})}/></label>
          <label>Owner<input value={actionForm.owner_name} onChange={e=>setActionForm({...actionForm,owner_name:e.target.value})} placeholder="Name / role"/></label>
          <label>Department<input value={actionForm.department} onChange={e=>setActionForm({...actionForm,department:e.target.value})}/></label>
          <label>Due date<input type="date" value={actionForm.due_date} onChange={e=>setActionForm({...actionForm,due_date:e.target.value})}/></label>
          <label>Priority<select value={actionForm.priority} onChange={e=>setActionForm({...actionForm,priority:e.target.value})}><option>low</option><option>medium</option><option>high</option><option>critical</option></select></label>
          <label className="wide">Description<textarea rows={3} value={actionForm.description} onChange={e=>setActionForm({...actionForm,description:e.target.value})}/></label>
          <div className="wide impact-form-actions"><button type="button" className="button secondary" onClick={()=>setActionForm({...actionForm,impact_mapping_id:""})}>Cancel</button><button className="button primary" disabled={busy}>Create action</button></div>
        </form>
      </section>}
    </>}

    {mode === "actions" && <section className="panel">
      <div className="panel-heading"><div><h2>Action register</h2><p>Track implementation status, ownership, due dates and priorities.</p></div><span className="pill neutral">{actions.length} actions</span></div>
      {actions.length===0 ? <div className="simple-empty"><CheckCircle2 size={22}/><strong>No remediation actions assigned</strong><span>Open an impact assessment and create an action from a gap or recommendation.</span></div> :
        <div className="impact-action-list">{actions.map(action=><article className="impact-action" key={action.id}>
          <div className="impact-action-copy"><span className="pill neutral">{action.priority} priority</span><strong>{action.title}</strong><p>{action.description}</p><small>{[action.owner_name || "Owner unassigned",action.department || "Department unassigned",action.due_date ? "Due "+action.due_date : "No due date"].join(" · ")}</small></div>
          <div className="impact-action-controls"><label>Status<select value={action.status} onChange={e=>void updateAction(action.id,{status:e.target.value})}><option value="open">Open</option><option value="in_progress">In progress</option><option value="blocked">Blocked</option><option value="completed">Completed</option><option value="cancelled">Cancelled</option></select></label><label>Owner<input defaultValue={action.owner_name ?? ""} onBlur={e=>void updateAction(action.id,{owner_name:e.target.value})} placeholder="Assign owner"/></label><label>Due date<input type="date" defaultValue={action.due_date ?? ""} onBlur={e=>void updateAction(action.id,{due_date:e.target.value})}/></label></div>
        </article>)}</div>}
    </section>}
    <p className="impact-disclaimer"><Shield size={14}/> AI-assisted matching is an initial triage signal only. A qualified reviewer must verify control effectiveness, legal interpretation and remediation decisions.</p>
  </div>;
}
