from datetime import datetime

from pydantic import BaseModel, Field


class Stat(BaseModel):
    label: str
    value: int
    detail: str


class LoginRequest(BaseModel):
    user_id: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class LoginResponse(BaseModel):
    user_id: str
    display_name: str
    department: str
    roles: list[str]
    must_change_password: bool
    auth_mode: str = "mvp-user-id"


class Dashboard(BaseModel):
    project_name: str
    generated_from: str
    stats: list[Stat]
    pending_by_area: list[dict[str, object]]
    critical_items: list[dict[str, object]]
    guardrail: str
    data_scope: str = "운영 자료만"
    demo_source_count: int = 0


class ReviewItem(BaseModel):
    id: str
    priority: int | None = None
    discipline: str | None = None
    drawing_sheet: str | None = None
    title: str
    severity: str
    status: str
    owner_department: str
    recommended_action: str
    evidence: str | None = None
    confidence: str | None = None
    rule: str | None = None


class RuleRunResult(BaseModel):
    processed: int
    by_result: dict[str, int]
    items: list[ReviewItem]
    notice: str
    quantity_checks: list[dict[str, object]] = Field(default_factory=list)
    warnings: list[dict[str, object]] = Field(default_factory=list)
    drawing_comparisons: list[dict[str, object]] = Field(default_factory=list)
    mapping_candidates: list[dict[str, object]] = Field(default_factory=list)
    price_candidates: list[dict[str, object]] = Field(default_factory=list)
    persisted: bool = False
    persisted_project_id: str | None = None


class PriceCandidate(BaseModel):
    id: str
    standard_key: str
    category: str
    status: str
    route: str
    api_status: str | None = None
    restriction: str


class DecisionRequest(BaseModel):
    department: str = Field(pattern="^(공사부서|설계부서|구매부서)$")
    decision: str = Field(pattern="^(승인|수정 요청|반려|추가 확인 필요|오탐)$")
    comment: str = Field(min_length=1, max_length=2000)
    reviewer: str = Field(min_length=1, max_length=100)
    evidence_ref: str | None = Field(default=None, max_length=3000)
    override_sequence: bool = False
    override_reason: str | None = Field(default=None, max_length=2000)


class DecisionResponse(BaseModel):
    id: str
    source_id: str
    department: str
    decision: str
    comment: str
    reviewer: str
    override_sequence: bool = False
    override_reason: str | None = None
    created_at: datetime | None = None


class BatchDecisionRequest(BaseModel):
    source_ids: list[str] = Field(min_length=1, max_length=200)
    department: str = Field(pattern="^(공사부서|설계부서|구매부서)$")
    decision: str = Field(pattern="^(승인|수정 요청|반려|추가 확인 필요|오탐)$")
    comment: str = Field(min_length=1, max_length=2000)
    reviewer: str = Field(min_length=1, max_length=100)
    evidence_ref: str | None = Field(default=None, max_length=3000)
    override_sequence: bool = False
    override_reason: str | None = Field(default=None, max_length=2000)


class BatchDecisionItemResponse(BaseModel):
    source_id: str
    status: str
    decision_id: str | None = None
    error_message: str | None = None


class BatchDecisionResponse(BaseModel):
    project_id: str
    department: str
    decision: str
    requested_count: int
    succeeded_count: int
    failed_count: int
    items: list[BatchDecisionItemResponse]


class ProjectSummary(BaseModel):
    id: str
    project_code: str
    name: str
    site: str | None = None
    status: str
    base_date: datetime | None = None


class ScopeOption(BaseModel):
    id: str
    name: str
    code: str | None = None
    building_id: str | None = None


class ProjectScopeResponse(BaseModel):
    project: ProjectSummary
    buildings: list[ScopeOption] = Field(default_factory=list)
    work_packages: list[ScopeOption] = Field(default_factory=list)


class ProjectStatus(BaseModel):
    project: ProjectSummary
    warnings: int
    drawing_candidates: int
    mapping_candidates: int
    quantity_checks: int
    price_candidates: int
    approvals: int
    pending_approvals: int
    last_rule_job: str | None = None


class PreprocessingStatus(BaseModel):
    project_id: str
    generated_from: str
    areas: list[dict[str, object]]
    pending_total: int
    runs: list["PreprocessingRunResponse"] = Field(default_factory=list)


class QuantityAnalysisItem(BaseModel):
    id: str
    project_id: str
    source_set: str
    version: str
    discipline: str | None = None
    work_package: str | None = None
    item_key: str | None = None
    item_text: str | None = None
    source_file: str | None = None
    sheet_or_drawing: str | None = None
    source_locator: str | None = None
    baseline_source_locator: str | None = None
    changed_source_locator: str | None = None
    comparison_rate: str | None = None
    comparison_tolerance: str | None = None
    comparison_tolerance_rate: str | None = None
    comparison_band: str | None = None
    quantity_context: str | None = None
    quantity_candidates: list[dict[str, object]] = Field(default_factory=list)
    issue_type: str
    judgement: str
    severity: str
    status: str
    confidence: str | None = None
    original_value: str | None = None
    recalculated_value: str | None = None
    recalculated_basis: str | None = None
    difference: str | None = None
    evidence: str | None = None
    required_action: str | None = None
    rule_version: str = "preprocessing-v1"
    locator_status: str = "UNRESOLVED"


class QuantityCandidateSelectionRequest(BaseModel):
    quantity_item_id: str = Field(min_length=1, max_length=100)
    comment: str = Field(default="", max_length=1000)


class QuantityCandidateSelectionResponse(BaseModel):
    estimate_item_id: str
    quantity_item_id: str
    status: str
    auto_decision: str
    comment: str = ""


class QuantityAnalysisResponse(BaseModel):
    project_id: str
    scope: str
    generated_from: str
    total: int
    approval_queue_total: int = 0
    summary: dict[str, int]
    # Counts are calculated before API item pagination so filter options do
    # not depend on whichever workbook happened to occupy the first page.
    work_package_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    items: list[QuantityAnalysisItem]
    recheck_summary: list[dict[str, object]] = Field(default_factory=list)
    steel_relation_summary: list[dict[str, object]] = Field(default_factory=list)
    steel_coating_formula_summary: list[dict[str, object]] = Field(default_factory=list)
    material_construction_relation_summary: list[dict[str, object]] = Field(default_factory=list)
    baseline_changed_comparison: list[dict[str, object]] = Field(default_factory=list)


class PreprocessingRunRequest(BaseModel):
    source_file_ids: list[str] | None = Field(default=None, max_length=100)


class PreprocessingRunResponse(BaseModel):
    id: str
    project_id: str
    source_kind: str
    parser_version: str
    input_hash: str
    source_count: int
    processed_count: int
    status: str
    attempt_count: int = 0
    max_attempts: int = 5
    error_message: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class PreprocessingRecordResponse(BaseModel):
    id: str
    run_id: str
    source_file_id: str | None = None
    item_kind: str
    raw_payload: object
    normalized_payload: object
    source_locator: str | None = None
    status: str
    confidence: str
    created_at: datetime | None = None


class PriceReferenceResponse(BaseModel):
    id: str
    project_id: str
    source_file_id: str | None = None
    source_scope: str
    original_item: str | None = None
    standard_item: str | None = None
    specification: str | None = None
    unit: str | None = None
    building_label: str | None = None
    price: float | None = None
    reference_date: datetime | None = None
    provenance: str | None = None
    restriction: str | None = None
    is_active: bool
    created_at: datetime | None = None


class PriceReferenceImportResponse(BaseModel):
    project_id: str
    status: str
    imported_count: int = 0
    source_file_id: str | None = None
    source_path: str | None = None
    error_message: str | None = None


class SourceFileResponse(BaseModel):
    id: str
    project_id: str
    building_id: str | None = None
    work_package_id: str | None = None
    file_type: str
    document_type: str
    original_name: str
    file_path: str
    sha256: str | None = None
    version_type: str
    reference_date: datetime | None = None
    revision: str | None = None
    drawing_number: str | None = None
    sheet_name: str | None = None
    source_row_ref: str | None = None
    uploaded_by: str | None = None
    is_valid: bool
    deleted_at: datetime | None = None
    deleted_by: str | None = None
    delete_reason: str | None = None
    created_at: datetime | None = None
    preprocessing_run_id: str | None = None
    preprocessing_status: str | None = None
    preprocessing_error: str | None = None


class DeleteSourceFileRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=1000)


class AuditLogResponse(BaseModel):
    id: str
    user_id: str | None = None
    project_id: str | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    detail: str | None = None
    created_at: datetime | None = None


class JobResponse(BaseModel):
    id: str
    project_id: str
    status: str
    processed_count: int = 0
    error_message: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ReviewExportRequest(BaseModel):
    review_run_id: str | None = Field(default=None, max_length=100)
    building_id: str | None = Field(default=None, max_length=100)
    work_package_id: str | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, max_length=50)
    warning_severity: str | None = Field(default=None, max_length=30)


class ReviewExportResponse(BaseModel):
    id: str
    project_id: str
    requested_by: str | None = None
    review_run_id: str | None = None
    export_type: str
    filter_snapshot: dict[str, object]
    approval_snapshot: dict[str, object]
    rule_version: str | None = None
    input_hash: str | None = None
    data_as_of: datetime | None = None
    status: str
    bundle_path: str | None = None
    xlsx_path: str | None = None
    pdf_path: str | None = None
    manifest_path: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None


class PriceLookupRequest(BaseModel):
    candidate_id: str | None = Field(default=None, min_length=1, max_length=100)
    item_name: str = Field(min_length=1, max_length=500)
    specification: str | None = Field(default=None, max_length=2000)
    unit: str | None = Field(default=None, max_length=30)
    query_text: str | None = Field(default=None, max_length=1000)


class PriceLookupResponse(BaseModel):
    id: str
    project_id: str
    candidate_id: str
    lookup_status: str
    item_name: str | None = None
    specification: str | None = None
    unit: str | None = None
    price: float | None = None
    service_name: str
    source_file_id: str | None = None
    reference_date: datetime | None = None
    created_at: datetime | None = None
    # 신규내역 후보의 원천·수량 문맥. 기존 API 조회 결과에는 없을 수 있다.
    source_set: str | None = None
    work_package: str | None = None
    baseline_quantity: str | None = None
    changed_quantity: str | None = None
    difference: str | None = None
    evidence: str | None = None
    reference_match_count: int = 0
    best_reference_price: float | None = None
    best_reference_scope: str | None = None
    reference_match_status: str = "참고단가 미확인"


class PriceDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(미검토|적용 후보|적용 예정|적용 보류|반려)$")
    reason: str = Field(min_length=1, max_length=2000)
    applied_price: float | None = Field(default=None, ge=0)
    evidence_ref: str | None = Field(default=None, max_length=3000)


class PriceDecisionResponse(BaseModel):
    id: str
    project_id: str
    standardized_item_id: str | None = None
    price_result_id: str | None = None
    price_type: str
    applied_price: float | None = None
    decision: str
    reason: str | None = None
    approved_by: str | None = None
    evidence_ref: str | None = None
    created_at: datetime | None = None


class ReviewWarningResponse(BaseModel):
    id: str
    project_id: str
    warning_type: str
    severity: str
    title: str
    detail: str | None = None
    expected_value: str | None = None
    actual_value: str | None = None
    status: str
    rule_code: str | None = None
    created_at: datetime | None = None


class DrawingCandidateResponse(BaseModel):
    id: str
    project_id: str
    discipline: str | None = None
    drawing_number: str | None = None
    candidate_text: str | None = None
    change_type: str
    location_ref: str | None = None
    confidence: str | None = None
    status: str
    source_row_ref: str | None = None
    baseline_file: str | None = None
    changed_file: str | None = None
    baseline_revision: str | None = None
    changed_revision: str | None = None
    sheet_number: str | None = None
    next_action: str | None = None
    linked_estimate_count: int = 0
    linked_estimate_names: list[str] = []
    link_status: str = "연결 근거 없음"


class EvidenceResponse(BaseModel):
    id: str
    project_id: str
    mapping_candidate_id: str | None = None
    warning_id: str | None = None
    source_file_id: str | None = None
    evidence_type: str
    file_path: str | None = None
    sheet_name: str | None = None
    row_ref: str | None = None
    cell_ref: str | None = None
    page_number: int | None = None
    object_id: str | None = None
    location_text: str | None = None
    extraction_confidence: str | None = None
    evidence_note: str | None = None


class MappingCandidateResponse(BaseModel):
    id: str
    project_id: str
    candidate_key: str | None = None
    match_method: str | None = None
    confidence: str | None = None
    status: str
    source_candidate_count: int | None = None
    auto_decision: str | None = None


PreprocessingStatus.model_rebuild()
