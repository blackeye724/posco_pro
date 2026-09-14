"""전처리 결과 일부를 이용한 재현 가능한 MVP 샘플 시드.

원본 파일을 복사하지 않고, DB에 파일 경로와 원본 행 참조만 저장한다.
실행: python scripts/seed_sample.py
"""

import csv
import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.config import get_settings
from app.database import (
    ApprovalHistory,
    Base,
    Building,
    Department,
    DrawingChangeCandidate,
    EvidenceReference,
    MappingCandidate,
    PriceApplicationDecision,
    ProcurementPriceResult,
    Project,
    ReviewWarning,
    Role,
    SessionLocal,
    SourceFile,
    StandardizedItem,
    User,
    UserRole,
    WorkPackage,
    engine,
)
from app.services.auth import hash_password


def rows(root: Path, name: str) -> list[dict[str, str]]:
    path = root / name
    if path.exists():
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            return list(csv.DictReader(source))

    # Render와 같은 공개 환경에는 로컬 전처리 폴더가 포함되지 않을 수 있다.
    # 이 경우에도 로그인·대시보드·검토 흐름을 바로 확인할 수 있도록
    # 파일 의존성이 없는 최소 샘플 행을 사용한다.
    fallbacks: dict[str, list[dict[str, str]]] = {
        "72_사무동_검토우선순위_작업대기열.csv": [
            {
                "candidate_key": "ARCH-SAMPLE-001",
                "discipline": "건축공사",
                "candidate_text": "통합 테스트 검토 항목",
                "drawing_sheet": "DWG-201",
                "severity": "높음",
                "recommended_first_action": "기준·변경 도면과 수량 근거를 확인하세요.",
                "confidence": "0.95",
                "source_candidate_count": "1",
            }
        ],
        "79_사무동_구매부서_신규내역_단가검토_대기열.csv": [
            {
                "procurement_queue_id": "PRICE-NEW-SAMPLE-001",
                "standard_key": "건축공사|통합 테스트 검토 항목",
            }
        ],
    }
    if name in fallbacks:
        return fallbacks[name]
    raise FileNotFoundError(f"전처리 샘플 파일이 없습니다: {path}")


def get_or_create(db, model, key_field: str, key_value: str, **values):
    current = db.scalar(select(model).where(getattr(model, key_field) == key_value))
    if current:
        return current
    current = model(**values)
    db.add(current)
    db.flush()
    return current


def main() -> None:
    settings = get_settings()
    root = settings.preprocessing_dir
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        construction = get_or_create(db, Department, "code", "CONSTRUCTION", id="dept-construction", code="CONSTRUCTION", name="공사부서")
        design = get_or_create(db, Department, "code", "DESIGN", id="dept-design", code="DESIGN", name="설계부서")
        procurement = get_or_create(db, Department, "code", "PROCUREMENT", id="dept-procurement", code="PROCUREMENT", name="구매부서")
        management = get_or_create(db, Department, "code", "MANAGEMENT", id="dept-management", code="MANAGEMENT", name="관리자")
        reviewer_role = get_or_create(db, Role, "code", "REVIEWER", id="role-reviewer", code="REVIEWER", name="검토자")
        admin_role = get_or_create(db, Role, "code", "ADMIN", id="role-admin", code="ADMIN", name="관리자")

        def ensure_login(user_id: str, email: str, display_name: str, department_id: str, password_env: str, password_default: str, roles: list[Role]) -> User:
            user = get_or_create(db, User, "id", user_id, id=user_id, email=email, display_name=display_name, department_id=department_id)
            user.password_hash = user.password_hash or hash_password(os.getenv(password_env, password_default))
            user.must_change_password = True
            for role in roles:
                if not db.scalar(select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)):
                    db.add(UserRole(user_id=user.id, role_id=role.id))
            return user

        construction_user = ensure_login("pfc391", "pfc391@local", "공사부서 검토자", construction.id, "MVP_CONSTRUCTION_PASSWORD", "1234", [reviewer_role])
        design_user = ensure_login("pfe391", "pfe391@local", "설계부서 검토자", design.id, "MVP_DESIGN_PASSWORD", "12345", [reviewer_role])
        procurement_user = ensure_login("pfp391", "pfp391@local", "구매부서 검토자", procurement.id, "MVP_PROCUREMENT_PASSWORD", "123456", [reviewer_role])
        master_user = ensure_login("pfm391", "pfm391@local", "전체 관리자·승인권자", management.id, "MVP_MASTER_PASSWORD", "1234", [reviewer_role, admin_role])
        legacy_reviewer = db.get(User, "user-mvp-reviewer")
        if legacy_reviewer:
            # 이전 개발 시드 계정은 이력 보존을 위해 삭제하지 않고 로그인만 차단한다.
            legacy_reviewer.is_active = False
        project = get_or_create(db, Project, "project_code", "G5-OFFICE", id="project-g5-office", project_code="G5-OFFICE", name="광양5 사무동 투자사업", site="광양5", status="검토 중")
        building = db.scalar(select(Building).where(Building.project_id == project.id, Building.name == "사무동"))
        if not building:
            building = Building(id="building-g5-office", project_id=project.id, name="사무동", code="OFFICE")
            db.add(building)
            db.flush()
        work = db.scalar(select(WorkPackage).where(WorkPackage.project_id == project.id, WorkPackage.code == "ARCH"))
        if not work:
            work = WorkPackage(id="work-arch", project_id=project.id, building_id=building.id, code="ARCH", name="건축공사")
            db.add(work)
            db.flush()

        report_path = root / "119_최종_전처리_종합보고서.md"
        source = get_or_create(db, SourceFile, "id", "source-final-report", id="source-final-report", project_id=project.id, building_id=building.id, work_package_id=work.id, file_type="MD", document_type="preprocessing_report", original_name=report_path.name, file_path=str(report_path), version_type="기준", source_row_ref="119_최종_전처리_종합보고서.md")
        queue_rows = rows(root, "72_사무동_검토우선순위_작업대기열.csv")
        queue = queue_rows[0]
        item = db.scalar(select(StandardizedItem).where(StandardizedItem.item_code == queue.get("candidate_key"), StandardizedItem.project_id == project.id))
        if not item:
            item = StandardizedItem(id="item-sample-001", project_id=project.id, building_id=building.id, work_package_id=work.id, source_file_id=source.id, item_kind="estimate", item_code=queue.get("candidate_key"), discipline=queue.get("discipline"), item_name=queue.get("candidate_text") or "샘플 검토 항목", normalized_name=queue.get("candidate_key"), drawing_number=queue.get("drawing_sheet"), source_row_ref="72_사무동_검토우선순위_작업대기열.csv:2")
            db.add(item)
            db.flush()
        change = db.scalar(select(DrawingChangeCandidate).where(DrawingChangeCandidate.project_id == project.id, DrawingChangeCandidate.drawing_number == queue.get("drawing_sheet")))
        if not change:
            change = DrawingChangeCandidate(id="change-sample-001", project_id=project.id, discipline=queue.get("discipline"), drawing_number=queue.get("drawing_sheet"), candidate_text=queue.get("candidate_text"), status="근거 확인 대기", source_row_ref="72_사무동_검토우선순위_작업대기열.csv:2")
            db.add(change)
            db.flush()
        warning = db.scalar(select(ReviewWarning).where(ReviewWarning.id == "warning-sample-001"))
        if not warning:
            warning = ReviewWarning(id="warning-sample-001", project_id=project.id, standardized_item_id=item.id, drawing_change_candidate_id=change.id, warning_type="drawing_quantity_evidence", severity=queue.get("severity") or "높음", title=queue.get("candidate_text") or "근거 확인 필요", detail=queue.get("recommended_first_action"), status="근거 요청 대기", rule_code="EVIDENCE_REQUIRED")
            db.add(warning)
            db.flush()
        mapping = db.scalar(select(MappingCandidate).where(MappingCandidate.id == "mapping-sample-001"))
        if not mapping:
            mapping = MappingCandidate(id="mapping-sample-001", project_id=project.id, estimate_item_id=item.id, quantity_item_id=item.id, drawing_change_candidate_id=change.id, candidate_key=queue.get("candidate_key"), match_method="공종·도면번호 후보", confidence=queue.get("confidence"), status="검토 대기", source_candidate_count=int(queue.get("source_candidate_count") or 0))
            db.add(mapping)
            db.flush()
        if not db.scalar(select(EvidenceReference).where(EvidenceReference.id == "evidence-sample-001")):
            db.add(EvidenceReference(id="evidence-sample-001", project_id=project.id, mapping_candidate_id=mapping.id, warning_id=warning.id, source_file_id=source.id, evidence_type="preprocessing_row", file_path=str(root / "72_사무동_검토우선순위_작업대기열.csv"), row_ref="2", location_text=queue.get("drawing_sheet"), extraction_confidence=queue.get("confidence"), evidence_note="원천 근거 승인 전 자동 확정 금지"))

        price_queue = rows(root, "79_사무동_구매부서_신규내역_단가검토_대기열.csv")[0]
        price_id = "price-result-sample-001"
        if not db.scalar(select(ProcurementPriceResult).where(ProcurementPriceResult.id == price_id)):
            db.add(ProcurementPriceResult(id=price_id, project_id=project.id, standardized_item_id=item.id, candidate_id=price_queue.get("procurement_queue_id") or "PRICE-NEW-STR-0001", standard_key=price_queue.get("standard_key"), lookup_status="미검토 - 수량 확정 전 단가 적용 금지", service_name="PriceInfoService", source_file_id=source.id))
            # PostgreSQL must see the referenced price result before the
            # decision row is flushed; the two records have no ORM
            # relationship for SQLAlchemy to infer that ordering.
            db.flush()
            db.add(PriceApplicationDecision(id="price-decision-sample-001", project_id=project.id, standardized_item_id=item.id, price_result_id=price_id, price_type="계약단가 → 유사품목 → 조달청", decision="미검토", reason="수량·품목 승인 후 구매부서 판단 필요"))
        if not db.scalar(select(ApprovalHistory).where(ApprovalHistory.id == "approval-sample-001")):
            db.add(ApprovalHistory(id="approval-sample-001", project_id=project.id, source_id="FIND-건축-0001", department="공사부서", decision="추가 확인 필요", comment="도면·수량 근거 확인 대기 샘플", reviewer=construction_user.display_name, reviewer_user_id=construction_user.id, evidence_ref="evidence-sample-001"))
        db.commit()
        print("샘플 시드 완료: 프로젝트=G5-OFFICE, 검토항목=FIND-건축-0001")
    finally:
        db.close()


if __name__ == "__main__":
    main()
