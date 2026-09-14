"use client";

import { useEffect, useState } from "react";
import { AppShell, PageMessage } from "../../components/AppShell";
import { Approval, AuditLog, PROJECT_ID, ReviewExport, ScopeOption, createReviewExport, downloadReviewExport, fetchAuditLogs, fetchHistory, fetchProjectScope, fetchReviewExport } from "../../components/api";

function formatDate(value?: string) { return value ? new Date(value).toLocaleString("ko-KR") : "시간 미지정"; }

const actionLabels: Record<string, string> = {
  "price_application.review": "단가 적용 판단 기록",
  "source_file.duplicate_upload": "중복 파일 업로드 감지",
  "source_file.logical_delete": "원본 파일 삭제 처리",
  "source_file.bulk_import": "원본 파일 일괄 등록",
  "quantity.mapping.select_candidate": "수량 후보 연결 선택",
  "price_reference.import": "참고 단가 가져오기",
  "approval.batch_request": "승인 일괄 요청",
  "review_export.request": "검토 결과 패키지 생성 요청",
};
const entityLabels: Record<string, string> = { procurement_price_result: "단가 후보", source_file: "원본 파일", mapping_candidate: "수량 매핑 후보", price_reference_catalog: "참고 단가 목록", approval_batch: "승인 일괄 요청", review_export: "검토 결과 패키지" };
const detailLabels: Record<string, string> = { decision: "판정", reason: "판정 사유", comment: "메모", department: "담당 부서", original_name: "파일명", source_path: "출처 경로", imported_count: "가져온 단가", requested_count: "요청 건수", succeeded_count: "성공 건수", failed_count: "실패 건수", reused: "기존 파일 재사용", auto_confirmed: "자동 확정", auto_apply: "자동 적용", export_type: "패키지 유형", version_type: "자료 구분", preprocessing: "전처리 방식", api_skipped: "외부 API 조회" };

function shortId(value?: string) { if (!value) return "대상 미지정"; return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value; }
function readableValue(key: string, value: unknown): string { if (typeof value === "boolean") return value ? "예" : "아니오"; if (Array.isArray(value)) return `${value.length}개 항목`; if (value && typeof value === "object") return "세부 조건 있음"; if (key.endsWith("_count")) return `${String(value)}건`; return String(value ?? "-"); }
function detailLines(detail?: string): string[] {
  if (!detail) return ["추가 설명 없음"];
  try {
    const parsed: unknown = JSON.parse(detail);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return [detail];
    const object = parsed as Record<string, unknown>;
    const lines = Object.entries(object).filter(([key]) => !["sha256", "source_ids", "filters"].includes(key)).map(([key, value]) => `${detailLabels[key] || key}: ${readableValue(key, value)}`);
    if (object.filters) lines.push("적용 필터: 결과 패키지 생성 조건 저장됨");
    return lines.length ? lines : ["추가 설명 없음"];
  } catch { return [detail]; }
}
function historyTarget(item: Approval) { return item.comment?.includes("통합 테스트") ? "통합 테스트 검토 항목" : "검토 대상 항목"; }

export default function HistoryPage() {
  const [items, setItems] = useState<Approval[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [exportJob, setExportJob] = useState<ReviewExport | null>(null);
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [refreshingExport, setRefreshingExport] = useState(false);
  const [downloading, setDownloading] = useState("");
  const [buildings, setBuildings] = useState<ScopeOption[]>([]);
  const [workPackages, setWorkPackages] = useState<ScopeOption[]>([]);
  const [filters, setFilters] = useState({ review_stage: "", building_id: "", work_package_id: "", status: "", warning_severity: "" });

  useEffect(() => { Promise.all([fetchHistory(PROJECT_ID), fetchAuditLogs(PROJECT_ID), fetchProjectScope(PROJECT_ID)]).then(([historyRows, auditRows, scope]) => { setItems(historyRows); setAuditLogs(auditRows); setBuildings(scope.buildings || []); setWorkPackages(scope.work_packages || []); }).catch(() => setNotice("검토 이력과 감사 로그를 불러오지 못했습니다." )).finally(() => setLoading(false)); }, []);

  function setFilter(key: keyof typeof filters, value: string) { setFilters(previous => ({ ...previous, [key]: value })); }

  async function createExport() {
    setExporting(true); setNotice("");
    try {
      const body = Object.fromEntries(Object.entries(filters).filter(([, value]) => value)) as Parameters<typeof createReviewExport>[1];
      const created = await createReviewExport(PROJECT_ID, body);
      setExportJob(created); setNotice(`결과 패키지 생성을 접수했습니다. export_id: ${created.id}`);
      let finished = false;
      for (let attempt = 0; attempt < 45; attempt += 1) {
        await new Promise(resolve => setTimeout(resolve, 1000));
        try {
          const current = await fetchReviewExport(PROJECT_ID, created.id);
          setExportJob(current);
          if (["completed", "completed_with_warning", "failed"].includes(current.status)) { finished = true; break; }
        } catch { /* 일시적인 연결 오류는 다음 주기에 재시도한다. */ }
      }
      if (!finished) setNotice("패키지 생성이 계속 진행 중입니다. ‘상태 새로고침’으로 완료 여부를 확인하세요.");
    } catch (error) { setNotice(error instanceof Error ? error.message : "결과 패키지 생성에 실패했습니다."); } finally { setExporting(false); }
  }
  async function refreshExport() {
    if (!exportJob) return;
    setRefreshingExport(true);
    try { const current = await fetchReviewExport(PROJECT_ID, exportJob.id); setExportJob(current); setNotice(["completed", "completed_with_warning"].includes(current.status) ? "검토 결과 패키지가 준비되었습니다. 파일 형식을 선택해 다운로드하세요." : current.status === "failed" ? `결과 패키지 생성 실패: ${current.error_message ?? "오류 내용을 확인하세요."}` : "아직 생성 중입니다. 잠시 후 다시 확인하세요."); } catch (error) { setNotice(error instanceof Error ? error.message : "패키지 상태를 확인하지 못했습니다."); } finally { setRefreshingExport(false); }
  }
  async function download(format: "bundle" | "xlsx" | "pdf" | "manifest") {
    if (!exportJob || !["completed", "completed_with_warning"].includes(exportJob.status)) return;
    setDownloading(format); try { const blob = await downloadReviewExport(PROJECT_ID, exportJob.id, format); const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = `cost-review-${exportJob.id}.${format === "bundle" ? "zip" : format}`; link.click(); URL.revokeObjectURL(url); } catch (error) { setNotice(error instanceof Error ? error.message : "결과 파일 다운로드에 실패했습니다."); } finally { setDownloading(""); }
  }

  return <AppShell eyebrow="AUDIT TRAIL / REPORTS" title="검토 이력·감사 로그">
    <div className="history-scope-bar"><span>프로젝트 <strong>광양5 사무동</strong></span><span>이력 <strong>읽기 전용</strong></span><span className="candidate-state">결과 패키지 스냅샷</span></div>
    <p className="lead">승인·수정 요청·반려·오탐 판정과 시스템 행위를 시간순으로 확인합니다. 내부 코드 대신 사람이 읽을 수 있는 작업명과 사유를 표시합니다.</p>
    {notice && <PageMessage tone={notice.includes("실패") || notice.includes("찾을") ? "danger" : "info"}>{notice}</PageMessage>}
    <section className="history-kpis"><div><span>검토 이력</span><strong>{loading ? "—" : items.length}</strong><small>부서별 승인·판정</small></div><div><span>감사 로그</span><strong>{loading ? "—" : auditLogs.length}</strong><small>상태 변경·요청 추적</small></div><div><span>결과 패키지</span><strong>{exportJob ? exportJob.status : "대기"}</strong><small>export_id 스냅샷</small></div></section>
    <section className="history-grid"><section className="panel history-decision-panel"><div className="panel-head"><div><p className="eyebrow">DECISION LOG</p><h2>{items.length}건의 검토 이력</h2></div><span className="review-only">판정 기록</span></div><div className="timeline history-timeline">{loading ? <div className="review-loading">검토 이력을 불러오는 중입니다…</div> : items.map(item => <article className="timeline-row" key={item.id}><div className="timeline-mark"/><div className="timeline-content"><div className="row-kicker"><span className="tag">{item.department}</span><strong>{item.decision}</strong><span>{formatDate(item.created_at)}</span></div><h3>{historyTarget(item)}</h3><p>{item.comment || "판정 메모 없음"}</p><small>검토자 {item.reviewer || "확인 필요"}{item.reviewer_user_id ? ` · 계정 ${item.reviewer_user_id}` : ""}</small><small className="timeline-id">추적 ID {shortId(item.source_id)}</small></div></article>)}{!loading && !items.length && <div className="empty">아직 기록된 검토 이력이 없습니다.</div>}</div></section><section className="panel audit-log-panel"><div className="panel-head"><div><p className="eyebrow">SYSTEM AUDIT</p><h2>감사 로그</h2></div><span className="review-only">변경 추적</span></div><div className="audit-list">{auditLogs.slice(0, 80).map(log => <article className="audit-row" key={log.id}><div><strong>{actionLabels[log.action] || log.action}</strong><small>{entityLabels[log.entity_type] || log.entity_type} · 추적 ID {shortId(log.entity_id)}</small></div><time>{formatDate(log.created_at)}</time><ul className="audit-detail">{detailLines(log.detail).map((line, index) => <li key={`${log.id}-${index}`}>{line}</li>)}</ul><small className="audit-actor">행위자 {log.user_id || "확인 필요"}</small></article>)}{!loading && !auditLogs.length && <div className="empty">감사 로그가 없습니다.</div>}</div></section></section>
    <section className="panel export-panel"><div className="panel-head"><div><p className="eyebrow">REVIEW EXPORT</p><h2>검토 결과 패키지</h2><small>검토 조건을 선택하면 동일 기준의 PDF·Excel·Manifest를 생성합니다.</small></div><div className="export-actions"><button type="button" onClick={createExport} disabled={exporting}>{exporting ? "생성 중…" : "결과 패키지 생성"}</button>{exportJob && !["completed", "completed_with_warning", "failed"].includes(exportJob.status) && <button type="button" className="button-secondary" onClick={refreshExport} disabled={refreshingExport}>{refreshingExport ? "확인 중…" : "상태 새로고침"}</button>}</div></div><div className="export-filters"><label>검토 단계<select value={filters.review_stage} onChange={event => setFilter("review_stage", event.target.value)}><option value="">전체 단계</option><option value="initial">최초자료 검토</option><option value="change">설계변경 검토</option><option value="price">신규내역 단가</option></select></label><label>건물<select value={filters.building_id} onChange={event => setFilter("building_id", event.target.value)}><option value="">전체 건물</option>{buildings.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><label>공종<select value={filters.work_package_id} onChange={event => setFilter("work_package_id", event.target.value)}><option value="">전체 공종</option>{workPackages.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><label>상태<select value={filters.status} onChange={event => setFilter("status", event.target.value)}><option value="">전체 상태</option><option value="검토 대기">검토 대기</option><option value="승인">승인</option><option value="반려">반려</option><option value="추가 확인 필요">추가 확인 필요</option></select></label><label>심각도<select value={filters.warning_severity} onChange={event => setFilter("warning_severity", event.target.value)}><option value="">전체 심각도</option><option value="높음">높음</option><option value="중간">중간</option><option value="낮음">낮음</option></select></label></div>{exportJob && <div className="export-status"><div><strong>export_id</strong><code>{exportJob.id}</code></div><div><strong>상태</strong><span className={`export-badge ${exportJob.status}`}>{exportJob.status}</span></div><div><strong>기준 시각</strong><span>{formatDate(exportJob.data_as_of)}</span></div>{exportJob.error_message && <p>{exportJob.error_message}</p>}</div>}{exportJob && ["completed", "completed_with_warning"].includes(exportJob.status) && <div className="export-downloads"><button type="button" className="button-secondary" disabled={Boolean(downloading)} onClick={() => download("bundle")}>{downloading === "bundle" ? "준비 중…" : "전체 묶음 다운로드"}</button><button type="button" className="button-secondary" disabled={Boolean(downloading)} onClick={() => download("xlsx")}>{downloading === "xlsx" ? "준비 중…" : "Excel"}</button><button type="button" className="button-secondary" disabled={Boolean(downloading)} onClick={() => download("pdf")}>{downloading === "pdf" ? "준비 중…" : "PDF"}</button><button type="button" className="button-secondary" disabled={Boolean(downloading)} onClick={() => download("manifest")}>{downloading === "manifest" ? "준비 중…" : "Manifest"}</button></div>}</section>
  </AppShell>;
}
