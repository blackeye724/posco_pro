const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
export const USER_ID = process.env.NEXT_PUBLIC_USER_ID ?? "pfc391";
export const PROJECT_ID = process.env.NEXT_PUBLIC_PROJECT_ID ?? "project-g5-office";
export const currentUserId = () => (typeof window !== "undefined" ? window.localStorage.getItem("mvp_user_id") || USER_ID : USER_ID);
const authHeaders = () => ({ "X-User-Id": currentUserId() });

export type Dashboard = { project_name: string; generated_from: string; guardrail: string; stats: { label: string; value: number; detail: string }[]; pending_by_area: Record<string, string | number>[]; critical_items: Record<string, string>[] };
export type ReviewItem = { id: string; priority?: number; discipline?: string; drawing_sheet?: string; title: string; severity: string; status: string; owner_department: string; recommended_action: string; evidence?: string; confidence?: string; rule?: string };
export type PriceCandidate = { id: string; standard_key: string; category: string; status: string; route: string; api_status?: string; restriction: string };
export type JobResponse = { id: string; project_id: string; status: string; processed_count: number; error_message?: string };
export type ReviewExport = { id: string; project_id: string; requested_by?: string; review_run_id?: string; export_type: string; filter_snapshot: Record<string, unknown>; approval_snapshot: Record<string, unknown>; rule_version?: string; input_hash?: string; data_as_of?: string; status: string; bundle_path?: string; xlsx_path?: string; pdf_path?: string; manifest_path?: string; error_message?: string; created_at?: string };
export type ProjectSummary = { id: string; project_code: string; name: string; site?: string; status: string; base_date?: string };
export type ProjectStatus = { project: ProjectSummary; warnings: number; drawing_candidates: number; mapping_candidates: number; quantity_checks: number; price_candidates: number; approvals: number; pending_approvals: number; last_rule_job?: string };
export type PreprocessingStatus = { project_id: string; generated_from: string; areas: Record<string, string | number>[]; pending_total: number; runs?: PreprocessingRun[] };
export type PreprocessingRun = { id: string; project_id: string; source_kind: string; parser_version: string; input_hash: string; source_count: number; processed_count: number; status: string; error_message?: string; created_at?: string; started_at?: string; finished_at?: string };
export type PreprocessingRecord = { id: string; run_id: string; source_file_id?: string; item_kind: string; raw_payload: unknown; normalized_payload: unknown; source_locator?: string; status: string; confidence: string; created_at?: string };
export type Warning = { id: string; project_id: string; warning_type: string; severity: string; title: string; detail?: string; expected_value?: string; actual_value?: string; status: string; rule_code?: string };
export type DrawingCandidate = { id: string; project_id: string; discipline?: string; drawing_number?: string; candidate_text?: string; change_type: string; location_ref?: string; confidence?: string; status: string; source_row_ref?: string; baseline_file?: string; changed_file?: string; baseline_revision?: string; changed_revision?: string; sheet_number?: string };
export type MappingCandidate = { id: string; project_id: string; candidate_key?: string; match_method?: string; confidence?: string; status: string; source_candidate_count?: number; auto_decision?: string };
export type Evidence = { id: string; project_id: string; mapping_candidate_id?: string; warning_id?: string; source_file_id?: string; evidence_type: string; file_path?: string; sheet_name?: string; row_ref?: string; cell_ref?: string; page_number?: number; object_id?: string; location_text?: string; extraction_confidence?: string; evidence_note?: string };
export type PriceResult = { id: string; project_id: string; candidate_id: string; service_name: string; item_name?: string; specification?: string; unit?: string; lookup_status: string; price?: number; source_file_id?: string; reference_date?: string; created_at?: string };
export type PriceReference = { id: string; project_id: string; source_file_id?: string; source_scope: string; original_item?: string; standard_item?: string; specification?: string; unit?: string; building_label?: string; price?: number; reference_date?: string; provenance?: string; restriction?: string; is_active: boolean; created_at?: string };
export type Approval = { id: string; project_id?: string; source_id: string; department: string; decision: string; comment: string; reviewer: string; reviewer_user_id?: string; evidence_ref?: string; created_at?: string };
export type SourceFile = { id: string; project_id: string; file_type: string; document_type: string; original_name: string; file_path: string; sha256?: string; version_type: string; revision?: string; drawing_number?: string; sheet_name?: string; source_row_ref?: string; uploaded_by?: string; is_valid: boolean; preprocessing_run_id?: string; preprocessing_status?: string; preprocessing_error?: string; created_at?: string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("X-User-Id")) headers.set("X-User-Id", currentUserId());
  if (!(init?.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

export const fetchDashboard = () => request<Dashboard>(`/dashboard?project_id=${PROJECT_ID}`);
export const fetchReviews = (limit: number) => request<Warning[]>(`/projects/${PROJECT_ID}/warnings?limit=${limit}`).then(rows => rows.map(row => ({ id: row.id, title: row.title, severity: row.severity, status: row.status, owner_department: "공사부서", recommended_action: "근거 확인", evidence: row.detail, confidence: "중간", rule: row.rule_code })));
export const fetchPrices = () => request<PriceCandidate[]>("/prices");
export const runRules = () => request<JobResponse>(`/projects/${PROJECT_ID}/rules/run`, { method: "POST", headers: authHeaders() });
export const fetchJob = (jobId: string) => request<JobResponse>(`/jobs/${jobId}`);
export const createDecision = (sourceId: string, body: { department: string; decision: string; reviewer: string; comment: string }) => request(`/reviews/${sourceId}/decisions`, { method: "POST", headers: authHeaders(), body: JSON.stringify(body) });

export const fetchProjects = () => request<ProjectSummary[]>("/projects");
export const fetchProjectStatus = (projectId = PROJECT_ID) => request<ProjectStatus>(`/projects/${projectId}`);
export const fetchPreprocessing = (projectId = PROJECT_ID) => request<PreprocessingStatus>(`/projects/${projectId}/preprocessing`);
export const fetchPreprocessingRecords = (runId: string, projectId = PROJECT_ID, params = "") => request<PreprocessingRecord[]>(`/projects/${projectId}/preprocessing/runs/${encodeURIComponent(runId)}/records${params ? `?${params}` : ""}`);
export const startPreprocessing = (projectId = PROJECT_ID, source_file_ids?: string[]) => request<PreprocessingRun>(`/projects/${projectId}/preprocessing/run`, { method: "POST", headers: authHeaders(), body: JSON.stringify(source_file_ids ? { source_file_ids } : {}) });
export const retryPreprocessing = (projectId = PROJECT_ID, runId: string) => request<PreprocessingRun>(`/projects/${projectId}/preprocessing/${runId}/retry`, { method: "POST", headers: authHeaders() });
export const fetchWarnings = (projectId = PROJECT_ID, limit = 100) => request<Warning[]>(`/projects/${projectId}/warnings?limit=${limit}`);
export const fetchDrawings = (projectId = PROJECT_ID, limit = 100) => request<DrawingCandidate[]>(`/projects/${projectId}/drawings/changes?limit=${limit}`);
export const fetchQuantities = (projectId = PROJECT_ID) => request<Warning[]>(`/projects/${projectId}/quantities`);
export const fetchMappings = (projectId = PROJECT_ID) => request<MappingCandidate[]>(`/projects/${projectId}/mappings`);
export const fetchPriceResults = (projectId = PROJECT_ID) => request<PriceResult[]>(`/projects/${projectId}/prices/results`);
export const fetchPriceReferences = (projectId = PROJECT_ID, query = "", includeOtherProjects = true) => { const params = new URLSearchParams(); if (query) params.set("q", query); params.set("include_other_projects", String(includeOtherProjects)); return request<PriceReference[]>(`/projects/${projectId}/price-references?${params.toString()}`); };
export const importPriceReferences = (projectId = PROJECT_ID) => request<{ project_id: string; status: string; imported_count: number; source_file_id?: string; source_path?: string; error_message?: string }>(`/admin/projects/${projectId}/price-references/import`, { method: "POST", headers: authHeaders() });
export const fetchEvidence = (projectId = PROJECT_ID, params = "") => request<Evidence[]>(`/projects/${projectId}/evidence${params ? `?${params}` : ""}`);
export const fetchHistory = (projectId = PROJECT_ID) => request<Approval[]>(`/projects/${projectId}/review-history`);
export const enqueueRules = (projectId = PROJECT_ID) => request<JobResponse>(`/projects/${projectId}/rules/run`, { method: "POST", headers: authHeaders() });
export const createApproval = (projectId: string, sourceId: string, body: { department: string; decision: string; reviewer: string; comment: string }) => request<Approval>(`/projects/${projectId}/reviews/${encodeURIComponent(sourceId)}/approvals`, { method: "POST", headers: authHeaders(), body: JSON.stringify(body) });
export type BatchDecisionResponse = { project_id: string; department: string; decision: string; requested_count: number; succeeded_count: number; failed_count: number; items: { source_id: string; status: string; decision_id?: string; error_message?: string }[] };
export const createBatchApproval = (projectId: string, body: { source_ids: string[]; department: string; decision: string; reviewer: string; comment: string }) => request<BatchDecisionResponse>(`/projects/${projectId}/reviews/approvals/batch`, { method: "POST", headers: authHeaders(), body: JSON.stringify(body) });
export const createReviewExport = (projectId = PROJECT_ID, body: { review_run_id?: string; building_id?: string; work_package_id?: string; status?: string; warning_severity?: string } = {}) => request<ReviewExport>(`/projects/${projectId}/reports`, { method: "POST", headers: authHeaders(), body: JSON.stringify(body) });
export const fetchReviewExport = (projectId: string, exportId: string) => request<ReviewExport>(`/projects/${projectId}/reports/${encodeURIComponent(exportId)}`);
export const requestPriceLookup = (projectId: string, body: { candidate_id?: string; item_name: string; specification?: string; unit?: string; query_text?: string }) => request<PriceResult>(`/projects/${projectId}/prices/query`, { method: "POST", headers: authHeaders(), body: JSON.stringify(body) });
export const savePriceDecision = (projectId: string, resultId: string, body: { decision: "적용 예정" | "적용 보류" | "반려"; reason: string; applied_price?: number; evidence_ref?: string }) => request<PriceDecision>(`/projects/${projectId}/prices/${resultId}/decision`, { method: "POST", headers: authHeaders(), body: JSON.stringify(body) });
export type PriceDecision = { id: string; project_id: string; price_result_id?: string; decision: string; applied_price?: number; reason?: string; approved_by?: string; evidence_ref?: string; created_at?: string };
export const fetchProjectFiles = (projectId = PROJECT_ID) => request<SourceFile[]>(`/projects/${projectId}/files`);
export const uploadProjectFile = (projectId: string, file: File, metadata: { document_type?: string; version_type?: string; revision?: string; drawing_number?: string; sheet_name?: string; source_row_ref?: string } = {}) => { const form = new FormData(); form.append("file", file); Object.entries(metadata).forEach(([key, value]) => { if (value) form.append(key, value); }); return request<SourceFile>(`/projects/${projectId}/files`, { method: "POST", headers: authHeaders(), body: form }); };
export const login = (user_id: string, password: string) => request<{ user_id: string; display_name: string; department: string; roles: string[]; must_change_password: boolean }>("/auth/login", { method: "POST", body: JSON.stringify({ user_id, password }) });
