"""운영 메타데이터와 검토 이력을 저장하는 PostgreSQL 모델."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.sql import func

from .config import get_settings

settings = get_settings()


def normalize_database_url(value: str) -> str:
    """Use the bundled psycopg 3 driver for provider-style PostgreSQL URLs."""
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value[len("postgres://"):]
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value[len("postgresql://"):]
    return value


engine = create_engine(normalize_database_url(settings.database_url), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Department(Base, TimestampMixin):
    __tablename__ = "departments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Role(Base, TimestampMixin):
    __tablename__ = "roles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    must_change_password: Mapped[bool] = mapped_column(default=True)


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)


class Project(Base, TimestampMixin):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    site: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="검토 중")
    base_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Building(Base, TimestampMixin):
    __tablename__ = "buildings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_buildings_project_name"),)


class WorkPackage(Base, TimestampMixin):
    __tablename__ = "work_packages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    building_id: Mapped[str | None] = mapped_column(ForeignKey("buildings.id", ondelete="SET NULL"), nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(255))
    contract_amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_work_packages_project_code"),)


class SourceFile(Base, TimestampMixin):
    __tablename__ = "source_files"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    building_id: Mapped[str | None] = mapped_column(ForeignKey("buildings.id", ondelete="SET NULL"), nullable=True, index=True)
    work_package_id: Mapped[str | None] = mapped_column(ForeignKey("work_packages.id", ondelete="SET NULL"), nullable=True, index=True)
    file_type: Mapped[str] = mapped_column(String(30))
    document_type: Mapped[str] = mapped_column(String(50))
    original_name: Mapped[str] = mapped_column(String(500))
    file_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    version_type: Mapped[str] = mapped_column(String(30), default="기준")
    reference_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    revision: Mapped[str | None] = mapped_column(String(50), nullable=True)
    drawing_number: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    sheet_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_row_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_valid: Mapped[bool] = mapped_column(default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    delete_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class PreprocessingRun(Base, TimestampMixin):
    __tablename__ = "preprocessing_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    requested_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(40), default="raw_upload")
    parser_version: Mapped[str] = mapped_column(String(40), default="raw-v1")
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_file_ids: Mapped[str] = mapped_column(Text, default="[]")
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PreprocessingRecord(Base, TimestampMixin):
    __tablename__ = "preprocessing_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("preprocessing_runs.id", ondelete="CASCADE"), index=True)
    source_file_id: Mapped[str | None] = mapped_column(ForeignKey("source_files.id", ondelete="SET NULL"), nullable=True, index=True)
    item_kind: Mapped[str] = mapped_column(String(40), default="source")
    raw_payload: Mapped[str] = mapped_column(Text)
    normalized_payload: Mapped[str] = mapped_column(Text)
    source_locator: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="생성")
    confidence: Mapped[str] = mapped_column(String(30), default="중간")


class PreprocessingArtifact(Base, TimestampMixin):
    __tablename__ = "preprocessing_artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("preprocessing_runs.id", ondelete="CASCADE"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(50))
    file_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))


class PriceReference(Base, TimestampMixin):
    """저장된 참고 단가. 자동 적용·학습에 사용하지 않고 신규내역 후보 비교에만 사용한다."""

    __tablename__ = "price_reference_catalog"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    source_file_id: Mapped[str | None] = mapped_column(ForeignKey("source_files.id", ondelete="SET NULL"), nullable=True, index=True)
    source_scope: Mapped[str] = mapped_column(String(50), default="other_building_reference")
    original_item: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    standard_item: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    specification: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    building_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    reference_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provenance: Mapped[str | None] = mapped_column(Text, nullable=True)
    restriction: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, index=True)


class ReviewExport(Base, TimestampMixin):
    """동일 검토 스냅샷에서 생성한 PDF·Excel·근거 Manifest 패키지."""

    __tablename__ = "review_exports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    requested_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    review_run_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    export_type: Mapped[str] = mapped_column(String(40), default="review_bundle")
    filter_snapshot: Mapped[str] = mapped_column(Text, default="{}")
    approval_snapshot: Mapped[str] = mapped_column(Text, default="{}")
    rule_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    data_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    bundle_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    xlsx_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    manifest_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class StandardizedItem(Base, TimestampMixin):
    __tablename__ = "standardized_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    building_id: Mapped[str | None] = mapped_column(ForeignKey("buildings.id", ondelete="SET NULL"), nullable=True, index=True)
    work_package_id: Mapped[str | None] = mapped_column(ForeignKey("work_packages.id", ondelete="SET NULL"), nullable=True, index=True)
    source_file_id: Mapped[str | None] = mapped_column(ForeignKey("source_files.id", ondelete="SET NULL"), nullable=True, index=True)
    item_kind: Mapped[str] = mapped_column(String(30))
    item_code: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    discipline: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    item_name: Mapped[str] = mapped_column(String(500))
    normalized_name: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    specification: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    quantity: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    material_cost: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    labor_cost: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    expense_cost: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    unit_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    total_amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    formula_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    formula_result: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    building_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    floor_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    space_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    drawing_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_row_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_cell_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class DrawingChangeCandidate(Base, TimestampMixin):
    __tablename__ = "drawing_change_candidates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    before_file_id: Mapped[str | None] = mapped_column(ForeignKey("source_files.id", ondelete="SET NULL"), nullable=True)
    after_file_id: Mapped[str | None] = mapped_column(ForeignKey("source_files.id", ondelete="SET NULL"), nullable=True)
    discipline: Mapped[str | None] = mapped_column(String(100), nullable=True)
    drawing_number: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    candidate_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_type: Mapped[str] = mapped_column(String(50), default="변경 후보")
    location_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    geometry_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="근거 확인 대기")
    source_row_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    baseline_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    baseline_revision: Mapped[str | None] = mapped_column(String(100), nullable=True)
    changed_revision: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sheet_number: Mapped[str | None] = mapped_column(String(100), nullable=True)


class ReviewWarning(Base, TimestampMixin):
    __tablename__ = "review_warnings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    standardized_item_id: Mapped[str | None] = mapped_column(ForeignKey("standardized_items.id", ondelete="SET NULL"), nullable=True, index=True)
    drawing_change_candidate_id: Mapped[str | None] = mapped_column(ForeignKey("drawing_change_candidates.id", ondelete="SET NULL"), nullable=True)
    warning_type: Mapped[str] = mapped_column(String(80), index=True)
    severity: Mapped[str] = mapped_column(String(30), default="중간")
    title: Mapped[str] = mapped_column(String(500))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="검토 대기")
    rule_code: Mapped[str | None] = mapped_column(String(100), nullable=True)


class MappingCandidate(Base, TimestampMixin):
    __tablename__ = "mapping_candidates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    estimate_item_id: Mapped[str | None] = mapped_column(ForeignKey("standardized_items.id", ondelete="SET NULL"), nullable=True)
    quantity_item_id: Mapped[str | None] = mapped_column(ForeignKey("standardized_items.id", ondelete="SET NULL"), nullable=True)
    drawing_change_candidate_id: Mapped[str | None] = mapped_column(ForeignKey("drawing_change_candidates.id", ondelete="SET NULL"), nullable=True)
    candidate_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    match_method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="검토 대기")
    source_candidate_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auto_decision: Mapped[str | None] = mapped_column(String(100), nullable=True)


class EvidenceReference(Base, TimestampMixin):
    __tablename__ = "evidence_references"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    mapping_candidate_id: Mapped[str | None] = mapped_column(ForeignKey("mapping_candidates.id", ondelete="CASCADE"), nullable=True, index=True)
    warning_id: Mapped[str | None] = mapped_column(ForeignKey("review_warnings.id", ondelete="CASCADE"), nullable=True, index=True)
    source_file_id: Mapped[str | None] = mapped_column(ForeignKey("source_files.id", ondelete="SET NULL"), nullable=True)
    evidence_type: Mapped[str] = mapped_column(String(50))
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    sheet_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    row_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cell_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_confidence: Mapped[str | None] = mapped_column(String(30), nullable=True)
    evidence_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ApprovalHistory(Base, TimestampMixin):
    __tablename__ = "approval_history"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    source_id: Mapped[str] = mapped_column(String(100), index=True)
    department: Mapped[str] = mapped_column(String(40), index=True)
    decision: Mapped[str] = mapped_column(String(40))
    comment: Mapped[str] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(String(100))
    reviewer_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_sequence: Mapped[bool] = mapped_column(default=False)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


# 기존 API 이름 호환
ReviewDecision = ApprovalHistory


class ProcurementPriceResult(Base, TimestampMixin):
    __tablename__ = "procurement_price_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    standardized_item_id: Mapped[str | None] = mapped_column(ForeignKey("standardized_items.id", ondelete="SET NULL"), nullable=True)
    candidate_id: Mapped[str] = mapped_column(String(100), index=True)
    service_name: Mapped[str] = mapped_column(String(100), default="PriceInfoService")
    standard_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    item_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    specification: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    material_cost: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    labor_cost: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    expense_cost: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    query_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lookup_status: Mapped[str] = mapped_column(String(50))
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_file_id: Mapped[str | None] = mapped_column(ForeignKey("source_files.id", ondelete="SET NULL"), nullable=True)
    # Review context for changed-office candidates.  These values remain
    # provisional until the quantity/design/procurement approvals complete.
    source_set: Mapped[str | None] = mapped_column(String(50), nullable=True)
    work_package: Mapped[str | None] = mapped_column(String(100), nullable=True)
    baseline_quantity: Mapped[str | None] = mapped_column(String(100), nullable=True)
    changed_quantity: Mapped[str | None] = mapped_column(String(100), nullable=True)
    difference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)


class PriceApplicationDecision(Base, TimestampMixin):
    __tablename__ = "price_application_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    standardized_item_id: Mapped[str | None] = mapped_column(ForeignKey("standardized_items.id", ondelete="SET NULL"), nullable=True)
    price_result_id: Mapped[str | None] = mapped_column(ForeignKey("procurement_price_results.id", ondelete="SET NULL"), nullable=True)
    price_type: Mapped[str] = mapped_column(String(50))
    applied_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    decision: Mapped[str] = mapped_column(String(40), default="미검토")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(Text, nullable=True)


class RuleRunJob(Base, TimestampMixin):
    __tablename__ = "rule_run_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    requested_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
