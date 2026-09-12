"""Run the end-to-end MVP flow against a running local API.

The script is intentionally dependency-light so it can be used in CI or a
developer shell. It creates temporary design/procurement reviewer accounts in
the configured database, then exercises the same HTTP boundaries as Next.js.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import Department, Role, SessionLocal, User, UserRole


# Local Next.js development uses the API on 8001 by default (see
# frontend/components/api.ts). Docker deployments still pass 8000 explicitly
# through INTEGRATION_API_BASE when the compose API is used.
API = os.getenv("INTEGRATION_API_BASE", "http://127.0.0.1:8001/api/v1")
HEALTH = os.getenv("INTEGRATION_HEALTH_URL", API.removesuffix("/api/v1") + "/health")
PROJECT_ID = os.getenv("NEXT_PUBLIC_PROJECT_ID", "project-g5-office")
INTEGRATION_USER = os.getenv("INTEGRATION_USER_ID", "pfc391")


def request(path: str, method: str = "GET", body: dict | None = None, user: str | None = None, anonymous: bool = False) -> tuple[int, dict | list]:
    headers = {"Content-Type": "application/json"}
    if user or not anonymous:
        headers["X-User-Id"] = user or INTEGRATION_USER
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    try:
        # Quantity analysis is intentionally row-based and may scan the full
        # office workbook set after a new upload. Keep the smoke client from
        # declaring a healthy asynchronous/API path failed at 20 seconds.
        with urlopen(Request(f"{API}{path}", method=method, data=payload, headers=headers), timeout=120) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> {error.code}: {detail}") from error
    except URLError as error:
        raise RuntimeError(f"API unavailable: {error}") from error


def download_request(path: str, user: str | None = None) -> tuple[int, bytes, str]:
    headers = {"Accept": "*/*"}
    if user:
        headers["X-User-Id"] = user
    try:
        with urlopen(Request(f"{API}{path}", method="GET", headers=headers), timeout=30) as response:
            return response.status, response.read(), response.headers.get("Content-Type", "")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {path} -> {error.code}: {detail}") from error
    except URLError as error:
        raise RuntimeError(f"API unavailable: {error}") from error


def multipart_request(path: str, filename: str, content: bytes, fields: dict[str, str], user: str | None = None) -> tuple[int, dict]:
    boundary = f"----cost-review-{uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend([f"--{boundary}\r\n".encode(), f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(), value.encode(), b"\r\n"])
    chunks.extend([f"--{boundary}\r\n".encode(), f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(), b"Content-Type: application/octet-stream\r\n\r\n", content, b"\r\n", f"--{boundary}--\r\n".encode()])
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if user:
        headers["X-User-Id"] = user
    with urlopen(Request(f"{API}{path}", method="POST", data=b"".join(chunks), headers=headers), timeout=30) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def multipart_expect_error(path: str, filename: str, content: bytes, fields: dict[str, str], user: str | None, expected: int) -> None:
    try:
        multipart_request(path, filename, content, fields, user)
    except HTTPError as error:
        error.read()
        assert error.code == expected, f"expected {expected}, got {error.code}"
        return
    raise AssertionError(f"expected multipart HTTP {expected}: {path}")


def expect_error(path: str, method: str = "GET", body: dict | None = None, user: str | None = None, expected: int = 400, anonymous: bool = False) -> None:
    try:
        request(path, method, body, user, anonymous=anonymous)
    except RuntimeError as error:
        assert f"-> {expected}:" in str(error), str(error)
        return
    raise AssertionError(f"expected HTTP {expected}: {method} {path}")


def ensure_reviewer(user_id: str, email: str, display_name: str, department_code: str, department_name: str) -> None:
    db = SessionLocal()
    try:
        department = db.query(Department).filter(Department.code == department_code).one_or_none()
        if department is None:
            department = Department(id=f"dept-{department_code.lower()}", code=department_code, name=department_name)
            db.add(department)
            db.flush()
        user = db.get(User, user_id)
        if user is None:
            user = User(id=user_id, email=email, display_name=display_name, department_id=department.id)
            db.add(user)
        reviewer = db.query(Role).filter(Role.code == "REVIEWER").one()
        if db.query(UserRole).filter(UserRole.user_id == user_id, UserRole.role_id == reviewer.id).one_or_none() is None:
            db.add(UserRole(user_id=user_id, role_id=reviewer.id))
        db.commit()
    finally:
        db.close()


def main() -> None:
    try:
        with urlopen(HEALTH, timeout=10) as response:
            health = json.loads(response.read().decode("utf-8"))
        assert response.status == 200 and health.get("database") == "ok", f"health check failed: {health}"
    except (HTTPError, URLError, AssertionError) as error:
        raise RuntimeError(f"서비스/PostgreSQL health check failed: {error}") from error

    ensure_reviewer("user-design-reviewer", "design.review@example.com", "설계 검토자", "DESIGN", "설계부서")
    ensure_reviewer("user-procurement-reviewer", "procurement.review@example.com", "구매 검토자", "PROCUREMENT", "구매부서")

    checks: list[str] = []
    status, projects = request("/projects")
    assert status == 200 and any(project["id"] == PROJECT_ID for project in projects), "project list" 
    checks.append("projects")
    expect_error("/projects/not-a-real-project", expected=404)
    expect_error(f"/projects/{PROJECT_ID}/warnings?limit=0", expected=422)
    checks.append("api-error-validation")

    large_pdf = b"%PDF-1.7\n" + (b"integration-test" * 200_000)
    upload_fields = {"document_type": "drawing", "version_type": "기준", "revision": "Rev.0", "drawing_number": "A-INT-001", "sheet_name": "합본"}
    status, uploaded = multipart_request(f"/projects/{PROJECT_ID}/files", "integration-source.pdf", large_pdf, upload_fields, "pfc391")
    assert status == 201 and uploaded["is_valid"] and uploaded["sha256"] and uploaded["file_path"] and Path(uploaded["file_path"]).exists(), "source upload"
    # 동일 SHA-256 재업로드는 원본을 중복 저장하지 않고 기존 전처리 실행을 재사용한다.
    status, duplicate = multipart_request(f"/projects/{PROJECT_ID}/files", "integration-source.pdf", large_pdf, upload_fields, "pfc391")
    assert status == 201 and duplicate["id"] == uploaded["id"] and duplicate["sha256"] == uploaded["sha256"] and duplicate["preprocessing_run_id"] == uploaded["preprocessing_run_id"], "duplicate upload reuse"
    # 동일 논리 식별자(문서 유형/도면번호/시트/Rev.)의 다른 해시는 별도 원본으로 보존하고 충돌 경고를 남긴다.
    # Keep the conflict payload unique across repeated local smoke runs so it
    # cannot be treated as a duplicate upload from a previous run.
    conflict_content = b"%PDF-1.7\nconflicting-revision-content-" + uuid4().hex.encode("ascii")
    status, conflict_upload = multipart_request(f"/projects/{PROJECT_ID}/files", "integration-source-conflict.pdf", conflict_content, upload_fields, "pfc391")
    assert status == 201 and conflict_upload["id"] != uploaded["id"] and conflict_upload["sha256"] != uploaded["sha256"], "revision conflict source preserved"
    _, conflict_warnings = request(f"/projects/{PROJECT_ID}/warnings?warning_type=same_revision_content_conflict&limit=10")
    assert any(item["warning_type"] == "same_revision_content_conflict" for item in conflict_warnings), "revision conflict warning"
    checks.append("duplicate-reuse-and-revision-conflict")
    for filename, signature, document_type in (("integration-source.dwg", b"AC1032", "drawing"), ("integration-source.xlsx", b"PK\x03\x04", "estimate")):
        status, result = multipart_request(f"/projects/{PROJECT_ID}/files", filename, signature + b"integration-test", {"document_type": document_type, "version_type": "기준"}, "pfc391")
        assert status == 201 and result["is_valid"], f"upload {filename}"
    multipart_expect_error(f"/projects/{PROJECT_ID}/files", "integration-source.exe", b"MZ", {}, "pfc391", 415)
    checks.append("upload-validation-and-traceability")

    preprocessing_run_id = uploaded.get("preprocessing_run_id")
    assert preprocessing_run_id and uploaded.get("preprocessing_status") in {"queued", "running", "completed"}, "raw preprocessing job created"
    current_preprocessing = None
    # A raw run includes every validated source in the project, not only the
    # tiny smoke files. Allow enough time for the real office workbook set.
    preprocessing_timeout = max(30, int(os.getenv("INTEGRATION_PREPROCESS_TIMEOUT", "300")))
    for _ in range(preprocessing_timeout * 2):
        time.sleep(0.5)
        _, current_preprocessing = request(f"/projects/{PROJECT_ID}/preprocessing")
        runs = current_preprocessing.get("runs", [])
        matching = [run for run in runs if run["id"] == preprocessing_run_id]
        if matching and matching[0]["status"] in {"completed", "failed"}:
            break
    assert current_preprocessing and any(run["id"] == preprocessing_run_id and run["status"] == "completed" for run in current_preprocessing.get("runs", [])), f"raw preprocessing failed: {current_preprocessing}"
    matching_run = next(run for run in current_preprocessing["runs"] if run["id"] == preprocessing_run_id)
    assert matching_run.get("max_attempts", 0) >= 5, f"retry policy not applied: {matching_run}"
    checks.append("raw-preprocessing-job")

    status, records = request(f"/projects/{PROJECT_ID}/preprocessing/runs/{preprocessing_run_id}/records?limit=20")
    assert status == 200 and isinstance(records, list), "selective preprocessing records"
    checks.append("selective-preprocessing-load")

    for path in (f"/projects/{PROJECT_ID}/preprocessing", f"/projects/{PROJECT_ID}/warnings", f"/projects/{PROJECT_ID}/drawings/changes", f"/projects/{PROJECT_ID}/quantities", f"/projects/{PROJECT_ID}/mappings", f"/projects/{PROJECT_ID}/prices/results", f"/projects/{PROJECT_ID}/evidence"):
        status, _ = request(path)
        assert status == 200, path
    checks.append("preprocessing-and-queries")

    expect_error(f"/projects/{PROJECT_ID}/reviews/test-source/approvals", "POST", {"department": "공사부서", "decision": "승인", "reviewer": "anonymous", "comment": "인증 누락"}, expected=401, anonymous=True)
    expect_error(f"/projects/{PROJECT_ID}/prices/query", "POST", {"item_name": "권한 테스트"}, "user-design-reviewer", expected=403)
    checks.append("auth-and-department-permissions")

    status, job = request(f"/projects/{PROJECT_ID}/rules/run", "POST", user="pfc391")
    assert status == 202 and job["status"] in {"queued", "running", "completed"}, "rule job accepted"
    for _ in range(40):
        time.sleep(0.25)
        _, current = request(f"/jobs/{job['id']}")
        if current["status"] in {"completed", "failed"}:
            break
    assert current["status"] == "completed", f"rule job failed: {current}"
    checks.append("rule-job")

    _, warnings = request(f"/projects/{PROJECT_ID}/warnings?limit=1")
    assert warnings, "warning generation"
    source_id = warnings[0]["id"]
    for user, department in (("pfc391", "공사부서"), ("pfe391", "설계부서")):
        status, _ = request(f"/projects/{PROJECT_ID}/reviews/{source_id}/approvals", "POST", {"department": department, "decision": "승인", "reviewer": user, "comment": "통합 테스트 근거 확인"}, user)
        assert status == 201, f"approval {department}"
    status, _ = request(f"/projects/{PROJECT_ID}/reviews/{source_id}/approvals", "POST", {"department": "구매부서", "decision": "승인", "reviewer": "user-procurement-reviewer", "comment": "통합 테스트 단가 검토 대기"}, "user-procurement-reviewer")
    assert status == 201, "approval 구매부서"
    checks.append("sequential-approvals")

    status, price = request(f"/projects/{PROJECT_ID}/prices/query", "POST", {"item_name": "통합 테스트 신규내역", "specification": "검증용 규격", "unit": "식"}, "user-procurement-reviewer")
    assert status == 202 and price["lookup_status"] and isinstance(price["lookup_status"], str), "price request"
    status, decision = request(f"/projects/{PROJECT_ID}/prices/{price['id']}/decision", "POST", {"decision": "적용 보류", "reason": "통합 테스트: 원본 단가 근거 추가 확인"}, "user-procurement-reviewer")
    assert status == 200 and decision["decision"] == "적용 보류", "price decision"
    checks.append("price-request")

    # 새 충돌 경고를 대상으로 선택 일괄승인의 성공/실패 집계를 확인한다.
    conflict_warning_id = next(item["id"] for item in conflict_warnings if item["warning_type"] == "same_revision_content_conflict")
    status, batch = request(f"/projects/{PROJECT_ID}/reviews/approvals/batch", "POST", {"source_ids": [conflict_warning_id], "department": "공사부서", "decision": "승인", "reviewer": "pfc391", "comment": "통합 테스트 일괄 승인"}, "pfc391")
    assert status == 200 and batch["requested_count"] == 1 and batch["succeeded_count"] == 1 and batch["items"][0]["status"] == "succeeded", "batch approval"
    checks.append("batch-approval")

    # 같은 export_id 스냅샷으로 결과 패키지를 만들고, 상태 조회와 다운로드까지 검증한다.
    status, export = request(f"/projects/{PROJECT_ID}/reports", "POST", {"warning_severity": "중간"}, "pfc391")
    assert status == 202 and export["status"] in {"queued", "running", "completed", "completed_with_warning"}, "report export accepted"
    export_id = export["id"]
    export_status = export
    # CSV/HTML fallback export can take longer than the short API job checks,
    # especially when the office run contains tens of thousands of rows.
    # Allow up to one minute before declaring the asynchronous export stuck.
    for _ in range(240):
        if export_status["status"] in {"completed", "completed_with_warning", "failed"}:
            break
        time.sleep(0.25)
        _, export_status = request(f"/projects/{PROJECT_ID}/reports/{export_id}", user="pfc391")
    assert export_status["status"] in {"completed", "completed_with_warning"} and export_status["bundle_path"] and export_status["manifest_path"], f"report export failed: {export_status}"
    for format_name in ("bundle", "manifest"):
        download_status, payload, content_type = download_request(f"/projects/{PROJECT_ID}/reports/{export_id}/download?format={format_name}", "pfc391")
        assert download_status == 200 and payload and content_type, f"report download {format_name}"
    checks.append("report-export-and-download")

    _, history = request(f"/projects/{PROJECT_ID}/review-history")
    assert len([item for item in history if item["source_id"] == source_id]) >= 3, "approval history persisted"
    _, status_snapshot = request(f"/projects/{PROJECT_ID}")
    assert status_snapshot["approvals"] >= 3, "project status re-query"
    checks.append("history-requery")
    print(json.dumps({"ok": True, "project_id": PROJECT_ID, "checks": checks, "warning_id": source_id, "rule_job_id": job["id"], "price_result_id": price["id"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
