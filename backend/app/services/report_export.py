"""검토 결과 스냅샷을 PDF·Excel·근거 Manifest 패키지로 내보내는 서비스."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..config import get_settings
from ..database import ApprovalHistory, DrawingChangeCandidate, EvidenceReference, ProcurementPriceResult, ReviewExport, ReviewWarning, SessionLocal, SourceFile


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _build_xlsx(path: Path, sheets: dict[str, tuple[list[str], list[dict[str, Any]]]]) -> str | None:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        return None
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet_name, (headers, rows) in sheets.items():
        sheet = workbook.create_sheet(sheet_name[:31])
        sheet.append(headers)
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F4E78")
        for row in rows:
            sheet.append([row.get(header) for header in headers])
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for column in sheet.columns:
            width = min(60, max(12, max(len(str(cell.value or "")) for cell in column) + 2))
            sheet.column_dimensions[column[0].column_letter].width = width
    workbook.save(path)
    return str(path)


def _build_pdf(path: Path, project_id: str, counts: dict[str, int], pending: int) -> str:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError:
        html_path = path.with_suffix(".html")
        html_path.write_text(f"<html><meta charset='utf-8'><h1>공사비 적정성 검토 요약</h1><p>프로젝트: {html.escape(project_id)}</p><p>생성일: {datetime.now(timezone.utc).isoformat()}</p><p>검토 대기: {pending}건</p><pre>{html.escape(_json(counts))}</pre></html>", encoding="utf-8")
        return str(html_path)
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setTitle("공사비 적정성 검토 요약")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(48, 800, "공사비 적정성 검토 요약")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(48, 780, f"Project: {project_id}")
    pdf.drawString(48, 765, f"Generated: {datetime.now(timezone.utc).isoformat()}")
    y = 720
    for label, value in [("Warnings", counts["warnings"]), ("Drawing candidates", counts["drawings"]), ("Price results", counts["prices"]), ("Approvals", counts["approvals"]), ("Pending review", pending)]:
        pdf.drawString(60, y, f"{label}: {value}")
        y -= 20
    pdf.drawString(48, y - 10, "Pre-approval quantities, amounts and prices are candidates only.")
    pdf.save()
    return str(path)


def execute_review_export(export_id: str) -> None:
    db = SessionLocal()
    export = db.get(ReviewExport, export_id)
    try:
        if not export:
            return
        export.status = "running"
        db.commit()
        project_dir = get_settings().export_dir / export.project_id / export.id
        project_dir.mkdir(parents=True, exist_ok=True)
        filters = json.loads(export.filter_snapshot or "{}")
        warning_query = select(ReviewWarning).where(ReviewWarning.project_id == export.project_id)
        if filters.get("warning_severity"):
            warning_query = warning_query.where(ReviewWarning.severity == filters["warning_severity"])
        if filters.get("status"):
            warning_query = warning_query.where(ReviewWarning.status == filters["status"])
        warnings = db.scalars(warning_query.order_by(ReviewWarning.created_at.desc())).all()
        drawings = db.scalars(select(DrawingChangeCandidate).where(DrawingChangeCandidate.project_id == export.project_id).order_by(DrawingChangeCandidate.created_at.desc())).all()
        prices = db.scalars(select(ProcurementPriceResult).where(ProcurementPriceResult.project_id == export.project_id).order_by(ProcurementPriceResult.created_at.desc())).all()
        approvals = db.scalars(select(ApprovalHistory).where(ApprovalHistory.project_id == export.project_id).order_by(ApprovalHistory.created_at.desc())).all()
        evidence = db.scalars(select(EvidenceReference).where(EvidenceReference.project_id == export.project_id).order_by(EvidenceReference.created_at.desc())).all()
        files = db.scalars(select(SourceFile).where(SourceFile.project_id == export.project_id).order_by(SourceFile.created_at.desc())).all()

        warning_rows = [{"id": item.id, "warning_type": item.warning_type, "severity": item.severity, "title": item.title, "detail": item.detail, "status": item.status, "rule_code": item.rule_code, "created_at": item.created_at.isoformat() if item.created_at else ""} for item in warnings]
        drawing_rows = [{"id": item.id, "drawing_number": item.drawing_number, "change_type": item.change_type, "location_ref": item.location_ref, "confidence": item.confidence, "status": item.status, "baseline_revision": item.baseline_revision, "changed_revision": item.changed_revision, "sheet_number": item.sheet_number} for item in drawings]
        price_rows = [{"id": item.id, "candidate_id": item.candidate_id, "item_name": item.item_name, "specification": item.specification, "unit": item.unit, "price": float(item.price) if item.price is not None else None, "lookup_status": item.lookup_status, "service_name": item.service_name, "source_file_id": item.source_file_id, "reference_date": item.reference_date.isoformat() if item.reference_date else ""} for item in prices]
        approval_rows = [{"id": item.id, "source_id": item.source_id, "department": item.department, "decision": item.decision, "reviewer": item.reviewer, "comment": item.comment, "evidence_ref": item.evidence_ref, "created_at": item.created_at.isoformat() if item.created_at else ""} for item in approvals]
        evidence_rows = [{"id": item.id, "warning_id": item.warning_id, "source_file_id": item.source_file_id, "file_path": item.file_path, "sheet_name": item.sheet_name, "row_ref": item.row_ref, "cell_ref": item.cell_ref, "page_number": item.page_number, "location_text": item.location_text, "extraction_confidence": item.extraction_confidence, "evidence_note": item.evidence_note} for item in evidence]
        file_rows = [{"id": item.id, "original_name": item.original_name, "file_path": item.file_path, "sha256": item.sha256, "document_type": item.document_type, "revision": item.revision, "drawing_number": item.drawing_number, "sheet_name": item.sheet_name, "is_valid": item.is_valid} for item in files]
        counts = {"warnings": len(warning_rows), "drawings": len(drawing_rows), "prices": len(price_rows), "approvals": len(approval_rows), "evidence": len(evidence_rows)}
        pending = sum(1 for item in warning_rows if item["status"] not in {"승인", "확정"})
        manifest = {"export_id": export.id, "project_id": export.project_id, "review_run_id": export.review_run_id, "filter_snapshot": filters, "approval_snapshot": json.loads(export.approval_snapshot or "{}"), "rule_version": export.rule_version, "input_hash": export.input_hash, "data_as_of": export.data_as_of.isoformat() if export.data_as_of else None, "counts": counts, "approval_before_final": True, "source_files": file_rows, "evidence": evidence_rows}
        manifest_path = project_dir / "evidence_manifest.json"
        manifest_path.write_text(_json(manifest), encoding="utf-8")
        _write_csv(project_dir / "warnings.csv", list(warning_rows[0].keys()) if warning_rows else ["id", "warning_type", "severity", "title", "detail", "status", "rule_code", "created_at"], warning_rows)
        _write_csv(project_dir / "drawings.csv", list(drawing_rows[0].keys()) if drawing_rows else ["id", "drawing_number", "change_type", "location_ref", "confidence", "status", "baseline_revision", "changed_revision", "sheet_number"], drawing_rows)
        _write_csv(project_dir / "prices.csv", list(price_rows[0].keys()) if price_rows else ["id", "candidate_id", "item_name", "specification", "unit", "price", "lookup_status", "service_name", "source_file_id", "reference_date"], price_rows)
        _write_csv(project_dir / "approvals.csv", list(approval_rows[0].keys()) if approval_rows else ["id", "source_id", "department", "decision", "reviewer", "comment", "evidence_ref", "created_at"], approval_rows)
        _write_csv(project_dir / "evidence.csv", list(evidence_rows[0].keys()) if evidence_rows else ["id", "warning_id", "source_file_id", "file_path", "sheet_name", "row_ref", "cell_ref", "page_number", "location_text", "extraction_confidence", "evidence_note"], evidence_rows)
        _write_csv(project_dir / "source_files.csv", list(file_rows[0].keys()) if file_rows else ["id", "original_name", "file_path", "sha256", "document_type", "revision", "drawing_number", "sheet_name", "is_valid"], file_rows)
        sheets = {
            "요약": (["항목", "값", "표시 기준"], [{"항목": "프로젝트", "값": export.project_id, "표시 기준": "검토 스냅샷"}, {"항목": "경고", "값": len(warning_rows), "표시 기준": "승인 전 후보"}, {"항목": "도면 변경 후보", "값": len(drawing_rows), "표시 기준": "근거 확인 대기"}, {"항목": "단가 후보", "값": len(price_rows), "표시 기준": "구매부서 판단 대기"}, {"항목": "검토 대기", "값": pending, "표시 기준": "자동 확정 금지"}]),
            "도면변경": (list(drawing_rows[0].keys()) if drawing_rows else ["id"], drawing_rows),
            "수량산식": (["warning_id", "title", "detail", "status", "rule_code"], [{"warning_id": row["id"], "title": row["title"], "detail": row["detail"], "status": row["status"], "rule_code": row["rule_code"]} for row in warning_rows if "quantity" in row["warning_type"] or "formula" in row["warning_type"]]),
            "내역연결": (["warning_id", "title", "detail", "status"], [{"warning_id": row["id"], "title": row["title"], "detail": row["detail"], "status": row["status"]} for row in warning_rows if "mapping" in row["warning_type"] or "mismatch" in row["warning_type"]]),
            "단가검토": (list(price_rows[0].keys()) if price_rows else ["id"], price_rows),
            "승인이력": (list(approval_rows[0].keys()) if approval_rows else ["id"], approval_rows),
            "원본근거": (list(evidence_rows[0].keys()) if evidence_rows else ["id"], evidence_rows),
            "데이터정의": (["필드", "설명"], [{"필드": "price", "설명": "승인 전 후보 단가이며 확정값이 아님"}, {"필드": "source_file_id", "설명": "원본 파일 추적 ID"}, {"필드": "export_id", "설명": "동일 검토 시점 스냅샷 ID"}]),
        }
        xlsx_path = _build_xlsx(project_dir / "review_result.xlsx", sheets)
        pdf_path = _build_pdf(project_dir / "summary.pdf", export.project_id, counts, pending)
        bundle_path = project_dir / "review_result_bundle.zip"
        with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as bundle:
            for child in project_dir.iterdir():
                if child.name != bundle_path.name and child.is_file():
                    bundle.write(child, child.name)
        export.bundle_path = str(bundle_path)
        export.xlsx_path = xlsx_path
        export.pdf_path = pdf_path
        export.manifest_path = str(manifest_path)
        export.status = "completed" if xlsx_path and pdf_path.endswith(".pdf") else "completed_with_warning"
        if not xlsx_path or not pdf_path.endswith(".pdf"):
            export.error_message = "선택적 Excel/PDF 라이브러리가 없어 일부 출력이 CSV 또는 HTML로 대체되었습니다. 운영 이미지에서는 requirements.txt 의 패키지를 설치하세요."
        db.commit()
    except Exception as error:
        db.rollback()
        export = db.get(ReviewExport, export_id)
        if export:
            export.status = "failed"
            export.error_message = str(error)[:2000]
            db.commit()
    finally:
        db.close()
