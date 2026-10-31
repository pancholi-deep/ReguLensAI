export interface Publication {
  id: string; title: string; authority: string; country: string; area: string;
  published: string; effective: string; status: string; kind: string;
}
export interface ChangeItem {
  id: string; publication: string; country: string; classification: string;
  priority: string; previous: string; updated: string; impact: string;
  actions: string[]; source: string;
  severity?: "high" | "medium" | "low";
  confidence?: number | null;
  compliance_status?: "open" | "in_progress" | "compliant";
  evidence_verified?: boolean;
  needs_review?: boolean;
  is_demo?: boolean;
}
export interface Overview {
  total_publications: number; new_or_unreviewed: number; awaiting_review: number;
  regions_represented: number; coverage: { country: string; count: number }[];
  recent_publications: Publication[];
}
export interface Source { country: string; authority: string; region: string; status: string; }

export interface ExtractedClause {
  clause_number: string;
  heading: string;
  clause_type: string;
  text: string;
  source_reference: string;
  evidence_verified: boolean;
  extraction_method?: string;
}

export interface ExtractedReference {
  referenced_title: string;
  reference_number: string;
  relationship_type: string;
  source_reference: string;
  source_excerpt: string;
  evidence_verified: boolean;
}

export interface ExtractedObligation {
  requirement: string;
  classification: string;
  obligation_type?: string;
  applies_to: string[];
  affected_entities?: string[];
  departments?: string[];
  deadline: string;
  clause_number?: string;
  source_reference: string;
  source_excerpt: string;
  evidence_verified: boolean;
}

export interface RepositoryChangeFinding {
  id: string;
  classification: string;
  previous_clause_number: string | null;
  updated_clause_number: string | null;
  previous_text: string | null;
  updated_text: string | null;
  previous_source_reference: string | null;
  updated_source_reference: string | null;
  change_summary: string;
  why_it_matters: string;
  affected_business_areas: string[];
  affected_departments: string[];
  recommended_actions: string[];
  previous_deadline: string | null;
  updated_deadline: string | null;
  confidence: number;
  evidence_verified: boolean;
  needs_review: boolean;
}

export interface HistoricalComparison {
  id: string;
  historical_document_version_id: string;
  historical_publication_id: string | null;
  historical_title: string;
  historical_reference_number: string | null;
  relationship_type: string;
  match_confidence: number;
  matching_method: string;
  match_evidence: Record<string, unknown>;
  analysis_method: string;
  status: string;
  summary: string;
  findings: RepositoryChangeFinding[];
  finding_count: number;
}

export interface RepositoryComparisonSummary {
  status: "compared" | "no_history" | "no_relevant_match" | "not_compared" | "failed" | string;
  documents_considered: number | null;
  documents_matched: number;
  finding_count?: number;
  classification_counts?: Record<string, number>;
  comparisons: HistoricalComparison[];
  message?: string;
}
export interface GeminiDiagnostics {
  configured: boolean;
  model: string;
  key_source: string;
  local_env_files_found: string[];
}
export interface DocumentPersistence {
  persisted: boolean;
  duplicate: boolean;
  publication_id: string;
  document_version_id: string;
  sha256: string;
  stored_sections?: number;
  stored_obligations?: number;
  stored_clauses?: number;
  stored_references?: number;
  linked_obligations?: number;
  original_file_stored?: boolean;
}

export interface DocumentRecord {
  document_version_id: string;
  publication_id: string;
  filename: string;
  sha256: string;
  extraction_status: string;
  extraction_method: string;
  created_at: string | null;
  publication: Publication;
}

export interface DocumentAnalysis {
  persistence?: DocumentPersistence;
  comparison?: RepositoryComparisonSummary;
  publication: Publication;
  document: {
    filename: string;
    extension: string;
    size_bytes: number;
    text_characters: number;
    source_sections: number;
    sha256: string;
  };
  extraction: {
    method: string;
    gemini_status: "not_configured" | "used" | "failed";
    model: string | null;
    summary: string;
    metadata: Record<string, string>;
    clauses?: ExtractedClause[];
    clause_count?: number;
    obligations: ExtractedObligation[];
    obligation_count: number;
    references?: ExtractedReference[];
    reference_count?: number;
    note: string;
  };
}


export interface MonitoredSourceChange { title: string; url: string; status: string; document_version_id: string; finding_count: number; detected_at: string; }
export interface MonitoredSource { id: string; name: string; url: string; source_kind: 'rbi_notifications' | 'custom'; enabled: boolean; poll_interval_minutes: number; last_checked_at: string | null; last_success_at: string | null; last_error: string | null; last_changes: MonitoredSourceChange[]; created_at: string | null; }
export interface SourceCrawlResult extends MonitoredSource { documents_discovered: number; documents_ingested: number; duplicates_skipped: number; changes: MonitoredSourceChange[]; }