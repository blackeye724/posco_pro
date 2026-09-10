"use client";

import { useEffect, useState } from "react";
import { AppShell, PageMessage } from "../../components/AppShell";
import { Approval, AuditLog, PROJECT_ID, ReviewExport, createReviewExport, downloadReviewExport, fetchAuditLogs, fetchHistory, fetchReviewExport } from "../../components/api";

function formatDate(value?: string) { return value ? new Date(value).toLocaleString("ko-KR") : "시간 미지정"; }

export default function HistoryPage() {
  const [items, setItems] = useState<Approval[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [exportJob, setExportJob] = useState<ReviewExport | null>(null);
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [downloading, setDownloading] = useState("");

  useEffect(() => { Promise.all([fetchHistory(PROJECT_ID), fetchAuditLogs(PROJECT_ID)]).then(([historyRows, auditRows]) => { setItems(historyRows); setAuditLogs(auditRows); }).catch(() => setNotice("검토 이력과 감사 로그를 불러오지 못했습니다." )).finally(() => setLoading(false)); }, []);

  async function createExport() {
    setExporting(true); setNotice("");
    try { const created = await createReviewExport(PROJECT_ID); setExportJob(created); setNotice(`결과 패키지 생성을 접수했습니다. export_id: ${created.id}`); for (let attempt = 0; attempt < 30; attempt += 1) { await new Promise(resolve => setTimeout(resolve, 1000)); const current = await fetchReviewExport(PROJECT_ID, created.id); setExportJob(current); if (current.status === "completed" || current.status === "completed_with_warning" || current.status === "failed") break; } } catch (error) { setNotice(error instanceof Error ? error.message : "결과 패키지 생성에 실패했습니다."); } finally { setExporting(false); }
  }
  async function download(format: "bundle" | "xlsx" | "pdf" | "manifest") {
    if (!exportJob || !["completed", "completed_with_warning"].includes(exportJob.status)) return;
    setDownloading(format); try { const blob = await downloadReviewExport(PROJECT_ID, exportJob.id, format); const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = `cost-review-${exportJob.id}.${format === "bundle" ? "zip" : format}`; link.click(); URL.revokeObjectURL(url); } catch (error) { setNotice(error instanceof Error ? error.message : "결과 파일 다운로드에 실패했습니다."); } finally { setDownloading(""); }
  }

  return <AppShell eyebrow="AUDIT TRAIL / REPORTS" title="검토 이력·감사 로그">
    <div className="history-scope-bar"><span>프로젝트 <strong>광양5 사무동</strong></span><span>이력 <strong>읽기 전용</strong></span><span className="candidate-state">결과 패키지 스냅샷</span></div>
    <p className="lead">승인·수정 요청·반려·오탐 판정과 시스템 행위를 시간순으로 확인합니다. 보고서는 한 검토 스냅샷으로 생성되며 승인 전 값은 후보 상태로 표시됩니다.</p>
    {notice && <PageMessage tone={notice.includes("실패") || notice.includes("찾을") ? "danger" : "info"}>{notice}</PageMessage>}
    <section className="history-kpis"><div><span>검토 이력</span><strong>{loading ? "—" : items.length}</strong><small>부서별 승인·판정</small></div><div><span>감사 로그</span><strong>{loading ? "—" : auditLogs.length}</strong><small>상태 변경·요청 추적</small></div><div><span>결과 패키지</span><strong>{exportJob ? exportJob.status : "대기"}</strong><small>export_id 스냅샷</small></div></section>
    <section className="history-grid"><section className="panel"><div className="panel-head"><div><p className="eyebrow">DECISION LOG</p><h2>{items.length}건의 검토 이력</h2></div><span className="review-only">감사 추적</span></div><div className="timeline">{loading ? <div className="review-loading">검토 이력을 불러오는 중입니다…</div> : items.map(item => <article className="timeline-row" key={item.id}><div className="timeline-mark"/><div className="timeline-content"><div className="row-kicker"><span className="tag">{item.department}</span><strong>{item.decision}</strong><span>{formatDate(item.created_at)}</span></div><h3>{item.source_id}</h3><p>{item.comment}</p><small>검토자 {item.reviewer} {item.reviewer_user_id ? `· 계정 ${item.reviewer_user_id}` : ""}</small></div></article>)}{!loading && !items.length && <div className="empty">아직 기록된 검토 이력이 없습니다.</div>}</div></section><section className="panel audit-log-panel"><div className="panel-head"><div><p className="eyebrow">SYSTEM AUDIT</p><h2>감사 로그</h2></div><span className="review-only">append-only</span></div><div className="audit-list">{auditLogs.slice(0, 80).map(log => <article className="audit-row" key={log.id}><div><strong>{log.action}</strong><small>{log.entity_type} · {log.entity_id || "대상 미지정"}</small></div><time>{formatDate(log.created_at)}</time><p>{log.detail || "상세 사유 없음"}</p><small>행위자 {log.user_id || "확인 필요"}</small></article>)}{!loading && !auditLogs.length && <div className="empty">감사 로그가 없습니다.</div>}</div></section></section>
    <section className="panel export-panel"><div className="panel-head"><div><p className="eyebrow">REVIEW EXPORT</p><h2>검토 결과 패키지</h2><small>동일 export_id의 PDF·Excel·Manifest·원본 링크 목록을 생성합니다.</small></div><button type="button" onClick={createExport} disabled={exporting}>{exporting ? "생성 중…" : "결과 패키지 생성"}</button></div>{exportJob && <div className="export-status"><div><strong>export_id</strong><code>{exportJob.id}</code></div><div><strong>상태</strong><span className={`export-badge ${exportJob.status}`}>{exportJob.status}</span></div><div><strong>기준 시각</strong><span>{formatDate(exportJob.data_as_of)}</span></div>{exportJob.error_message && <p>{exportJob.error_message}</p>}</div>}{exportJob && ["completed", "completed_with_warning"].includes(exportJob.status) && <div className="export-downloads"><button type="button" className="button-secondary" disabled={Boolean(downloading)} onClick={() => download("bundle")}>{downloading === "bundle" ? "준비 중…" : "전체 묶음 다운로드"}</button><button type="button" className="button-secondary" disabled={Boolean(downloading)} onClick={() => download("xlsx")}>{downloading === "xlsx" ? "준비 중…" : "Excel"}</button><button type="button" className="button-secondary" disabled={Boolean(downloading)} onClick={() => download("pdf")}>{downloading === "pdf" ? "준비 중…" : "PDF"}</button><button type="button" className="button-secondary" disabled={Boolean(downloading)} onClick={() => download("manifest")}>{downloading === "manifest" ? "준비 중…" : "Manifest"}</button></div>}</section>
  </AppShell>;
}
