from contextlib import asynccontextmanager
import csv
import hashlib
import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
from functools import lru_cache
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import get_settings
from .database import (
    ApprovalHistory,
    AuditLog,
    Building,
    Base,
    Department,
    DrawingChangeCandidate,
    EvidenceReference,
    MappingCandidate,
    PriceApplicationDecision,
    PriceReference,
    PreprocessingRun,
    PreprocessingRecord,
    ReviewExport,
    ProcurementPriceResult,
    Project,
    ReviewDecision,
    ReviewWarning,
    Role,
    RuleRunJob,
    SessionLocal,
    SourceFile,
    StandardizedItem,
    User,
    UserRole,
    WorkPackage,
    engine,
    get_db,
)
from .schemas import (
    Dashboard,
    DeleteSourceFileRequest,
    DecisionRequest,
    DecisionResponse,
    DrawingCandidateResponse,
    EvidenceResponse,
    JobResponse,
    LoginRequest,
    LoginResponse,
    MappingCandidateResponse,
    PreprocessingStatus,
    QuantityAnalysisResponse,
    QuantityCandidateSelectionRequest,
    QuantityCandidateSelectionResponse,
    PreprocessingRunRequest,
    PreprocessingRunResponse,
    PreprocessingRecordResponse,
    PriceReferenceImportResponse,
    PriceReferenceResponse,
    PriceCandidate,
    PriceDecisionRequest,
    PriceDecisionResponse,
    PriceLookupRequest,
    PriceLookupResponse,
    ProjectStatus,
    ProjectScopeResponse,
    ProjectSummary,
    ScopeOption,
    ReviewItem,
    ReviewWarningResponse,
    RuleRunResult,
    AuditLogResponse,
    BatchDecisionItemResponse,
    BatchDecisionRequest,
    BatchDecisionResponse,
    ReviewExportRequest,
    ReviewExportResponse,
    SourceFileResponse,
    Stat,
)
from .services.preprocessing_reader import PreprocessingReader, clear_drawing_candidate_cache, clear_raw_quantity_cache, drawing_text_role, infer_work_package
from .services.quantity_rule_engine import canonical_key as comparison_key, canonical_unit as comparison_unit
from .services.price_lookup import PriceLookupService

logger = logging.getLogger(__name__)
from .services.rule_engine import RuleEngine
from .services.raw_preprocessor import RawPreprocessor, is_non_office_scope


# Drawing candidates are immutable evidence until the next preprocessing run.
# Cache the merged response briefly so revisiting the drawings screen does not
# repeat model validation for all 1,348 legacy rows.
_DRAWING_RESPONSE_CACHE: dict[tuple[str, str | None, int], tuple[float, list[DrawingCandidateResponse]]] = {}
_DRAWING_RESPONSE_CACHE_TTL_SECONDS = 120.0


def clear_drawing_response_cache() -> None:
    _DRAWING_RESPONSE_CACHE.clear()


_PDF_PERCENT_RE = re.compile(r"^(?:0|[1-9]\d?)(?:\.\d+)?%$")


def _stored_pdf_highlight_regions(geometry_ref: str | None) -> list[dict[str, object]]:
    """Read only explicitly stored PDF-relative regions from a candidate.

    ``geometry_ref`` is an audit payload written by preprocessing.  Requiring
    percentage coordinates prevents a CAD viewport offset or an arbitrary
    text coordinate from being mistaken for a PDF highlight.  Invalid or
    missing geometry is intentionally returned as an empty list.
    """
    if not geometry_ref:
        return []
    try:
        payload = json.loads(geometry_ref)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if isinstance(payload, dict):
        payload = payload.get("pdf_highlight_regions", [])
    if not isinstance(payload, list):
        return []
    regions: list[dict[str, object]] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        if not all(_PDF_PERCENT_RE.fullmatch(str(raw.get(key, "")).strip()) for key in ("left", "top", "width", "height")):
            continue
        floor = raw.get("floor")
        if floor is not None and (not isinstance(floor, int) or floor < 1):
            continue
        regions.append({
            "floor": floor,
            "left": str(raw["left"]).strip(),
            "top": str(raw["top"]).strip(),
            "width": str(raw["width"]).strip(),
            "height": str(raw["height"]).strip(),
            "label": str(raw.get("label") or "변경 구간").strip(),
        })
    return regions


def is_demo_source_name(value: str | None) -> bool:
    """Identify only the files created by the local integration smoke test."""
    name = Path(value or "").name.casefold()
    return name.startswith("integration-source") or name.startswith("demo_")
from .services.report_export import execute_review_export
from .services.auth import verify_password


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="공사비 적정성 검토 API", version="0.1.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

APPROVAL_STAGES = ("공사부서", "설계부서", "구매부서")


@app.post("/api/v1/auth/login", response_model=LoginResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = db.get(User, request.user_id)
    if not user or not user.is_active or not verify_password(request.password, user.password_hash):
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
    department = db.get(Department, user.department_id)
    roles = list(db.scalars(select(Role.code).join(UserRole, Role.id == UserRole.role_id).where(UserRole.user_id == user.id)).all())
    return LoginResponse(user_id=user.id, display_name=user.display_name, department=department.name if department else "", roles=roles, must_change_password=user.must_change_password)


class Principal:
    def __init__(self, user_id: str | None, department: str | None, roles: set[str]):
        self.user_id = user_id
        self.department = department
        self.roles = roles

    @property
    def is_admin(self) -> bool:
        return "ADMIN" in self.roles or "admin" in self.roles


def get_principal(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_db),
) -> Principal:
    """MVP 권한 주체. 운영에서는 X-User-Id를 사내 SSO/JWT 검증 결과로 주입한다."""
    if not x_user_id:
        return Principal(None, None, {"VIEWER"})
    user = db.get(User, x_user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "유효한 X-User-Id가 필요합니다.")
    department = db.get(Department, user.department_id)
    roles = set(db.scalars(select(Role.code).join(UserRole, Role.id == UserRole.role_id).where(UserRole.user_id == user.id)).all())
    return Principal(user.id, department.name if department else None, roles)


def require_read(principal: Principal = Depends(get_principal)) -> Principal:
    if get_settings().auth_required and not principal.user_id:
        raise HTTPException(401, "조회 API는 X-User-Id 인증이 필요합니다.")
    return principal


def require_authenticated(principal: Principal = Depends(get_principal)) -> Principal:
    if not principal.user_id:
        raise HTTPException(401, "변경 API는 X-User-Id 인증이 필요합니다.")
    return principal


def require_project(project_id: str, db: Session) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
    return project


def reader() -> PreprocessingReader:
    return PreprocessingReader()


def as_review_item(row: dict[str, str], rule_outcome: str | None = None) -> ReviewItem:
    return ReviewItem(
        id=row.get("work_id") or row.get("finding_id") or "UNKNOWN",
        priority=int(row["priority_rank"]) if row.get("priority_rank", "").isdigit() else None,
        discipline=row.get("discipline"),
        drawing_sheet=row.get("drawing_sheet"),
        title=row.get("candidate_text") or row.get("candidate_key") or "검토 항목",
        severity=row.get("severity", "중간"),
        status=rule_outcome or row.get("status", "검토 대기"),
        owner_department=row.get("assigned_department") or row.get("owner_department") or "공사부서",
        recommended_action=row.get("recommended_first_action") or row.get("automatic_action") or "근거 확인",
        evidence=row.get("evidence") or row.get("source_evidence"),
        confidence=row.get("confidence"),
        rule=row.get("preprocessing_rule"),
    )


@app.get("/health")
def healthcheck(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        return JSONResponse(status_code=503, content={"status": "degraded", "database": "unavailable", "detail": "PostgreSQL 연결을 확인할 수 없습니다.", "engine": "rule-based", "preprocessing_mode": "raw-upload-pipeline"})
    return {"status": "ok", "database": "ok", "engine": "rule-based", "preprocessing_read_only": False, "preprocessing_mode": "raw-upload-pipeline"}


@app.get("/api/v1/dashboard", response_model=Dashboard)
def dashboard(project_id: str = Query("project-g5-office"), source: PreprocessingReader = Depends(reader), db: Session = Depends(get_db), _: Principal = Depends(require_read)):
    try:
        data = source.dashboard()
    except FileNotFoundError as error:
        data = None
    project = db.get(Project, project_id)
    project_name = project.name if project else "공사비 적정성 검토"
    valid_sources = db.scalars(select(SourceFile).where(SourceFile.project_id == project_id, SourceFile.is_valid.is_(True))).all()
    demo_source_count = sum(1 for item in valid_sources if is_demo_source_name(item.original_name))
    raw_run_count = int(db.scalar(select(func.count()).select_from(PreprocessingRun).where(PreprocessingRun.project_id == project_id, PreprocessingRun.source_kind == "raw_upload")) or 0)
    if data and raw_run_count == 0 and project_id in {"project-g5-office", "G5-OFFICE"}:
        pending = sum(int(row.get("pending") or 0) for row in data["status_rows"])
        stats = [
            Stat(label="검토 대기", value=pending, detail="승인 전 자동 확정 금지"),
            Stat(label="우선 검토", value=data["total_queue"], detail="전처리 우선순위 작업대기열"),
            Stat(label="도면·수량 승인", value=234, detail="원천 근거 및 사람 승인 필요"),
            Stat(label="단가 API 재조회", value=86, detail="인증·파라미터 확인 전 적용 금지"),
        ]
        pending_by_area = data["status_rows"]
        critical_items = data["critical_items"]
        generated_from = "119_최종_전처리_종합보고서 및 연결 CSV(관리자 참고자료)"
    else:
        warning_count = int(db.scalar(select(func.count()).select_from(ReviewWarning).where(ReviewWarning.project_id == project_id)) or 0)
        drawing_count = int(db.scalar(select(func.count()).select_from(DrawingChangeCandidate).where(DrawingChangeCandidate.project_id == project_id)) or 0)
        pending = warning_count + drawing_count
        stats = [
            Stat(label="검토 대기", value=pending, detail="원본 전처리·승인 전 자동 확정 금지"),
            Stat(label="우선 검토", value=warning_count, detail="원본 기반 규칙 경고"),
            Stat(label="도면 변경 후보", value=drawing_count, detail="연결 후보·근거 확인 필요"),
            Stat(label="단가 API 재조회", value=0, detail="단가 검토 결과 조회"),
        ]
        pending_by_area = [{"area": "raw_upload", "total": pending, "auto_processed": 0, "approved": 0, "pending": pending, "blocker": "원본 전처리·검토 대기"}]
        critical_items = []
        generated_from = "원본 업로드 기반 전처리 결과"
    return Dashboard(
        project_name=project_name,
        generated_from=generated_from,
        stats=stats,
        pending_by_area=pending_by_area,
        critical_items=critical_items,
        guardrail="수량·금액·단가는 공사부서 → 설계부서 → 구매부서 승인 전까지 확정하지 않습니다.",
        data_scope="운영 자료 + 통합 테스트 자료" if demo_source_count else "운영 자료만",
        demo_source_count=demo_source_count,
    )


@app.get("/api/v1/reviews", response_model=list[ReviewItem])
def reviews(limit: int = Query(50, ge=1, le=200), status: str | None = None, source: PreprocessingReader = Depends(reader)):
    try:
        return [as_review_item(item) for item in source.review_items(limit, status)]
    except FileNotFoundError as error:
        raise HTTPException(503, str(error)) from error


@app.post("/api/v1/rules/run", response_model=RuleRunResult)
def run_rules(project_id: str = Query("project-g5-office"), source: PreprocessingReader = Depends(reader), db: Session = Depends(get_db), principal: Principal = Depends(require_authenticated)):
    if not principal.is_admin and "REVIEWER" not in principal.roles:
        raise HTTPException(403, "규칙 실행 권한이 없습니다.")
    project = db.get(Project, project_id)
    raw_runs = int(db.scalar(select(func.count()).select_from(PreprocessingRun).where(PreprocessingRun.project_id == project_id, PreprocessingRun.source_kind == "raw_upload", PreprocessingRun.status == "completed")) or 0)
    if raw_runs:
        warning_rows = db.scalars(select(ReviewWarning).where(ReviewWarning.project_id == project_id).order_by(ReviewWarning.created_at.desc()).limit(50)).all()
        items = [as_review_item({"finding_id": row.id, "candidate_text": row.title, "severity": row.severity, "status": row.status, "automatic_action": row.detail, "preprocessing_rule": row.rule_code}, row.status) for row in warning_rows]
        warnings_count = int(db.scalar(select(func.count()).select_from(ReviewWarning).where(ReviewWarning.project_id == project_id)) or 0)
        drawing_count = int(db.scalar(select(func.count()).select_from(DrawingChangeCandidate).where(DrawingChangeCandidate.project_id == project_id)) or 0)
        mapping_count = int(db.scalar(select(func.count()).select_from(MappingCandidate).where(MappingCandidate.project_id == project_id)) or 0)
        return RuleRunResult(processed=warnings_count + drawing_count + mapping_count, by_result={"검토 대기": warnings_count}, items=items, notice="원본 업로드 후 생성된 내부 전처리 결과를 규칙 검토했습니다. 승인 전 자동 확정하지 않았습니다.", quantity_checks=[], warnings=[], drawing_comparisons=[], mapping_candidates=[], price_candidates=[], persisted=bool(project), persisted_project_id=project.id if project else None)
    try:
        result = RuleEngine(source).run()
    except FileNotFoundError as error:
        raise HTTPException(503, str(error)) from error
    project = db.scalar(select(Project).where(Project.project_code == "G5-OFFICE"))
    persisted = False
    if project:
        RuleEngine(source).persist(db, project, result)
        persisted = True
    return RuleRunResult(
        processed=result["processed"],
        by_result=result["by_result"],
        items=[as_review_item(item, item["rule_outcome"]) for item in result["flagged_source_rows"]],
        notice=result["notice"],
        quantity_checks=result["quantity_checks"],
        warnings=result["warnings"],
        drawing_comparisons=result["drawing_comparisons"],
        mapping_candidates=result["mapping_candidates"],
        price_candidates=result["price_candidates"],
        persisted=persisted,
        persisted_project_id=project.id if project else None,
    )


@app.get("/api/v1/prices", response_model=list[PriceCandidate])
def prices(source: PreprocessingReader = Depends(reader)):
    try:
        rows = source.prices()
    except FileNotFoundError as error:
        raise HTTPException(503, str(error)) from error
    return [
        PriceCandidate(
            id=item.get("procurement_queue_id", ""),
            standard_key=item.get("standard_key", ""),
            category=item.get("category", ""),
            status=item.get("status", ""),
            route=item.get("review_route", ""),
            api_status=item.get("api_status"),
            restriction=item.get("restriction", ""),
        )
        for item in rows
    ]


ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".dwg", ".xlsx", ".xlsm", ".xls", ".csv"}
ALLOWED_DOCUMENT_TYPES = {"drawing", "estimate", "quantity", "price_reference", "uploaded_source"}
ALLOWED_VERSION_TYPES = {"기준", "변경", "검토본"}


def validate_upload_signature(extension: str, sample: bytes) -> None:
    """Reject obvious mislabeled files before preserving them on disk."""
    if extension == ".pdf" and not sample.startswith(b"%PDF"):
        raise HTTPException(422, "PDF 파일 시그니처가 올바르지 않습니다.")
    if extension in {".xlsx", ".xlsm"} and not sample.startswith(b"PK"):
        raise HTTPException(422, "XLSX/XLSM 파일 시그니처가 올바르지 않습니다.")
    if extension == ".xls" and not sample.startswith(b"\xd0\xcf\x11\xe0"):
        raise HTTPException(422, "XLS 파일 시그니처가 올바르지 않습니다.")
    if extension == ".dwg" and not sample.startswith(b"AC10"):
        raise HTTPException(422, "DWG 파일 시그니처가 올바르지 않습니다.")


def safe_upload_name(filename: str) -> str:
    name = Path(filename).name
    safe = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", name).strip("._")
    return safe or "uploaded-source"


def preprocessing_run_response(run: PreprocessingRun) -> PreprocessingRunResponse:
    return PreprocessingRunResponse(
        id=run.id,
        project_id=run.project_id,
        source_kind=run.source_kind,
        parser_version=run.parser_version,
        input_hash=run.input_hash,
        source_count=run.source_count,
        processed_count=run.processed_count,
        status=run.status,
        attempt_count=run.attempt_count,
        max_attempts=run.max_attempts,
        error_message=run.error_message,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def execute_preprocessing_run(run_id: str) -> None:
    db = SessionLocal()
    run = db.get(PreprocessingRun, run_id)
    try:
        if not run:
            return
        from datetime import datetime, timezone
        last_error: Exception | None = None
        for attempt in range(1, max(1, run.max_attempts) + 1):
            try:
                run = db.get(PreprocessingRun, run_id)
                run.status = "running"
                run.attempt_count = attempt
                run.started_at = datetime.now(timezone.utc)
                run.error_message = None
                db.commit()
                processed = RawPreprocessor().process(db, run)
                run = db.get(PreprocessingRun, run_id)
                run.status = "completed"
                run.processed_count = processed
                run.finished_at = datetime.now(timezone.utc)
                db.commit()
                clear_drawing_candidate_cache()
                clear_drawing_response_cache()
                return
            except Exception as error:
                last_error = error
                db.rollback()
                if attempt < max(1, run.max_attempts):
                    run = db.get(PreprocessingRun, run_id)
                    run.status = "queued"
                    run.error_message = f"일시 오류로 재시도 예정({attempt}/{run.max_attempts}): {str(error)[:1500]}"
                    db.commit()
        run = db.get(PreprocessingRun, run_id)
        if run:
            run.status = "failed"
            run.error_message = str(last_error or "전처리 실패")[:2000]
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


def execute_legacy_import(run_id: str, project_id: str) -> None:
    db = SessionLocal()
    run = db.get(PreprocessingRun, run_id)
    try:
        if not run:
            return
        from datetime import datetime, timezone
        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        db.commit()
        project = require_project(project_id, db)
        source = PreprocessingReader()
        result = RuleEngine(source).run()
        RuleEngine(source).persist(db, project, result)
        run = db.get(PreprocessingRun, run_id)
        run.status = "completed"
        run.processed_count = int(result["processed"])
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        clear_drawing_candidate_cache()
        clear_drawing_response_cache()
    except Exception as error:
        db.rollback()
        run = db.get(PreprocessingRun, run_id)
        if run:
            from datetime import datetime, timezone
            run.status = "failed"
            run.error_message = str(error)[:2000]
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


@app.get("/api/v1/projects/{project_id}/files", response_model=list[SourceFileResponse])
def project_files(project_id: str, include_deleted: bool = False, db: Session = Depends(get_db), principal: Principal = Depends(require_read)):
    require_project(project_id, db)
    query = select(SourceFile).where(SourceFile.project_id == project_id)
    if not include_deleted or not principal.is_admin:
        query = query.where(SourceFile.is_valid.is_(True))
    rows = db.scalars(query.order_by(SourceFile.created_at.desc())).all()
    runs = db.scalars(select(PreprocessingRun).where(PreprocessingRun.project_id == project_id).order_by(PreprocessingRun.created_at.desc())).all()
    run_by_source: dict[str, tuple[str, str, str | None]] = {}
    for run in runs:
        for source_id in json.loads(run.source_file_ids or "[]"):
            run_by_source.setdefault(source_id, (run.id, run.status, run.error_message))
    return [SourceFileResponse.model_validate(row, from_attributes=True).model_copy(update={"preprocessing_run_id": (run_by_source.get(row.id) or (None, None, None))[0], "preprocessing_status": (run_by_source.get(row.id) or (None, None, None))[1], "preprocessing_error": (run_by_source.get(row.id) or (None, None, None))[2]}) for row in rows]


@app.get("/api/v1/projects/{project_id}/files/{file_id}/pdf")
def project_source_pdf(project_id: str, file_id: str, db: Session = Depends(get_db), _: Principal = Depends(require_read)):
    """Return an uploaded PDF only through its audited source-file record.

    Historical DXF catalogue paths must never become arbitrary downloads.
    The PDF viewer is available only for a valid PDF registered to this
    project.
    """
    require_project(project_id, db)
    record = db.scalar(select(SourceFile).where(
        SourceFile.id == file_id,
        SourceFile.project_id == project_id,
        SourceFile.is_valid.is_(True),
    ))
    if not record:
        raise HTTPException(404, "원본 PDF를 찾을 수 없습니다.")
    path = Path(record.file_path)
    if record.file_type.upper() != "PDF" or path.suffix.lower() != ".pdf":
        raise HTTPException(415, "PDF 원본만 미리보기로 열 수 있습니다.")
    if not path.is_file():
        raise HTTPException(404, "원본 PDF 파일이 저장소에 없습니다.")
    # FileResponse encodes non-ASCII filenames safely. Do not construct a raw
    # Content-Disposition header here: Korean filenames are not Latin-1.
    return FileResponse(path=str(path), media_type="application/pdf", filename=record.original_name)


def _legacy_office_drawing_pdf(discipline: str | None, side: str, bundle: str = "main") -> Path | None:
    """Resolve the audited office-building PDF bundles used for review.

    Legacy detailed candidates are DXF-derived and retain their sheet/coordinate
    evidence. The PDF bundle is a visual source aid for the same architectural
    or structural drawing set; it is never selected from a request path.
    """
    source_root = get_settings().preprocessing_dir.resolve().parent
    paths = {
        ("건축", "baseline"): source_root / "기초자료" / "도면자료" / "광양5-1A-02-DWG-100 사무동 건축기본도면 (Rev.0).pdf",
        ("건축", "changed"): source_root / "변경자료" / "도면자료" / "02. PDF" / "광양5-준공-1A-02-DWG-100_사무동 건축도면_Rev.F.pdf",
        ("구조", "baseline"): source_root / "기초자료" / "도면자료" / "광양5-1S-02-DWG-100 사무동 구조도면 (Rev.0).pdf",
        ("구조", "changed"): source_root / "변경자료" / "도면자료" / "02. PDF" / "광양5-준공-1S-02-DWG-100_사무동 구조도면_Rev.F.pdf",
    }
    # 조적 검토도 기준·변경 모두 같은 ``DWG-100`` 묶음의 층별 평면도를
    # 사용한다. 이전에는 기준만 DWG-500의 벽체 안내도로 바꿔 표시했는데,
    # 변경 도면의 DWG-201/202 평면도와 동일 종류의 시트가 아니어서
    # 좌표를 보정해도 전후 비교가 성립하지 않았다.
    path = paths.get((discipline or "", side))
    return path if path and path.is_file() else None


@lru_cache(maxsize=8)
def _pdf_outline_pages(path_value: str) -> dict[str, int]:
    """Read PDF bookmarks once and expose a sheet-number → page map.

    The audited baseline PDFs are image drawings, so a full text scan cannot
    reliably recover sheets.  Their PDF bookmarks do retain the sheet number;
    using them restores the PDF-based masonry review without a CAD renderer.
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(path_value)
        pages: dict[str, int] = {}

        def walk(nodes: object) -> None:
            if not isinstance(nodes, list):
                return
            for node in nodes:
                if isinstance(node, list):
                    walk(node)
                    continue
                if not hasattr(node, "get"):
                    continue
                title = str(node.get("/Title") or "")
                match = re.search(r"DWG-(\d+[A-Za-z]?)", title, flags=re.IGNORECASE)
                if not match:
                    continue
                try:
                    pages.setdefault(match.group(1).upper(), reader.get_destination_page_number(node) + 1)
                except Exception:
                    continue

        walk(reader.outline)
        return pages
    except Exception:
        # A missing/corrupt bookmark is review metadata only.  The source PDF
        # remains available and is never replaced with a fabricated diagram.
        return {}


def _legacy_office_drawing_page(discipline: str | None, side: str, drawing_number: str | None, bundle: str = "main") -> int | None:
    # 조적 검토는 기준·변경 모두 층별 평면도로 비교한다. DWG-111은
    # 마감재료표이므로 벽돌의 대표 내역 근거로는 쓸 수 있어도 위치 도면으로
    # 쓰면 안 된다. 두 PDF의 실제 페이지 조합을 명시한다.
    if bundle == "masonry-plan" and discipline == "건축" and drawing_number:
        if side == "baseline" and drawing_number.startswith("1A-"):
            return {"1A-201": 10, "1A-202": 11}.get(drawing_number.strip())
        if side == "changed" and drawing_number.startswith("1A-"):
            return {"1A-201": 11, "1A-202": 12}.get(drawing_number.strip())
    path = _legacy_office_drawing_pdf(discipline, side, bundle)
    if not path or not drawing_number:
        return None
    sheet_match = re.search(r"-(\d+[A-Za-z]?)$", drawing_number.strip())
    if not sheet_match:
        return None
    return _pdf_outline_pages(str(path)).get(sheet_match.group(1).upper())


@lru_cache(maxsize=16)
def _pdf_page_png(path_value: str, page_number: int) -> bytes | None:
    """Rasterize exactly one audited PDF page for browsers without a PDF viewer.

    This is a PDF-page preview, not a CAD renderer or inferred geometry.  The
    output is kept only in-process and regenerated after a server restart.
    """
    converter = shutil.which("pdftoppm")
    if not converter or page_number < 1:
        return None
    cache_root = get_settings().upload_dir.resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pdf-page-", dir=str(cache_root)) as directory:
        output_root = Path(directory) / "preview"
        try:
            subprocess.run(
                [converter, "-f", str(page_number), "-l", str(page_number), "-png", "-singlefile", "-scale-to", "1400", path_value, str(output_root)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            output_path = output_root.with_suffix(".png")
            return output_path.read_bytes() if output_path.is_file() else None
        except (OSError, subprocess.SubprocessError):
            return None


def _drawing_pdf_source(project_id: str, candidate_id: str, side: str, db: Session, bundle: str = "main") -> tuple[Path | None, str]:
    """Resolve one registered or audited drawing PDF without exposing a path."""
    candidate = db.scalar(select(DrawingChangeCandidate).where(
        DrawingChangeCandidate.id == candidate_id,
        DrawingChangeCandidate.project_id == project_id,
    ))
    if candidate:
        source_id = candidate.before_file_id if side == "baseline" else candidate.after_file_id
        if source_id:
            source = db.scalar(select(SourceFile).where(
                SourceFile.id == source_id,
                SourceFile.project_id == project_id,
                SourceFile.is_valid.is_(True),
            ))
            if source and source.file_type.upper() == "PDF":
                path = Path(source.file_path)
                if path.is_file():
                    return path, source.original_name
    elif project_id == "project-g5-office" and candidate_id.startswith(("DRAW-DETAIL-", "DRAW-PAIR-")):
        legacy = next((item for item in PreprocessingReader().drawing_candidates(limit=2000) if item.get("id") == candidate_id), None)
        if legacy:
            path = _legacy_office_drawing_pdf(str(legacy.get("discipline") or ""), side, bundle)
            return path, path.name if path else ""
    return None, ""


@app.get("/api/v1/projects/{project_id}/drawings/changes/{candidate_id}/pdf")
def project_drawing_candidate_pdf(
    project_id: str,
    candidate_id: str,
    side: str = Query(..., pattern="^(baseline|changed)$"),
    db: Session = Depends(get_db),
    _: Principal = Depends(require_read),
):
    """Serve the exact registered or audited PDF evidence for one candidate."""
    require_project(project_id, db)
    path, filename = _drawing_pdf_source(project_id, candidate_id, side, db)
    if not path:
        raise HTTPException(404, "이 도면 후보에 연결된 PDF 원본이 없습니다.")
    return FileResponse(path=str(path), media_type="application/pdf", filename=filename)


@app.get("/api/v1/projects/{project_id}/drawings/changes/{candidate_id}/pdf-preview")
def project_drawing_candidate_pdf_preview(
    project_id: str,
    candidate_id: str,
    side: str = Query(..., pattern="^(baseline|changed)$"),
    page: int = Query(..., ge=1, le=2000),
    bundle: str = Query(default="main", pattern="^(main|masonry-plan)$"),
    db: Session = Depends(get_db),
    _: Principal = Depends(require_read),
):
    """Return one real PDF page as PNG when the browser has no PDF plugin."""
    require_project(project_id, db)
    path, _ = _drawing_pdf_source(project_id, candidate_id, side, db, bundle)
    if not path:
        raise HTTPException(404, "이 도면 후보에 연결된 PDF 원본이 없습니다.")
    image = _pdf_page_png(str(path), page)
    if not image:
        raise HTTPException(503, "PDF 페이지 미리보기를 생성할 수 없습니다.")
    return Response(content=image, media_type="image/png", headers={"Cache-Control": "private, max-age=600"})


@app.delete("/api/v1/projects/{project_id}/files/{file_id}", response_model=SourceFileResponse)
def delete_project_file(project_id: str, file_id: str, request: DeleteSourceFileRequest, db: Session = Depends(get_db), principal: Principal = Depends(require_authenticated)):
    require_project(project_id, db)
    if not principal.is_admin:
        raise HTTPException(403, "원본 논리 삭제는 전체 관리자만 수행할 수 있습니다.")
    record = db.scalar(select(SourceFile).where(SourceFile.id == file_id, SourceFile.project_id == project_id))
    if not record:
        raise HTTPException(404, "프로젝트 원본 파일을 찾을 수 없습니다.")
    if not record.is_valid:
        raise HTTPException(409, "이미 논리 삭제된 원본 파일입니다.")
    from datetime import datetime, timezone
    record.is_valid = False
    record.deleted_at = datetime.now(timezone.utc)
    record.deleted_by = principal.user_id
    record.delete_reason = request.reason
    db.add(AuditLog(id=str(uuid4()), user_id=principal.user_id, project_id=project_id, action="source_file.logical_delete", entity_type="source_file", entity_id=file_id, detail=json.dumps({"reason": request.reason, "sha256": record.sha256, "file_path": record.file_path}, ensure_ascii=False)))
    db.commit()
    db.refresh(record)
    return SourceFileResponse.model_validate(record, from_attributes=True)


@app.post("/api/v1/projects/{project_id}/files", response_model=SourceFileResponse, status_code=201)
async def upload_project_file(
    project_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    document_type: str = Form("uploaded_source"),
    version_type: str = Form("기준"),
    building_id: str | None = Form(default=None),
    work_package_id: str | None = Form(default=None),
    reference_date: str | None = Form(default=None),
    revision: str | None = Form(default=None),
    drawing_number: str | None = Form(default=None),
    sheet_name: str | None = Form(default=None),
    source_row_ref: str | None = Form(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_authenticated),
):
    project = require_project(project_id, db)
    if not principal.is_admin and "REVIEWER" not in principal.roles:
        raise HTTPException(403, "자료 업로드 권한이 없습니다.")
    if document_type not in ALLOWED_DOCUMENT_TYPES:
        raise HTTPException(422, "문서 유형은 도면·내역서·수량산출서·단가자료 중 하나여야 합니다.")
    if version_type not in ALLOWED_VERSION_TYPES:
        raise HTTPException(422, "자료 세트는 기준·변경·검토본 중 하나여야 합니다.")
    building = None
    work_package = None
    if building_id:
        building = db.scalar(select(Building).where(Building.id == building_id, Building.project_id == project.id))
        if not building:
            raise HTTPException(422, "선택한 건물이 현재 프로젝트에 속하지 않습니다.")
    if work_package_id:
        work_package = db.scalar(select(WorkPackage).where(WorkPackage.id == work_package_id, WorkPackage.project_id == project.id))
        if not work_package:
            raise HTTPException(422, "선택한 공사단위가 현재 프로젝트에 속하지 않습니다.")
        if building and work_package.building_id and work_package.building_id != building.id:
            raise HTTPException(422, "선택한 공사단위가 건물 범위와 일치하지 않습니다.")
    parsed_reference_date = None
    if reference_date:
        try:
            parsed_reference_date = datetime.fromisoformat(reference_date.replace("Z", "+00:00"))
        except ValueError as error:
            raise HTTPException(422, "기준일 형식이 올바르지 않습니다.") from error
    original_name = file.filename or ""
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(415, "지원하지 않는 파일 형식입니다. PDF·DWG·XLSX·XLSM·XLS·CSV만 업로드할 수 있습니다.")
    settings = get_settings()
    target_dir = settings.upload_dir / project.id
    target_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4().hex}_{safe_upload_name(original_name)}"
    target = target_dir / stored_name
    temporary = target.with_suffix(target.suffix + ".part")
    hasher = hashlib.sha256()
    total = 0
    first_chunk = b""
    max_upload_bytes = settings.max_upload_bytes_for(extension)
    try:
        with temporary.open("wb") as destination:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                if not first_chunk:
                    first_chunk = chunk[:64]
                total += len(chunk)
                if total > max_upload_bytes:
                    raise HTTPException(413, f"{extension.upper()} 파일 크기 제한({max_upload_bytes:,} bytes)을 초과했습니다.")
                hasher.update(chunk)
                destination.write(chunk)
        validate_upload_signature(extension, first_chunk)
        temporary.replace(target)
    except HTTPException:
        temporary.unlink(missing_ok=True)
        raise
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise HTTPException(507, f"업로드 파일을 저장하지 못했습니다: {error}") from error
    finally:
        await file.close()
    digest = hasher.hexdigest()
    duplicate = db.scalar(select(SourceFile).where(SourceFile.project_id == project.id, SourceFile.sha256 == digest, SourceFile.is_valid.is_(True)).order_by(SourceFile.created_at.asc()))
    if duplicate:
        target.unlink(missing_ok=True)
        runs = db.scalars(select(PreprocessingRun).where(PreprocessingRun.project_id == project.id).order_by(PreprocessingRun.created_at.desc())).all()
        linked_run = next((run for run in runs if duplicate.id in json.loads(run.source_file_ids or "[]")), None)
        db.add(AuditLog(id=str(uuid4()), user_id=principal.user_id, project_id=project.id, action="source_file.duplicate_upload", entity_type="source_file", entity_id=duplicate.id, detail=json.dumps({"sha256": digest, "original_name": original_name, "reused": True}, ensure_ascii=False)))
        db.commit()
        response = SourceFileResponse.model_validate(duplicate, from_attributes=True)
        return response.model_copy(update={"preprocessing_run_id": linked_run.id if linked_run else None, "preprocessing_status": linked_run.status if linked_run else "기존 결과 연결 대기", "preprocessing_error": linked_run.error_message if linked_run else None})

    # 같은 논리 식별자(문서 유형·도면번호·시트·Rev.)에 다른 내용이 올라오면
    # 파일을 덮어쓰지 않고 신규 버전으로 보존하되 검토 경고를 남긴다.
    conflict_source = None
    if any((revision or "", drawing_number or "", sheet_name or "")):
        existing_sources = db.scalars(select(SourceFile).where(SourceFile.project_id == project.id, SourceFile.is_valid.is_(True), SourceFile.file_type == extension.lstrip(".").upper(), SourceFile.document_type == document_type[:50])).all()
        for candidate in existing_sources:
            if candidate.sha256 != digest and candidate.revision == (revision or None) and candidate.drawing_number == (drawing_number or None) and candidate.sheet_name == (sheet_name or None):
                conflict_source = candidate
                break

    record = SourceFile(id=str(uuid4()), project_id=project.id, building_id=building.id if building else None, work_package_id=work_package.id if work_package else None, file_type=extension.lstrip(".").upper(), document_type=document_type[:50], original_name=original_name[:500], file_path=str(target), sha256=digest, version_type=version_type[:30], reference_date=parsed_reference_date, revision=(revision or None), drawing_number=(drawing_number or None), sheet_name=(sheet_name or None), source_row_ref=(source_row_ref or None), uploaded_by=principal.user_id, is_valid=True)
    try:
        db.add(record)
        # PostgreSQL needs the source row before the conflict warning and its
        # evidence reference can satisfy their foreign keys. These objects do
        # not have ORM relationships that let SQLAlchemy infer the order.
        db.flush()
        if conflict_source:
            warning_id = str(uuid4())
            db.add(ReviewWarning(id=warning_id, project_id=project.id, warning_type="same_revision_content_conflict", severity="중간", title="동일 Rev.의 파일 내용 상충", detail=f"동일 논리 식별자에 다른 해시 파일이 등록되었습니다. 기존 파일 {conflict_source.original_name} / {conflict_source.sha256}; 신규 파일 {original_name} / {digest}", expected_value=f"기존 해시 {conflict_source.sha256}", actual_value=f"신규 해시 {digest}", status="검토 대기", rule_code="SOURCE_VERSION_CONFLICT"))
            db.flush()
            db.add(EvidenceReference(id=str(uuid4()), project_id=project.id, warning_id=warning_id, source_file_id=record.id, evidence_type="source_version", file_path=str(target), sheet_name=sheet_name, location_text=drawing_number, evidence_note="동일 Rev. 논리 식별자 파일 간 해시 비교"))
        db.commit()
        db.refresh(record)
    except Exception as error:
        db.rollback()
        logger.exception("source file metadata save failed")
        target.unlink(missing_ok=True)
        raise HTTPException(500, "파일 메타데이터를 저장하지 못했습니다.") from error
    # 파일을 한 개씩 업로드해도 프로젝트의 검증 완료 원본 전체를 같은 실행으로
    # 묶어야 수량산출서·내역서·도면 간 연결 후보를 함께 만들 수 있다.
    all_sources = db.scalars(
        select(SourceFile)
        .where(SourceFile.project_id == project.id, SourceFile.is_valid.is_(True))
        .order_by(SourceFile.created_at.asc())
    ).all()
    preprocessing_run = RawPreprocessor().create_run(db, project, all_sources, principal.user_id)
    if preprocessing_run.status == "queued":
        background_tasks.add_task(execute_preprocessing_run, preprocessing_run.id)
    response = SourceFileResponse.model_validate(record, from_attributes=True)
    return response.model_copy(update={"preprocessing_run_id": preprocessing_run.id, "preprocessing_status": preprocessing_run.status, "preprocessing_error": preprocessing_run.error_message})


@app.post("/api/v1/reviews/{source_id}/decisions", response_model=DecisionResponse, status_code=201)
def create_decision(source_id: str, request: DecisionRequest, db: Session = Depends(get_db), principal: Principal = Depends(require_authenticated)):
    if not principal.is_admin and principal.department != request.department:
        raise HTTPException(403, "본인 부서의 승인만 처리할 수 있습니다.")
    if request.override_sequence and not principal.is_admin:
        raise HTTPException(403, "승인 순서 우회는 전체 관리자만 사용할 수 있습니다.")
    if request.override_sequence and not request.override_reason:
        raise HTTPException(422, "승인 순서 우회 사유가 필요합니다.")
    stage_index = APPROVAL_STAGES.index(request.department)
    if stage_index and not request.override_sequence:
        prior_stages = APPROVAL_STAGES[:stage_index]
        approved = set(
            db.scalars(
                select(ReviewDecision.department).where(
                    ReviewDecision.source_id == source_id,
                    ReviewDecision.decision == "승인",
                    ReviewDecision.department.in_(prior_stages),
                )
            ).all()
        )
        missing = [stage for stage in prior_stages if stage not in approved]
        if missing:
            raise HTTPException(
                409,
                f"{request.department} 검토를 시작하려면 선행 승인({', '.join(missing)})이 필요합니다.",
            )
    record = ReviewDecision(id=str(uuid4()), source_id=source_id, reviewer_user_id=principal.user_id, **request.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return DecisionResponse.model_validate(record, from_attributes=True)


@app.get("/api/v1/reviews/{source_id}/decisions", response_model=list[DecisionResponse])
def decision_history(source_id: str, db: Session = Depends(get_db), _: Principal = Depends(require_read)):
    results = db.scalars(select(ReviewDecision).where(ReviewDecision.source_id == source_id).order_by(ReviewDecision.created_at.desc())).all()
    return [DecisionResponse.model_validate(item, from_attributes=True) for item in results]


def job_response(job: RuleRunJob) -> JobResponse:
    return JobResponse(
        id=job.id,
        project_id=job.project_id,
        status=job.status,
        processed_count=job.processed_count,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def execute_rule_job(job_id: str, project_id: str) -> None:
    db = SessionLocal()
    job = db.get(RuleRunJob, job_id)
    try:
        if not job:
            return
        job.status = "running"
        from datetime import datetime, timezone
        job.started_at = datetime.now(timezone.utc)
        db.commit()
        project = require_project(project_id, db)
        raw_runs = int(db.scalar(select(func.count()).select_from(PreprocessingRun).where(PreprocessingRun.project_id == project_id, PreprocessingRun.source_kind == "raw_upload", PreprocessingRun.status == "completed")) or 0)
        if raw_runs:
            processed_count = int(db.scalar(select(func.count()).select_from(ReviewWarning).where(ReviewWarning.project_id == project_id)) or 0)
            processed_count += int(db.scalar(select(func.count()).select_from(MappingCandidate).where(MappingCandidate.project_id == project_id)) or 0)
            processed_count += int(db.scalar(select(func.count()).select_from(DrawingChangeCandidate).where(DrawingChangeCandidate.project_id == project_id)) or 0)
        else:
            source = PreprocessingReader()
            result = RuleEngine(source).run()
            RuleEngine(source).persist(db, project, result)
            processed_count = int(result["processed"])
        job = db.get(RuleRunJob, job_id)
        job.status = "completed"
        job.processed_count = processed_count
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as error:  # background task must leave an inspectable failed state
        db.rollback()
        job = db.get(RuleRunJob, job_id)
        if job:
            job.status = "failed"
            job.error_message = str(error)[:2000]
            from datetime import datetime, timezone
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


@app.get("/api/v1/projects", response_model=list[ProjectSummary])
def project_list(db: Session = Depends(get_db), _: Principal = Depends(require_read)):
    projects = db.scalars(select(Project).order_by(Project.created_at.desc())).all()
    return [ProjectSummary.model_validate(project, from_attributes=True) for project in projects]


@app.get("/api/v1/projects/{project_id}/scope", response_model=ProjectScopeResponse)
def project_scope(project_id: str, db: Session = Depends(get_db), _: Principal = Depends(require_read)):
    project = require_project(project_id, db)
    buildings = db.scalars(select(Building).where(Building.project_id == project_id).order_by(Building.name.asc())).all()
    work_packages = db.scalars(select(WorkPackage).where(WorkPackage.project_id == project_id).order_by(WorkPackage.name.asc())).all()
    return ProjectScopeResponse(
        project=ProjectSummary.model_validate(project, from_attributes=True),
        buildings=[ScopeOption(id=item.id, name=item.name, code=item.code) for item in buildings],
        work_packages=[ScopeOption(id=item.id, name=item.name, code=item.code, building_id=item.building_id) for item in work_packages],
    )


@app.get("/api/v1/projects/{project_id}", response_model=ProjectStatus)
def project_status(project_id: str, db: Session = Depends(get_db), _: Principal = Depends(require_read)):
    project = require_project(project_id, db)
    warning_count = db.scalar(select(func.count()).select_from(ReviewWarning).where(ReviewWarning.project_id == project_id)) or 0
    drawing_count = db.scalar(select(func.count()).select_from(DrawingChangeCandidate).where(DrawingChangeCandidate.project_id == project_id)) or 0
    mapping_count = db.scalar(select(func.count()).select_from(MappingCandidate).where(MappingCandidate.project_id == project_id)) or 0
    quantity_count = db.scalar(select(func.count()).select_from(ReviewWarning).where(ReviewWarning.project_id == project_id, ReviewWarning.warning_type.in_(["quantity_formula_check", "formula_recheck_required"]))) or 0
    price_count = db.scalar(select(func.count()).select_from(ProcurementPriceResult).where(ProcurementPriceResult.project_id == project_id)) or 0
    approval_count = db.scalar(select(func.count()).select_from(ApprovalHistory).where(ApprovalHistory.project_id == project_id)) or 0
    pending_approval_count = db.scalar(select(func.count()).select_from(ApprovalHistory).where(ApprovalHistory.project_id == project_id, ApprovalHistory.decision.in_(["추가 확인 필요", "수정 요청"]))) or 0
    job = db.scalar(select(RuleRunJob).where(RuleRunJob.project_id == project_id).order_by(RuleRunJob.created_at.desc()))
    return ProjectStatus(project=ProjectSummary.model_validate(project, from_attributes=True), warnings=warning_count, drawing_candidates=drawing_count, mapping_candidates=mapping_count, quantity_checks=quantity_count, price_candidates=price_count, approvals=approval_count, pending_approvals=pending_approval_count, last_rule_job=job.id if job else None)


@app.get("/api/v1/projects/{project_id}/preprocessing", response_model=PreprocessingStatus)
def preprocessing_status(project_id: str, db: Session = Depends(get_db), source: PreprocessingReader = Depends(reader), _: Principal = Depends(require_read)):
    require_project(project_id, db)
    runs = db.scalars(select(PreprocessingRun).where(PreprocessingRun.project_id == project_id).order_by(PreprocessingRun.created_at.desc()).limit(20)).all()
    try:
        data = source.dashboard()
    except FileNotFoundError as error:
        data = None
    if data:
        areas = data["status_rows"]
        generated_from = "118_final_preprocessing_status.csv 및 119_최종_전처리_종합보고서.md(관리자 참고자료)"
        pending_total = sum(int(row.get("pending") or 0) for row in areas)
    else:
        areas = [{"area": "raw_upload", "total": sum(run.source_count for run in runs), "auto_processed": sum(run.processed_count for run in runs if run.status == "completed"), "approved": 0, "pending": sum(run.source_count for run in runs if run.status != "completed"), "blocker": "원본 전처리 작업 상태"}]
        generated_from = "원본 업로드 기반 전처리 작업"
        pending_total = sum(int(row.get("pending") or 0) for row in areas)
    return PreprocessingStatus(project_id=project_id, generated_from=generated_from, areas=areas, pending_total=pending_total, runs=[preprocessing_run_response(run) for run in runs])


def _json_payload(value: str | None) -> object:
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


@app.get("/api/v1/projects/{project_id}/preprocessing/runs/{run_id}/records", response_model=list[PreprocessingRecordResponse])
def preprocessing_records(
    project_id: str,
    run_id: str,
    item_kind: str | None = None,
    status: str | None = None,
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: Principal = Depends(require_read),
):
    """선택한 전처리 실행의 원본값·표준화값을 필요한 범위만 재조회한다."""
    require_project(project_id, db)
    run = db.scalar(select(PreprocessingRun).where(PreprocessingRun.id == run_id, PreprocessingRun.project_id == project_id))
    if not run:
        raise HTTPException(404, "프로젝트의 전처리 실행을 찾을 수 없습니다.")
    query = select(PreprocessingRecord).where(PreprocessingRecord.run_id == run_id)
    if item_kind:
        query = query.where(PreprocessingRecord.item_kind == item_kind)
    if status:
        query = query.where(PreprocessingRecord.status == status)
    rows = db.scalars(query.order_by(PreprocessingRecord.created_at.asc()).offset(offset).limit(limit)).all()
    return [
        PreprocessingRecordResponse(
            id=row.id,
            run_id=row.run_id,
            source_file_id=row.source_file_id,
            item_kind=row.item_kind,
            raw_payload=_json_payload(row.raw_payload),
            normalized_payload=_json_payload(row.normalized_payload),
            source_locator=row.source_locator,
            status=row.status,
            confidence=row.confidence,
            created_at=row.created_at,
        )
        for row in rows
    ]


@app.post("/api/v1/projects/{project_id}/preprocessing/run", response_model=PreprocessingRunResponse, status_code=202)
def enqueue_preprocessing(project_id: str, background_tasks: BackgroundTasks, request: PreprocessingRunRequest | None = None, db: Session = Depends(get_db), principal: Principal = Depends(require_authenticated)):
    project = require_project(project_id, db)
    if not principal.is_admin and not ("REVIEWER" in principal.roles or principal.department in APPROVAL_STAGES):
        raise HTTPException(403, "전처리 실행 권한이 없습니다.")
    requested_ids = request.source_file_ids if request and request.source_file_ids else None
    query = select(SourceFile).where(SourceFile.project_id == project.id, SourceFile.is_valid.is_(True))
    if requested_ids:
        query = query.where(SourceFile.id.in_(requested_ids))
    sources = db.scalars(query.order_by(SourceFile.created_at.asc())).all()
    if not sources:
        raise HTTPException(422, "전처리할 검증 완료 원본 파일이 없습니다.")
    run = RawPreprocessor().create_run(db, project, sources, principal.user_id)
    if run.status == "queued":
        background_tasks.add_task(execute_preprocessing_run, run.id)
    return preprocessing_run_response(run)


@app.post("/api/v1/projects/{project_id}/preprocessing/{run_id}/retry", response_model=PreprocessingRunResponse, status_code=202)
def retry_preprocessing(project_id: str, run_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db), principal: Principal = Depends(require_authenticated)):
    require_project(project_id, db)
    if not principal.is_admin and "REVIEWER" not in principal.roles:
        raise HTTPException(403, "전처리 재시도 권한이 없습니다.")
    run = db.scalar(select(PreprocessingRun).where(PreprocessingRun.id == run_id, PreprocessingRun.project_id == project_id))
    if not run:
        raise HTTPException(404, "전처리 작업을 찾을 수 없습니다.")
    if run.source_kind != "raw_upload":
        raise HTTPException(409, "기존 전처리 결과 가져오기 작업은 원본 재시도 API를 사용할 수 없습니다.")
    if run.status in {"queued", "running"}:
        raise HTTPException(409, "이미 실행 중인 전처리 작업입니다.")
    if run.status != "failed":
        raise HTTPException(409, "실패한 전처리 작업만 재시도할 수 있습니다.")
    run.status = "queued"
    run.attempt_count = 0
    run.max_attempts = 5
    run.error_message = None
    run.started_at = None
    run.finished_at = None
    run.requested_by = principal.user_id
    db.commit()
    db.refresh(run)
    background_tasks.add_task(execute_preprocessing_run, run.id)
    return preprocessing_run_response(run)


@app.post("/api/v1/admin/projects/{project_id}/preprocessing/import", response_model=PreprocessingRunResponse, status_code=202)
def import_legacy_preprocessing(project_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db), principal: Principal = Depends(require_authenticated)):
    project = require_project(project_id, db)
    if not principal.is_admin:
        raise HTTPException(403, "기존 전처리 결과 가져오기는 전체 관리자만 사용할 수 있습니다.")
    legacy_root = get_settings().preprocessing_dir
    if not legacy_root.exists():
        raise HTTPException(503, "기존 전처리 결과 경로를 찾을 수 없습니다.")
    digest = hashlib.sha256("|".join(sorted(path.name + str(path.stat().st_mtime_ns) for path in legacy_root.glob("*"))).encode("utf-8")).hexdigest()
    run = PreprocessingRun(id=str(uuid4()), project_id=project.id, requested_by=principal.user_id, source_kind="legacy_import", parser_version="legacy-reader-v1", input_hash=digest, source_count=0, status="queued")
    db.add(run)
    db.commit()
    db.refresh(run)
    background_tasks.add_task(execute_legacy_import, run.id, project.id)
    return preprocessing_run_response(run)


@app.get("/api/v1/projects/{project_id}/warnings", response_model=list[ReviewWarningResponse])
def project_warnings(project_id: str, severity: str | None = None, status: str | None = None, warning_type: str | None = Query(default=None, max_length=100), run_id: str | None = Query(default=None, max_length=100), limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db), _: Principal = Depends(require_read)):
    require_project(project_id, db)
    query = select(ReviewWarning).where(ReviewWarning.project_id == project_id)
    if severity:
        query = query.where(ReviewWarning.severity == severity)
    if status:
        query = query.where(ReviewWarning.status == status)
    if warning_type:
        query = query.where(ReviewWarning.warning_type == warning_type)
    if run_id:
        # A warning is retained as audit history across reprocessing runs.
        # The intake page needs only the selected run's immutable source rows,
        # so filter through the standardized snapshot's persisted run id.
        query = query.join(StandardizedItem, ReviewWarning.standardized_item_id == StandardizedItem.id).where(
            StandardizedItem.notes.like(f'%"run_id": "{run_id}"%')
        )
    query = query.order_by(ReviewWarning.created_at.desc()).limit(limit)
    return [ReviewWarningResponse.model_validate(item, from_attributes=True) for item in db.scalars(query).all()]


@app.get("/api/v1/projects/{project_id}/drawings/changes", response_model=list[DrawingCandidateResponse])
def project_drawing_candidates(project_id: str, status: str | None = None, limit: int = Query(100, ge=1, le=2000), db: Session = Depends(get_db), _: Principal = Depends(require_read)):
    require_project(project_id, db)
    cache_key = (project_id, status, limit)
    cached = _DRAWING_RESPONSE_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < _DRAWING_RESPONSE_CACHE_TTL_SECONDS:
        return cached[1]
    query = select(DrawingChangeCandidate).where(DrawingChangeCandidate.project_id == project_id)
    if status:
        query = query.where(DrawingChangeCandidate.status == status)
    query = query.order_by(DrawingChangeCandidate.created_at.desc()).limit(limit)
    db_items = db.scalars(query).all()
    # Seeded legacy rows may be newer than the file-backed candidates created
    # by raw preprocessing. Prefer the latter whenever they exist so that the
    # response carries real before/after files and linkage evidence.
    file_backed_query = select(DrawingChangeCandidate).where(
        DrawingChangeCandidate.project_id == project_id,
        or_(DrawingChangeCandidate.baseline_file.is_not(None), DrawingChangeCandidate.changed_file.is_not(None)),
    )
    if status:
        file_backed_query = file_backed_query.where(DrawingChangeCandidate.status == status)
    file_backed_items = db.scalars(file_backed_query.order_by(DrawingChangeCandidate.created_at.desc()).limit(limit)).all()
    if file_backed_items:
        db_items = file_backed_items
    # 도면 후보가 실제 사무동 변경 내역과 연결되는지 읽기 전용으로
    # 검증한다. 이 단계에서는 MappingCandidate를 자동 확정하지 않고,
    # 같은 기준/변경 도면번호를 가진 내역서 행의 개수와 품명만 근거로
    # 반환한다.
    source_ids = {source_id for item in db_items for source_id in (item.before_file_id, item.after_file_id) if source_id}
    estimate_rows = []
    if source_ids:
        estimate_rows = db.scalars(
            select(StandardizedItem).where(
                StandardizedItem.project_id == project_id,
                StandardizedItem.item_kind == "estimate",
                StandardizedItem.source_file_id.in_(source_ids),
            )
        ).all()
    estimates_by_source: dict[str, list[StandardizedItem]] = {}
    for row in estimate_rows:
        if is_non_office_scope(row.item_name, row.specification, row.building_label, row.drawing_number):
            continue
        estimates_by_source.setdefault(row.source_file_id or "", []).append(row)

    def with_link_evidence(item: DrawingChangeCandidate | dict) -> DrawingCandidateResponse:
        if isinstance(item, dict):
            response = DrawingCandidateResponse.model_validate(item)
            masonry_plan = project_id == "project-g5-office" and response.discipline == "건축" and "조적" in (response.work_package or "")
            pdf_bundle = "masonry-plan" if masonry_plan else "main"
            baseline_pdf = _legacy_office_drawing_pdf(response.discipline, "baseline", pdf_bundle) if project_id == "project-g5-office" else None
            changed_pdf = _legacy_office_drawing_pdf(response.discipline, "changed", pdf_bundle) if project_id == "project-g5-office" else None
            # Historic office candidates originated from a DXF catalogue, but
            # the review source is the paired PDF.  Recover the bookmarked
            # page here rather than treating a text coordinate as a drawing
            # renderer or showing page 1 for every masonry item.
            baseline_page = _legacy_office_drawing_page(response.discipline, "baseline", response.drawing_number or response.sheet_number, pdf_bundle) if baseline_pdf else None
            changed_page = _legacy_office_drawing_page(response.discipline, "changed", response.drawing_number or response.sheet_number, pdf_bundle) if changed_pdf else None
            page_number = baseline_page or changed_page or response.page_number
            # DWG-111의 마감재료표 텍스트는 위치 근거가 아니다. 같은 형식의
            # 평면도끼리만 화면에 비교한다: 기준 DWG-100 p.10/11 ↔ 변경
            # DWG-100 p.11/12. 위치 좌표가 확인되지 않은 공종은 이 페이지를
            # 보여 주되 음영을 추정해 그리지 않는다.
            # 현재 대표 표시로 확인된 층은 1층(기준 p.10 ↔ 변경 p.11)만
            # 제공한다. 2층은 기준/변경 도면 유형과 범위가 달라 대표 구간을
            # 임의로 만들지 않고 화면에서 제외한다.
            baseline_floor_pages = [10] if masonry_plan else []
            changed_floor_pages = [11] if masonry_plan else []
            # 조적 대표 변경은 사용자가 확인한 1층 원본 PDF 확대 구간
            # (121 냉장실·122 냉동실 주변 벽체)을 검토 지원용으로 표시한다.
            # 승인 확정 좌표가 아니라, 동일 층 변경 PDF에서 이해를 돕는
            # 대표 범위이며 다른 층에는 재사용하지 않는다.
            pdf_highlight_regions = ([
                {
                    "floor": 1,
                    "left": "68.0%",
                    "top": "28.0%",
                    "width": "11.5%",
                    "height": "27.0%",
                    "label": "1층 조적 변경 구간 · 121·122실 벽체",
                },
            ] if masonry_plan else [])
            package_text = response.work_package or ""
            if masonry_plan:
                pdf_page_status = "동일 층 평면도 비교 · 확인된 대표 변경 구간 음영 표시"
            elif "철골" in package_text and baseline_page == 15:
                pdf_page_status = "철골 구조 입면도 표시"
            elif any(token in package_text for token in ("방수", "타일")) and baseline_page == 4:
                pdf_page_status = "마감재료표 표시 · 변경 표기 참고"
            elif "토공" in package_text and baseline_page == 50:
                pdf_page_status = "구조 상세도 표시 · 변경 표기 참고"
            else:
                pdf_page_status = "PDF 시트 표시" if baseline_page or changed_page else "PDF 원본 표시"
            return response.model_copy(update={
                "work_package": response.work_package or PreprocessingReader._drawing_work_package(response.candidate_text or "", response.discipline or ""),
                "text_role": response.text_role or drawing_text_role(response.candidate_text),
                "location_status": response.location_status or ("부위 후보" if drawing_text_role(response.candidate_text) == "부위 표기" else "부위 미확정"),
                "baseline_file": str(baseline_pdf) if baseline_pdf else response.baseline_file,
                "changed_file": str(changed_pdf) if changed_pdf else response.changed_file,
                "page_number": page_number,
                "baseline_page_number": baseline_page,
                "changed_page_number": changed_page,
                "baseline_floor_pages": baseline_floor_pages,
                "changed_floor_pages": changed_floor_pages,
                "pdf_highlight_regions": pdf_highlight_regions,
                "pdf_page_status": pdf_page_status,
            })
        response = DrawingCandidateResponse.model_validate(item, from_attributes=True)
        drawing_number = (item.drawing_number or item.sheet_number or "").strip().lower()
        baseline_matches = [row for row in estimates_by_source.get(item.before_file_id or "", []) if drawing_number and (row.drawing_number or "").strip().lower() == drawing_number]
        changed_matches = [row for row in estimates_by_source.get(item.after_file_id or "", []) if drawing_number and (row.drawing_number or "").strip().lower() == drawing_number]
        matches = baseline_matches + changed_matches
        names = list(dict.fromkeys((row.item_name or "").strip() for row in matches if (row.item_name or "").strip()))[:8]
        if baseline_matches and changed_matches:
            link_status = "기준·변경 내역 연결됨"
        elif changed_matches:
            link_status = "변경 내역 연결됨·기준 근거 없음"
        elif baseline_matches:
            link_status = "기준 내역 연결됨·변경 근거 없음"
        else:
            link_status = "내역 연결 근거 없음"
        page_match = re.search(r"PDF\s*페이지\s*(\d+)", item.location_ref or "", flags=re.IGNORECASE)
        stored_highlights = _stored_pdf_highlight_regions(item.geometry_ref)
        return response.model_copy(update={
            "work_package": PreprocessingReader._drawing_work_package(item.candidate_text or "", item.discipline or ""),
            "text_role": drawing_text_role(item.candidate_text),
            "location_status": "부위 후보" if drawing_text_role(item.candidate_text) == "부위 표기" else "부위 미확정",
            "baseline_source_file_id": item.before_file_id,
            "changed_source_file_id": item.after_file_id,
            "page_number": int(page_match.group(1)) if page_match else None,
            "linked_estimate_count": len(matches),
            "linked_estimate_names": names,
            "link_status": link_status,
            "pdf_highlight_regions": stored_highlights,
        })
    # The first UI mock returned either a file-level DB pair or the old 06
    # mapping sheet.  That hid the detailed masonry/architecture/structure
    # preprocessing records as soon as one raw upload existed.  Merge the
    # immutable catalogue with current raw-upload candidates instead: both are
    # drawing evidence, neither is a quantity judgement or an automatic link.
    legacy_items: list[dict] = []
    if project_id == "project-g5-office":
        try:
            legacy_items = PreprocessingReader().drawing_candidates(limit=limit)
        except FileNotFoundError:
            legacy_items = []
        if status:
            legacy_items = [item for item in legacy_items if item.get("status") == status]
    merged: list[DrawingChangeCandidate | dict] = [*legacy_items, *db_items]
    deduplicated: dict[str, DrawingChangeCandidate | dict] = {}
    for item in merged:
        identity = item.get("id") if isinstance(item, dict) else item.id
        if identity:
            deduplicated[str(identity)] = item
    response = [with_link_evidence(item) for item in list(deduplicated.values())[:limit]]
    _DRAWING_RESPONSE_CACHE[cache_key] = (time.monotonic(), response)
    return response


@app.get("/api/v1/projects/{project_id}/quantities", response_model=list[ReviewWarningResponse])
def project_quantity_results(project_id: str, db: Session = Depends(get_db), _: Principal = Depends(require_read)):
    require_project(project_id, db)
    rows = db.scalars(select(ReviewWarning).where(ReviewWarning.project_id == project_id, ReviewWarning.warning_type.in_(["quantity_formula_check", "formula_recheck_required", "quantity_mismatch", "negative_quantity_or_amount"])).order_by(ReviewWarning.created_at.desc())).all()
    return [ReviewWarningResponse.model_validate(item, from_attributes=True) for item in rows]


@app.get("/api/v1/projects/{project_id}/quantity-analysis", response_model=QuantityAnalysisResponse)
def project_quantity_analysis(
    project_id: str,
    source_set: str | None = Query(default=None, pattern="^(기준자료|변경자료|기준·변경 대조)$"),
    issue_type: str | None = Query(default=None, pattern="^(일치|불일치|재검산 불가|연결 근거 없음|복수 연결 후보)$"),
    severity: str | None = Query(default=None, pattern="^(높음|중간|낮음)$"),
    discipline: str | None = Query(default=None, max_length=50),
    work_package: str | None = Query(default=None, max_length=80),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=1000, ge=1, le=5000),
    db: Session = Depends(get_db),
    _: Principal = Depends(require_read),
):
    require_project(project_id, db)
    if project_id != "project-g5-office":
        raise HTTPException(status_code=404, detail="현재 MVP는 광양5 사무동 프로젝트만 분석 범위로 제공합니다.")
    reader = PreprocessingReader()
    # Seeded demo data is served from the immutable legacy CSV package. Once a
    # project has a completed raw-upload run with real estimate/quantity rows,
    # prefer that DB snapshot so new material is reviewed at item level rather
    # than being represented only by the legacy drawing-candidate queue.
    result = reader.raw_quantity_analysis(db, project_id=project_id, limit=limit, source_set=source_set, issue_type=issue_type, severity=severity, query=q, discipline=discipline, work_package=work_package)
    if result is None:
        result = reader.quantity_analysis(limit=limit, source_set=source_set, issue_type=issue_type, severity=severity, query=q, discipline=discipline, work_package=work_package)
    result["project_id"] = project_id
    return result


@app.post("/api/v1/projects/{project_id}/quantity-analysis/{estimate_item_id}/candidate", response_model=QuantityCandidateSelectionResponse)
def select_quantity_candidate(
    project_id: str,
    estimate_item_id: str,
    request: QuantityCandidateSelectionRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_authenticated),
):
    """Persist a human-selected quantity evidence row without confirming it."""
    require_project(project_id, db)
    if not principal.is_admin and principal.department != "공사부서":
        raise HTTPException(403, "수량산출서 후보 지정은 공사부서 또는 관리자만 처리할 수 있습니다.")
    estimate = db.scalar(select(StandardizedItem).where(StandardizedItem.id == estimate_item_id, StandardizedItem.project_id == project_id, StandardizedItem.item_kind == "estimate"))
    quantity = db.scalar(select(StandardizedItem).where(StandardizedItem.id == request.quantity_item_id, StandardizedItem.project_id == project_id, StandardizedItem.item_kind == "quantity"))
    if not estimate or not quantity:
        raise HTTPException(404, "내역서 또는 수량산출서 원본 행을 찾을 수 없습니다.")
    if quantity.building_label and quantity.building_label != "사무동":
        raise HTTPException(422, "광양5 사무동 검토에는 타건물 수량산출서 행을 지정할 수 없습니다.")
    estimate_source = db.get(SourceFile, estimate.source_file_id)
    quantity_source = db.get(SourceFile, quantity.source_file_id)
    if estimate_source and quantity_source and estimate_source.version_type != quantity_source.version_type:
        raise HTTPException(422, "기준자료와 변경자료를 교차 연결할 수 없습니다.")
    previous = db.scalars(select(MappingCandidate).where(MappingCandidate.project_id == project_id, MappingCandidate.estimate_item_id == estimate.id, MappingCandidate.status == "선택됨")).all()
    for row in previous:
        row.status = "검토 보류"
    mapping = MappingCandidate(
        id=str(uuid4()),
        project_id=project_id,
        estimate_item_id=estimate.id,
        quantity_item_id=quantity.id,
        candidate_key=estimate.normalized_name,
        match_method="manual_review_selection",
        confidence="중간",
        status="선택됨",
        source_candidate_count=len(previous) + 1,
        auto_decision="사람 선택·자동확정 아님",
    )
    db.add(mapping)
    db.add(AuditLog(id=str(uuid4()), user_id=principal.user_id, project_id=project_id, action="quantity.mapping.select_candidate", entity_type="mapping_candidate", entity_id=mapping.id, detail=json.dumps({"estimate_item_id": estimate.id, "quantity_item_id": quantity.id, "comment": request.comment, "auto_confirmed": False}, ensure_ascii=False)))
    db.commit()
    clear_raw_quantity_cache(project_id)
    return QuantityCandidateSelectionResponse(estimate_item_id=estimate.id, quantity_item_id=quantity.id, status=mapping.status, auto_decision=mapping.auto_decision or "", comment=request.comment)


@app.get("/api/v1/projects/{project_id}/mappings", response_model=list[MappingCandidateResponse])
def project_mapping_results(project_id: str, db: Session = Depends(get_db), _: Principal = Depends(require_read)):
    require_project(project_id, db)
    rows = db.scalars(select(MappingCandidate).where(MappingCandidate.project_id == project_id).order_by(MappingCandidate.created_at.desc())).all()
    return [MappingCandidateResponse.model_validate(item, from_attributes=True) for item in rows]


@app.get("/api/v1/projects/{project_id}/prices/results", response_model=list[PriceLookupResponse])
def project_price_results(project_id: str, db: Session = Depends(get_db), _: Principal = Depends(require_read)):
    require_project(project_id, db)
    rows = db.scalars(select(ProcurementPriceResult).where(ProcurementPriceResult.project_id == project_id).order_by(ProcurementPriceResult.created_at.desc())).all()
    # 가격 결과는 DB 조회 이력과 전처리 신규내역 대기열을 함께 보여준다.
    # 79번 대기열은 사무동 전용 산출물이며, 타건물 계약단가 카탈로그와
    # 달리 실제 연결·승인 대상이다. 기존 시드 DB에는 대기열 중 일부만
    # 저장되어 있을 수 있으므로 여기서 읽기 전용으로 합쳐 화면 누락을
    # 방지한다. 값이나 승인 상태를 자동 확정하지는 않는다.
    try:
        legacy_rows = PreprocessingReader().prices() if project_id == "project-g5-office" else []
    except FileNotFoundError:
        legacy_rows = []
    legacy_by_candidate: dict[str, dict[str, object]] = {}
    for item in legacy_rows:
        for key in (item.get("candidate_id"), item.get("procurement_queue_id")):
            if key:
                legacy_by_candidate[str(key)] = item
    result: list[PriceLookupResponse] = []
    seen_candidates: set[str] = set()
    seen_comparison_keys: set[tuple[str, str, str, str, str]] = set()
    has_persisted_changed_candidates = False
    reference_rows = db.scalars(
        select(PriceReference).where(
            PriceReference.is_active.is_(True),
            (PriceReference.project_id == project_id) | (PriceReference.source_scope == "other_building_reference"),
        )
    ).all()

    def enrich_reference_match(payload: dict[str, object]) -> None:
        """Attach ranked reference evidence without copying a price value."""
        item_name = comparison_key(payload.get("item_name"))
        item_spec = comparison_key(payload.get("specification"))
        item_unit = comparison_unit(payload.get("unit"))
        if not item_name:
            payload.update({"reference_match_count": 0, "reference_match_status": "품명 확인 필요"})
            return
        ranked: list[tuple[int, int, PriceReference]] = []
        for reference in reference_rows:
            reference_name = comparison_key(reference.standard_item or reference.original_item)
            if not reference_name or reference_name != item_name:
                continue
            reference_unit = comparison_unit(reference.unit)
            if item_unit and reference_unit and item_unit != reference_unit:
                continue
            reference_spec = comparison_key(reference.specification)
            score = 2
            if item_spec and reference_spec:
                if item_spec != reference_spec:
                    continue
                score += 2
            if item_unit and reference_unit:
                score += 1
            priority = 0 if reference.project_id == project_id and reference.source_scope != "other_building_reference" else 1
            ranked.append((score, priority, reference))
        ranked.sort(key=lambda row: (-row[0], row[1], str(row[2].reference_date or "")), reverse=False)
        if not ranked:
            payload.update({"reference_match_count": 0, "reference_match_status": "참고단가 미확인"})
            return
        best = ranked[0][2]
        scope = "동일 프로젝트 자료" if best.project_id == project_id and best.source_scope != "other_building_reference" else "타건물 참고자료"
        payload.update({
            "reference_match_count": len(ranked),
            "best_reference_price": float(best.price) if best.price is not None else None,
            "best_reference_scope": scope,
            "reference_match_status": "참고단가 후보 연결" if best.price is not None else "참고항목 연결·단가 없음",
        })

    def append_payload(payload: dict[str, object]) -> None:
        candidate_id = str(payload.get("candidate_id") or "").strip()
        if not candidate_id or candidate_id in seen_candidates:
            return
        if payload.get("source_set") in {"기준·변경 대조", "변경자료 신규내역"}:
            comparison_key = (
                str(payload.get("source_file_id") or ""),
                str(payload.get("item_name") or "").strip().casefold(),
                str(payload.get("specification") or "").strip().casefold(),
                str(payload.get("unit") or "").strip().casefold(),
                str(payload.get("changed_quantity") or "").strip(),
            )
            if comparison_key in seen_comparison_keys:
                return
            seen_comparison_keys.add(comparison_key)
        enrich_reference_match(payload)
        seen_candidates.add(candidate_id)
        result.append(PriceLookupResponse.model_validate(payload))

    for row in rows:
        # 조회 루프마다 연결 대상을 초기화한다. 이전 행의 객체가 다음
        # 행으로 누출되지 않도록 하여, 오래된 DB 결과도 안전하게 보강한다.
        standardized = None
        source = None
        # Older preprocessing runs may have persisted comparison candidates
        # before the office-scope/positive-quantity guard was introduced.
        # Re-apply the same guard at read time so stale rows cannot leak into
        # the unit-price queue after an upgrade.
        if row.service_name == "기준·변경 대조 전처리":
            standardized = db.get(StandardizedItem, row.standardized_item_id) if row.standardized_item_id else None
            source = db.get(SourceFile, standardized.source_file_id) if standardized else None
            if standardized and source and source.version_type == "변경":
                if standardized.quantity is None or standardized.quantity <= 0:
                    continue
                if is_non_office_scope(standardized.item_name, standardized.specification, standardized.building_label, standardized.drawing_number):
                    continue
                has_persisted_changed_candidates = True
        payload = {
            "id": row.id,
            "project_id": row.project_id,
            "candidate_id": row.candidate_id,
            "lookup_status": row.lookup_status,
            "item_name": row.item_name,
            "specification": row.specification,
            "unit": row.unit,
            "price": float(row.price) if row.price is not None else None,
            "service_name": row.service_name,
            "source_file_id": row.source_file_id,
            "reference_date": row.reference_date,
            "created_at": row.created_at,
        }
        if row.service_name == "기준·변경 대조 전처리" and standardized and source:
            payload["source_set"] = "변경자료 신규내역"
            payload["work_package"] = infer_work_package(standardized.item_name, standardized.specification)
            # 과거 실행분은 결과 테이블의 source_file_id를 채우기 전에
            # 저장됐을 수 있으므로, 표준화 내역의 원본 파일을 기준으로
            # 추적 ID를 보강한다.
            payload["source_file_id"] = source.id
            payload["changed_quantity"] = str(standardized.quantity) if standardized.quantity is not None else None
            payload["evidence"] = f"변경자료 내역서 {source.original_name} · {standardized.source_row_ref or '원본 행'} · 기준자료 표준키 미발견"
        legacy = legacy_by_candidate.get(row.candidate_id)
        if legacy:
            # 시드 결과가 품명/규격을 비워 둔 경우에도 대기열의 원문을
            # 우선 표시해 구매부서가 무엇을 검토하는지 알 수 있게 한다.
            payload["item_name"] = payload["item_name"] or legacy.get("standard_key") or "품명 확인 필요"
            payload["specification"] = payload["specification"] or legacy.get("category")
            payload["lookup_status"] = payload["lookup_status"] or legacy.get("price_status") or "단가 검토 대기"
            payload["source_set"] = "변경자료 신규내역"
            payload["evidence"] = legacy.get("restriction") or "79번 사무동 신규내역 단가검토 대기열"
        append_payload(payload)

    # DB에 아직 생성되지 않은 79번 신규내역도 후보로 노출한다. 안정적인
    # ID를 사용하므로 이후 실제 API 조회 결과가 저장되면 candidate_id로
    # 중복 없이 하나의 항목으로 합쳐진다.
    for legacy in legacy_rows:
        candidate_id = str(legacy.get("candidate_id") or "").strip()
        queue_id = str(legacy.get("procurement_queue_id") or candidate_id)
        if not candidate_id or candidate_id in seen_candidates or queue_id in seen_candidates:
            continue
        stable_id = f"legacy-price-{hashlib.sha256(f'{project_id}|{queue_id}'.encode('utf-8')).hexdigest()[:24]}"
        append_payload({
            "id": stable_id,
            "project_id": project_id,
            "candidate_id": candidate_id,
            "lookup_status": legacy.get("price_status") or "단가 검토 대기",
            "item_name": legacy.get("standard_key") or "품명 확인 필요",
            "specification": legacy.get("category") or None,
            "unit": None,
            "price": None,
            "service_name": "사무동 신규내역 전처리",
            "source_file_id": None,
            "reference_date": None,
            "created_at": None,
            "source_set": "변경자료 신규내역",
            "evidence": legacy.get("restriction") or "79번 사무동 신규내역 단가검토 대기열",
        })

    # DB 결과가 없는 환경에서도 변경자료의 기준·변경 대조에서 새로 생긴
    # 내역을 단가 후보로 넘긴다. 비교 결과는 승인 전 검토값이며,
    # 타건물 자료와는 연결하지 않는다.
    if project_id == "project-g5-office" and not has_persisted_changed_candidates:
        # 전체 수량 분석(행별 산출근거 매칭)은 무겁기 때문에 여기서는
        # 최신 전처리 실행의 내역서 행만 조회해 신규 여부를 빠르게 판별한다.
        # 동일한 표준키가 기준자료에 있으면 신규가 아니며, 수량 값은
        # 단가 후보의 참고 문맥으로만 전달한다.
        latest_run = db.scalar(select(PreprocessingRun).where(PreprocessingRun.project_id == project_id, PreprocessingRun.source_kind == "raw_upload", PreprocessingRun.status == "completed").order_by(PreprocessingRun.created_at.desc()))
        if latest_run:
            try:
                source_ids = json.loads(latest_run.source_file_ids or "[]")
            except (TypeError, ValueError):
                source_ids = []
            current_sources = db.scalars(select(SourceFile).where(SourceFile.id.in_(source_ids))).all() if source_ids else []
            source_by_id = {source.id: source for source in current_sources}
            office = db.scalar(select(Building).where(Building.project_id == project_id, Building.name == "사무동"))
            allowed_ids = {source.id for source in current_sources if source.document_type == "estimate" and (office is None or source.building_id == office.id)}
            estimate_rows = db.scalars(select(StandardizedItem).where(StandardizedItem.project_id == project_id, StandardizedItem.source_file_id.in_(allowed_ids), StandardizedItem.item_kind == "estimate")).all() if allowed_ids else []
            current_rows = []
            for row in estimate_rows:
                try:
                    if json.loads(row.notes or "{}").get("run_id") == latest_run.id:
                        current_rows.append(row)
                except (TypeError, ValueError):
                    continue
            baseline_keys = {(comparison_key(row.normalized_name or row.item_name), comparison_key(row.specification), comparison_unit(row.unit)) for row in current_rows if source_by_id.get(row.source_file_id) and source_by_id[row.source_file_id].version_type == "기준"}
            seen_new_keys: set[tuple[str, str, str]] = set()
            for row in current_rows:
                source = source_by_id.get(row.source_file_id)
                if not source or source.version_type != "변경":
                    continue
                comparison_text = " ".join(str(value or "") for value in (row.item_name, row.specification, row.building_label, row.drawing_number))
                if is_non_office_scope(row.item_name, row.specification, row.building_label, row.drawing_number):
                    continue
                # Deleted/zero quantity rows and section subtotals are not
                # new purchasable items. They remain visible in quantity and
                # change reviews, but must not enter the unit-price queue.
                if row.quantity is None or row.quantity <= 0:
                    continue
                key = (comparison_key(row.normalized_name or row.item_name), comparison_key(row.specification), comparison_unit(row.unit))
                if not key[0] or key in baseline_keys or key in seen_new_keys:
                    continue
                seen_new_keys.add(key)
                item_key = row.item_code or row.normalized_name or row.item_name
                candidate_id = f"NEW-CMP-{hashlib.sha256(f'{project_id}|{row.id}'.encode('utf-8')).hexdigest()[:16]}"
                if candidate_id in seen_candidates:
                    continue
                append_payload({
                    "id": f"comparison-price-{candidate_id}",
                    "project_id": project_id,
                    "candidate_id": candidate_id,
                    "lookup_status": "변경 후 신규 · 수량 승인 전 단가 검토 대기",
                    "item_name": row.item_name or item_key,
                    "specification": row.specification or item_key,
                    "unit": row.unit,
                    "price": None,
                    "service_name": "기준·변경 대조 전처리",
                    "source_file_id": row.source_file_id,
                    "reference_date": None,
                    "created_at": None,
                    "source_set": "변경자료 신규내역",
                    "work_package": infer_work_package(row.item_name, row.specification),
                    "changed_quantity": str(row.quantity) if row.quantity is not None else None,
                    "evidence": f"변경자료 내역서 {source.original_name} · {row.source_row_ref or '원본 행'} · 기준자료 표준키 미발견",
                })
    return result


def _reference_catalog_path() -> Path:
    settings = get_settings()
    return settings.price_reference_csv or (settings.preprocessing_dir / "15_타건물_기계약단가_참고.csv")


def _reference_number(value: object) -> float | None:
    cleaned = re.sub(r"[^0-9.\-]", "", str(value or "").replace(",", ""))
    if not cleaned or cleaned in {".", "-"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _import_price_references(db: Session, project_id: str, requested_by: str | None) -> PriceReferenceImportResponse:
    path = _reference_catalog_path()
    if not path.exists():
        return PriceReferenceImportResponse(project_id=project_id, status="failed", source_path=str(path), error_message="저장 단가 참고 CSV를 찾을 수 없습니다.")
    from datetime import datetime, timezone

    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        source = db.scalar(select(SourceFile).where(SourceFile.project_id == project_id, SourceFile.file_path == str(path)))
        if not source:
            source = SourceFile(id=str(uuid4()), project_id=project_id, file_type="CSV", document_type="price_reference", original_name=path.name, file_path=str(path), sha256=digest, version_type="참고", uploaded_by=requested_by, is_valid=True)
            db.add(source)
            db.flush()
        else:
            source.sha256 = digest
            source.is_valid = True
        reference_date = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        imported = 0
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row_number, row in enumerate(csv.DictReader(handle), start=2):
                original_item = (row.get("original_item") or "").strip() or None
                standard_item = (row.get("standard_item") or "").strip() or None
                if not original_item and not standard_item:
                    continue
                stable_id = f"PRICE-REF-{hashlib.sha1(f'{project_id}|{digest}|{row_number}'.encode('utf-8')).hexdigest()[:24]}"
                record = db.get(PriceReference, stable_id)
                if not record:
                    record = PriceReference(id=stable_id, project_id=project_id)
                    db.add(record)
                record.source_file_id = source.id
                # 타건물 계약단가는 신규내역 비교용 참고자료로만 분류한다.
                # CSV의 dataset_use 설명은 provenance/restriction에 남기고 범위 키는 고정한다.
                record.source_scope = "other_building_reference"
                record.original_item = original_item
                record.standard_item = standard_item
                record.specification = (row.get("estimate_spec") or row.get("original_spec") or "").strip() or None
                record.unit = (row.get("standard_unit") or row.get("original_unit") or "").strip() or None
                record.building_label = (row.get("building") or "").strip() or None
                record.price = _reference_number(row.get("estimate_unit_price"))
                record.reference_date = reference_date
                dataset_use = (row.get("dataset_use") or "").strip()
                record.provenance = (row.get("provenance") or "").strip() or f"{path.name}:row-{row_number}"
                record.restriction = (row.get("restriction") or "").strip() or dataset_use or "타건물 참고자료·신규내역 후보 비교만 사용"
                record.is_active = True
                imported += 1
        source.source_row_ref = f"{path.name}:rows={imported}"
        db.add(AuditLog(id=str(uuid4()), user_id=requested_by, project_id=project_id, action="price_reference.import", entity_type="price_reference_catalog", entity_id=source.id, detail=json.dumps({"source_path": str(path), "sha256": digest, "imported_count": imported, "auto_apply": False}, ensure_ascii=False)))
        db.commit()
        return PriceReferenceImportResponse(project_id=project_id, status="completed", imported_count=imported, source_file_id=source.id, source_path=str(path))
    except (OSError, csv.Error, SQLAlchemyError) as error:
        db.rollback()
        return PriceReferenceImportResponse(project_id=project_id, status="failed", source_path=str(path), error_message=str(error)[:2000])


@app.get("/api/v1/projects/{project_id}/price-references", response_model=list[PriceReferenceResponse])
def project_price_references(project_id: str, q: str | None = None, include_other_projects: bool = True, limit: int = Query(200, ge=1, le=2000), db: Session = Depends(get_db), _: Principal = Depends(require_read)):
    require_project(project_id, db)
    query = select(PriceReference).where(PriceReference.is_active.is_(True))
    if not include_other_projects:
        query = query.where(PriceReference.project_id == project_id)
    else:
        query = query.where((PriceReference.project_id == project_id) | (PriceReference.source_scope == "other_building_reference"))
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where((PriceReference.original_item.ilike(pattern)) | (PriceReference.standard_item.ilike(pattern)) | (PriceReference.specification.ilike(pattern)))
    rows = db.scalars(query.order_by(PriceReference.created_at.desc()).limit(limit)).all()
    return [PriceReferenceResponse.model_validate(item, from_attributes=True) for item in rows]


@app.post("/api/v1/admin/projects/{project_id}/price-references/import", response_model=PriceReferenceImportResponse)
def import_price_references(project_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_authenticated)):
    require_project(project_id, db)
    if not principal.is_admin:
        raise HTTPException(403, "저장 단가 참고자료 적재는 전체 관리자만 수행할 수 있습니다.")
    return _import_price_references(db, project_id, principal.user_id)


@app.get("/api/v1/projects/{project_id}/prices/{result_id}/decision", response_model=PriceDecisionResponse)
def price_decision(project_id: str, result_id: str, db: Session = Depends(get_db), _: Principal = Depends(require_read)):
    require_project(project_id, db)
    decision = db.scalar(select(PriceApplicationDecision).where(PriceApplicationDecision.project_id == project_id, PriceApplicationDecision.price_result_id == result_id).order_by(PriceApplicationDecision.created_at.desc()))
    if not decision:
        raise HTTPException(404, "단가 적용 판단을 찾을 수 없습니다.")
    return PriceDecisionResponse.model_validate(decision, from_attributes=True)


@app.post("/api/v1/projects/{project_id}/prices/{result_id}/decision", response_model=PriceDecisionResponse)
def save_price_decision(project_id: str, result_id: str, request: PriceDecisionRequest, db: Session = Depends(get_db), principal: Principal = Depends(require_authenticated)):
    require_project(project_id, db)
    if not principal.is_admin and principal.department != "구매부서":
        raise HTTPException(403, "단가 적용 판단은 구매부서 또는 관리자만 처리할 수 있습니다.")
    result = db.scalar(select(ProcurementPriceResult).where(ProcurementPriceResult.id == result_id, ProcurementPriceResult.project_id == project_id))
    if not result:
        raise HTTPException(404, "단가 조회 결과를 찾을 수 없습니다.")
    if request.decision in {"적용 후보", "적용 예정"} and request.applied_price is None:
        raise HTTPException(422, "적용 후보·적용 예정 판단에는 적용 후보 단가가 필요합니다.")
    decision = db.scalar(select(PriceApplicationDecision).where(PriceApplicationDecision.project_id == project_id, PriceApplicationDecision.price_result_id == result_id).order_by(PriceApplicationDecision.created_at.desc()))
    if not decision:
        decision = PriceApplicationDecision(id=str(uuid4()), project_id=project_id, price_result_id=result_id, price_type="계약단가→유사품목→조달청", decision="미검토")
        db.add(decision)
    decision.decision = request.decision
    decision.applied_price = request.applied_price
    decision.reason = request.reason
    decision.approved_by = principal.user_id
    decision.evidence_ref = request.evidence_ref
    db.add(AuditLog(id=str(uuid4()), user_id=principal.user_id, project_id=project_id, action="price_application.review", entity_type="procurement_price_result", entity_id=result_id, detail=json.dumps({"decision": request.decision, "reason": request.reason, "auto_confirmed": False}, ensure_ascii=False)))
    db.commit()
    db.refresh(decision)
    return PriceDecisionResponse.model_validate(decision, from_attributes=True)


@app.get("/api/v1/projects/{project_id}/evidence", response_model=list[EvidenceResponse])
def project_evidence(project_id: str, warning_id: str | None = None, mapping_candidate_id: str | None = None, limit: int = Query(200, ge=1, le=2000), db: Session = Depends(get_db), _: Principal = Depends(require_read)):
    require_project(project_id, db)
    query = select(EvidenceReference).where(EvidenceReference.project_id == project_id)
    if warning_id:
        query = query.where(EvidenceReference.warning_id == warning_id)
    if mapping_candidate_id:
        query = query.where(EvidenceReference.mapping_candidate_id == mapping_candidate_id)
    query = query.order_by(EvidenceReference.created_at.desc()).limit(limit)
    return [EvidenceResponse.model_validate(item, from_attributes=True) for item in db.scalars(query).all()]


@app.post("/api/v1/projects/{project_id}/rules/run", response_model=JobResponse, status_code=202)
def enqueue_rule_run(project_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db), principal: Principal = Depends(require_authenticated)):
    project = require_project(project_id, db)
    if not principal.is_admin and "REVIEWER" not in principal.roles:
        raise HTTPException(403, "규칙 실행 권한이 없습니다.")
    job = RuleRunJob(id=str(uuid4()), project_id=project.id, requested_by=principal.user_id, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    background_tasks.add_task(execute_rule_job, job.id, project.id)
    return job_response(job)


@app.get("/api/v1/jobs/{job_id}", response_model=JobResponse)
def get_rule_job(job_id: str, db: Session = Depends(get_db), _: Principal = Depends(require_read)):
    job = db.get(RuleRunJob, job_id)
    if not job:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    return job_response(job)


def record_approval(project_id: str, source_id: str, request: DecisionRequest, db: Session, principal: Principal) -> ApprovalHistory:
    project = require_project(project_id, db)
    if not principal.is_admin and principal.department != request.department:
        raise HTTPException(403, "본인 부서의 승인만 처리할 수 있습니다.")
    if request.override_sequence and not principal.is_admin:
        raise HTTPException(403, "승인 순서 우회는 전체 관리자만 사용할 수 있습니다.")
    if request.override_sequence and not request.override_reason:
        raise HTTPException(422, "승인 순서 우회 사유가 필요합니다.")
    stage_index = APPROVAL_STAGES.index(request.department)
    if stage_index and not request.override_sequence:
        prior_stages = APPROVAL_STAGES[:stage_index]
        approved = set(db.scalars(select(ReviewDecision.department).where(ReviewDecision.project_id == project.id, ReviewDecision.source_id == source_id, ReviewDecision.decision == "승인", ReviewDecision.department.in_(prior_stages))).all())
        missing = [stage for stage in prior_stages if stage not in approved]
        if missing:
            raise HTTPException(409, f"선행 승인({', '.join(missing)})이 필요합니다.")
    record = ApprovalHistory(id=str(uuid4()), project_id=project.id, source_id=source_id, reviewer_user_id=principal.user_id, **request.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@app.post("/api/v1/projects/{project_id}/reviews/{source_id}/approvals", response_model=DecisionResponse, status_code=201)
def project_approval(project_id: str, source_id: str, request: DecisionRequest, db: Session = Depends(get_db), principal: Principal = Depends(require_authenticated)):
    record = record_approval(project_id, source_id, request, db, principal)
    return DecisionResponse.model_validate(record, from_attributes=True)


@app.post("/api/v1/projects/{project_id}/reviews/approvals/batch", response_model=BatchDecisionResponse)
def project_batch_approval(project_id: str, request: BatchDecisionRequest, db: Session = Depends(get_db), principal: Principal = Depends(require_authenticated)):
    """선택한 동일 단계 항목을 개별 검증하면서 일괄 처리한다."""
    project = require_project(project_id, db)
    if not principal.is_admin and principal.department != request.department:
        raise HTTPException(403, "본인 부서의 승인만 처리할 수 있습니다.")
    if request.override_sequence and not principal.is_admin:
        raise HTTPException(403, "승인 순서 우회는 전체 관리자만 사용할 수 있습니다.")
    if request.override_sequence and not request.override_reason:
        raise HTTPException(422, "승인 순서 우회 사유가 필요합니다.")

    results: list[BatchDecisionItemResponse] = []
    for source_id in dict.fromkeys(request.source_ids):
        try:
            with db.begin_nested():
                stage_index = APPROVAL_STAGES.index(request.department)
                if stage_index and not request.override_sequence:
                    prior_stages = APPROVAL_STAGES[:stage_index]
                    approved = set(db.scalars(select(ReviewDecision.department).where(ReviewDecision.project_id == project.id, ReviewDecision.source_id == source_id, ReviewDecision.decision == "승인", ReviewDecision.department.in_(prior_stages))).all())
                    missing = [stage for stage in prior_stages if stage not in approved]
                    if missing:
                        raise HTTPException(409, f"선행 승인({', '.join(missing)})이 필요합니다.")
                record = ApprovalHistory(id=str(uuid4()), project_id=project.id, source_id=source_id, reviewer_user_id=principal.user_id, department=request.department, decision=request.decision, comment=request.comment, reviewer=request.reviewer, evidence_ref=request.evidence_ref, override_sequence=request.override_sequence, override_reason=request.override_reason)
                db.add(record)
                db.flush()
                results.append(BatchDecisionItemResponse(source_id=source_id, status="succeeded", decision_id=record.id))
        except HTTPException as error:
            results.append(BatchDecisionItemResponse(source_id=source_id, status="failed", error_message=str(error.detail)))
        except SQLAlchemyError as error:
            results.append(BatchDecisionItemResponse(source_id=source_id, status="failed", error_message=f"저장 오류: {str(error)[:500]}"))

    succeeded = sum(item.status == "succeeded" for item in results)
    failed = len(results) - succeeded
    db.add(AuditLog(id=str(uuid4()), user_id=principal.user_id, project_id=project.id, action="approval.batch_request", entity_type="approval_batch", entity_id=str(uuid4()), detail=json.dumps({"department": request.department, "decision": request.decision, "requested_count": len(results), "succeeded_count": succeeded, "failed_count": failed, "source_ids": [item.source_id for item in results]}, ensure_ascii=False)))
    db.commit()
    return BatchDecisionResponse(project_id=project.id, department=request.department, decision=request.decision, requested_count=len(results), succeeded_count=succeeded, failed_count=failed, items=results)


@app.get("/api/v1/projects/{project_id}/review-history", response_model=list[DecisionResponse])
def project_review_history(project_id: str, source_id: str | None = None, db: Session = Depends(get_db), _: Principal = Depends(require_read)):
    require_project(project_id, db)
    query = select(ApprovalHistory).where(ApprovalHistory.project_id == project_id).order_by(ApprovalHistory.created_at.desc())
    if source_id:
        query = query.where(ApprovalHistory.source_id == source_id)
    return [DecisionResponse.model_validate(item, from_attributes=True) for item in db.scalars(query).all()]


@app.get("/api/v1/projects/{project_id}/audit-logs", response_model=list[AuditLogResponse])
def project_audit_logs(project_id: str, limit: int = Query(200, ge=1, le=2000), db: Session = Depends(get_db), _: Principal = Depends(require_read)):
    require_project(project_id, db)
    rows = db.scalars(select(AuditLog).where(AuditLog.project_id == project_id).order_by(AuditLog.created_at.desc()).limit(limit)).all()
    return [AuditLogResponse.model_validate(item, from_attributes=True) for item in rows]


def review_export_response(record: ReviewExport) -> ReviewExportResponse:
    def decode(value: str | None) -> dict[str, object]:
        try:
            parsed = json.loads(value or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return ReviewExportResponse(id=record.id, project_id=record.project_id, requested_by=record.requested_by, review_run_id=record.review_run_id, export_type=record.export_type, filter_snapshot=decode(record.filter_snapshot), approval_snapshot=decode(record.approval_snapshot), rule_version=record.rule_version, input_hash=record.input_hash, data_as_of=record.data_as_of, status=record.status, bundle_path=record.bundle_path, xlsx_path=record.xlsx_path, pdf_path=record.pdf_path, manifest_path=record.manifest_path, error_message=record.error_message, created_at=record.created_at)


@app.post("/api/v1/projects/{project_id}/reports", response_model=ReviewExportResponse, status_code=202)
def enqueue_review_export(project_id: str, background_tasks: BackgroundTasks, request: ReviewExportRequest | None = None, db: Session = Depends(get_db), principal: Principal = Depends(require_authenticated)):
    project = require_project(project_id, db)
    if not principal.is_admin and not ("REVIEWER" in principal.roles or principal.department in APPROVAL_STAGES):
        raise HTTPException(403, "검토 결과 패키지 생성 권한이 없습니다.")
    request = request or ReviewExportRequest()
    source_files = db.scalars(select(SourceFile).where(SourceFile.project_id == project_id, SourceFile.is_valid.is_(True)).order_by(SourceFile.created_at.asc())).all()
    input_hash = hashlib.sha256("|".join(f"{item.id}:{item.sha256 or ''}" for item in source_files).encode("utf-8")).hexdigest()
    approvals = db.scalars(select(ApprovalHistory).where(ApprovalHistory.project_id == project_id)).all()
    approval_snapshot = {department: {"total": sum(item.department == department for item in approvals), "approved": sum(item.department == department and item.decision == "승인" for item in approvals)} for department in APPROVAL_STAGES}
    filters = request.model_dump(exclude_none=True)
    from datetime import datetime, timezone
    record = ReviewExport(id=str(uuid4()), project_id=project.id, requested_by=principal.user_id, review_run_id=request.review_run_id, export_type="review_bundle", filter_snapshot=json.dumps(filters, ensure_ascii=False), approval_snapshot=json.dumps(approval_snapshot, ensure_ascii=False), rule_version="rule-engine-v1", input_hash=input_hash, data_as_of=datetime.now(timezone.utc), status="queued")
    db.add(record)
    db.add(AuditLog(id=str(uuid4()), user_id=principal.user_id, project_id=project.id, action="review_export.request", entity_type="review_export", entity_id=record.id, detail=json.dumps({"filters": filters, "export_type": "review_bundle"}, ensure_ascii=False)))
    db.commit()
    db.refresh(record)
    background_tasks.add_task(execute_review_export, record.id)
    return review_export_response(record)


@app.get("/api/v1/projects/{project_id}/reports/{export_id}", response_model=ReviewExportResponse)
def get_review_export(project_id: str, export_id: str, db: Session = Depends(get_db), _: Principal = Depends(require_read)):
    require_project(project_id, db)
    record = db.scalar(select(ReviewExport).where(ReviewExport.id == export_id, ReviewExport.project_id == project_id))
    if not record:
        raise HTTPException(404, "검토 결과 패키지를 찾을 수 없습니다.")
    return review_export_response(record)


@app.get("/api/v1/projects/{project_id}/reports/{export_id}/download")
def download_review_export(project_id: str, export_id: str, format: str = Query("bundle", pattern="^(bundle|xlsx|pdf|manifest)$"), db: Session = Depends(get_db), _: Principal = Depends(require_read)):
    require_project(project_id, db)
    record = db.scalar(select(ReviewExport).where(ReviewExport.id == export_id, ReviewExport.project_id == project_id))
    if not record:
        raise HTTPException(404, "검토 결과 패키지를 찾을 수 없습니다.")
    if record.status not in {"completed", "completed_with_warning"}:
        raise HTTPException(409, "검토 결과 패키지가 아직 준비되지 않았습니다.")
    paths = {"bundle": record.bundle_path, "xlsx": record.xlsx_path, "pdf": record.pdf_path, "manifest": record.manifest_path}
    path = Path(paths[format] or "")
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "요청한 결과 파일을 찾을 수 없습니다.")
    media_types = {"bundle": "application/zip", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "pdf": "application/pdf", "manifest": "application/json"}
    return FileResponse(path=str(path), filename=path.name, media_type=media_types[format])


def execute_price_lookup(result_id: str) -> None:
    db = SessionLocal()
    try:
        record = db.get(ProcurementPriceResult, result_id)
        if record:
            PriceLookupService().execute(record)
            try:
                payload = json.loads(record.raw_response or "{}")
            except json.JSONDecodeError:
                payload = {}
            fallback = payload.get("fallback") if isinstance(payload, dict) else None
            if isinstance(fallback, dict) and fallback.get("source_file"):
                source_path = str(fallback["source_file"])
                from datetime import datetime, timezone
                try:
                    record.reference_date = datetime.fromtimestamp(float(fallback.get("reference_date")), timezone.utc) if fallback.get("reference_date") else None
                except (TypeError, ValueError, OSError):
                    record.reference_date = None
                source = db.scalar(select(SourceFile).where(SourceFile.project_id == record.project_id, SourceFile.file_path == source_path))
                if not source:
                    source = SourceFile(id=str(uuid4()), project_id=record.project_id, file_type="CSV", document_type="official_reference", original_name=Path(source_path).name, file_path=source_path, version_type="참고", source_row_ref=f"{source_path}:{fallback.get('row')}")
                    db.add(source)
                    db.flush()
                record.source_file_id = source.id
            decision = db.scalar(select(PriceApplicationDecision).where(PriceApplicationDecision.price_result_id == record.id).order_by(PriceApplicationDecision.created_at.desc()))
            if decision:
                decision.reason = f"{record.lookup_status}; 구매부서 승인 전 자동 적용 금지"
            db.commit()
    finally:
        db.close()


def _price_match_text(value: str | None) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", (value or "").lower())


def _find_saved_price_reference(db: Session, project_id: str, request: PriceLookupRequest) -> PriceReference | None:
    item_key = _price_match_text(request.item_name)
    if not item_key:
        return None
    unit_key = _price_match_text(request.unit)
    spec_key = _price_match_text(request.specification)
    references = db.scalars(select(PriceReference).where(PriceReference.project_id == project_id, PriceReference.is_active.is_(True)).order_by(PriceReference.reference_date.desc().nullslast(), PriceReference.created_at.desc()).limit(2000)).all()
    ranked: list[tuple[int, PriceReference]] = []
    for reference in references:
        names = {_price_match_text(reference.original_item), _price_match_text(reference.standard_item)} - {""}
        if item_key not in names:
            continue
        score = 1
        if unit_key and _price_match_text(reference.unit) == unit_key:
            score += 2
        if spec_key and _price_match_text(reference.specification) == spec_key:
            score += 2
        if reference.price is not None:
            score += 1
        ranked.append((score, reference))
    return max(ranked, key=lambda pair: pair[0])[1] if ranked else None


@app.post("/api/v1/projects/{project_id}/prices/query", response_model=PriceLookupResponse, status_code=202)
def request_price_lookup(project_id: str, request: PriceLookupRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db), principal: Principal = Depends(require_authenticated)):
    project = require_project(project_id, db)
    if not principal.is_admin and principal.department != "구매부서":
        raise HTTPException(403, "조달청 단가 조회는 구매부서 또는 관리자만 요청할 수 있습니다.")
    candidate_id = request.candidate_id or f"API-{uuid4().hex[:12].upper()}"
    saved_reference = _find_saved_price_reference(db, project.id, request)
    if saved_reference:
        result = ProcurementPriceResult(
            id=str(uuid4()),
            project_id=project.id,
            candidate_id=candidate_id,
            service_name="저장 단가 참고",
            item_name=request.item_name,
            specification=request.specification,
            unit=request.unit,
            price=saved_reference.price,
            reference_date=saved_reference.reference_date,
            source_file_id=saved_reference.source_file_id,
            query_text=request.query_text,
            lookup_status="저장 참고 단가 후보 - 구매부서 승인 전 확정 금지",
            raw_response=json.dumps({"reference_id": saved_reference.id, "source_scope": saved_reference.source_scope, "building": saved_reference.building_label, "provenance": saved_reference.provenance, "restriction": saved_reference.restriction, "auto_apply": False}, ensure_ascii=False),
        )
    else:
        result = ProcurementPriceResult(id=str(uuid4()), project_id=project.id, candidate_id=candidate_id, service_name=get_settings().price_api_service_name, item_name=request.item_name, specification=request.specification, unit=request.unit, query_text=request.query_text, lookup_status="조회 요청 대기")
    db.add(result)
    # PostgreSQL must persist the lookup result before the decision row can
    # satisfy its foreign key to procurement_price_results.
    db.flush()
    decision_reason = "저장된 타건물 참고 단가 후보입니다. 구매부서 적용 판단 전 자동 적용 금지." if saved_reference else "조회 결과 수신 후 구매부서 적용 판단 필요"
    decision = PriceApplicationDecision(id=str(uuid4()), project_id=project.id, price_result_id=result.id, price_type="계약단가→유사품목→조달청", decision="미검토", reason=decision_reason)
    if saved_reference:
        decision.evidence_ref = f"price_reference:{saved_reference.id}; {saved_reference.provenance or '출처 미지정'}"
    db.add(decision)
    db.commit()
    db.refresh(result)
    if not saved_reference:
        background_tasks.add_task(execute_price_lookup, result.id)
    return PriceLookupResponse.model_validate(result, from_attributes=True)
