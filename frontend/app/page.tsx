"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AppShell, PageMessage } from "../components/AppShell";
import { Dashboard, ProjectStatus, ReviewItem, createReviewExport, fetchDashboard, fetchJob, fetchProjectStatus, fetchReviews, fetchReviewExport, runRules } from "../components/api";

export default function Home() {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [status, setStatus] = useState<ProjectStatus | null>(null);
  const [reviews, setReviews] = useState<ReviewItem[]>([]);
  const [message, setMessage] = useState("원본 전처리 작업 상태를 불러오는 중입니다.");
  const [running, setRunning] = useState(false);
  const [exporting, setExporting] = useState(false);

  const reload = () => Promise.all([fetchDashboard(), fetchProjectStatus(), fetchReviews(8)]).then(([summary, current, queue]) => { setDashboard(summary); setStatus(current); setReviews(queue); setMessage(""); }).catch(() => setMessage("API에 연결하지 못했습니다. 백엔드와 원본 전처리 작업 상태를 확인하세요."));
  useEffect(() => { reload(); }, []);

  async function handleRuleRun() {
    setRunning(true);
    try {
      const job = await runRules();
      setMessage(`규칙 검토 작업을 접수했습니다. 작업 ID: ${job.id}`);
      for (let attempt = 0; attempt < 30; attempt += 1) {
        await new Promise(resolve => setTimeout(resolve, 1000));
        const current = await fetchJob(job.id);
        if (current.status === "completed") { setMessage(`${current.processed_count.toLocaleString()}건 규칙 검토가 완료되었습니다.`); break; }
        if (current.status === "failed") { setMessage(`규칙 검토 실패: ${current.error_message ?? "오류 내용을 확인하세요."}`); break; }
      }
      await reload();
    } catch { setMessage("규칙 검토 작업을 접수하지 못했습니다. 권한과 API 연결을 확인하세요."); }
    finally { setRunning(false); }
  }

  async function handleExport() {
    setExporting(true);
    try {
      const created = await createReviewExport();
      setMessage(`검토 결과 패키지 생성을 접수했습니다. export_id: ${created.id}`);
      for (let attempt = 0; attempt < 30; attempt += 1) {
        await new Promise(resolve => setTimeout(resolve, 1000));
        const current = await fetchReviewExport(created.project_id, created.id);
        if (current.status === "completed" || current.status === "completed_with_warning") { setMessage(`검토 결과 패키지가 생성되었습니다. 상태: ${current.status}.`); break; }
        if (current.status === "failed") { setMessage(`결과 패키지 생성 실패: ${current.error_message ?? "오류 내용을 확인하세요."}`); break; }
      }
    } catch { setMessage("검토 결과 패키지 생성을 접수하지 못했습니다. 권한과 API 연결을 확인하세요."); }
    finally { setExporting(false); }
  }

  const stats = status ? [
    { label: "검토 경고", value: status.warnings, href: "/quantities" },
    { label: "도면 변경 후보", value: status.drawing_candidates, href: "/drawings" },
    { label: "단가 검토 후보", value: status.price_candidates, href: "/prices" },
    { label: "승인 대기", value: status.pending_approvals, href: "/approvals" },
  ] : dashboard?.stats?.map(item => ({ label: item.label, value: item.value, href: "/review" })) || [];

  return <AppShell eyebrow="PROJECT OVERVIEW / MVP" title="공사비 적정성 검토">
    <div className="review-scope-bar"><span>프로젝트 <strong>광양5 사무동</strong></span><span>건물 <strong>전체</strong></span><span>공사·공종 <strong>전체</strong></span><span>현재 회차 <code>{dashboard?.generated_from || "API 기준"}</code></span><Link href="/review" className="scope-state scope-link">통합 검토 큐 열기 →</Link></div>
    <div className="dashboard-intro"><div><p className="lead">광양5 사무동 · 원본 업로드 기반 자동 전처리·규칙 검토</p><p className="muted-line">{dashboard?.generated_from || "원본 전처리 작업 상태 확인 중"}</p></div><div className="decision-actions"><button onClick={handleRuleRun} disabled={running}>{running ? "규칙 실행 중…" : "검토 규칙 실행"}</button><button className="button-secondary" onClick={handleExport} disabled={exporting}>{exporting ? "패키지 생성 중…" : "검토 결과 패키지 생성"}</button></div></div>
    {message && <PageMessage>{message}</PageMessage>}
    <section className="stats">{stats.map(stat => <Link className="stat-card" href={stat.href} key={stat.label}><span>{stat.label}</span><strong>{stat.value.toLocaleString()}</strong><small>검토 화면 열기 →</small></Link>)}</section>
    <section className="dashboard-insights">
      <div className="panel insight-panel">
        <div className="panel-head"><div><p className="eyebrow">REVIEW SIGNALS</p><h2>검토 대기 분포</h2></div><span className="review-only">실제 API 집계</span></div>
        <p className="insight-caption">영역별 대기 건수를 상대 막대로 표시합니다. 막대는 확정 금액이 아니라 검토 우선순위 신호입니다.</p>
        <div className="signal-bars">{dashboard?.pending_by_area?.length ? dashboard.pending_by_area.map(row => {
          const pending = Number(row.pending || 0);
          const maximum = Math.max(...dashboard.pending_by_area!.map(item => Number(item.pending || 0)), 1);
          return <div className="signal-row" key={String(row.area)}><div className="signal-label"><strong>{String(row.area)}</strong><span>{pending.toLocaleString()}건</span></div><div className="signal-track"><span style={{ width: `${Math.max((pending / maximum) * 100, pending ? 8 : 0)}%` }} /></div><small>{String(row.blocker || "검토 대기")}</small></div>;
        }) : <div className="insight-empty">원본 전처리 집계가 아직 없습니다.</div>}</div>
      </div>
      <div className="panel insight-panel insight-summary">
        <div className="panel-head"><div><p className="eyebrow">CONTROL SNAPSHOT</p><h2>검토 신호 요약</h2></div></div>
        <div className="signal-summary-list"><div><span>경고</span><strong>{status?.warnings ?? 0}건</strong></div><div><span>도면 변경 후보</span><strong>{status?.drawing_candidates ?? 0}건</strong></div><div><span>단가 후보</span><strong>{status?.price_candidates ?? 0}건</strong></div><div><span>승인 대기</span><strong>{status?.pending_approvals ?? 0}건</strong></div></div>
        <p className="insight-note">승인 전 수량·금액·단가는 후보 상태로 유지되며 자동 확정되지 않습니다.</p>
      </div>
    </section>
    <section className="dashboard-grid"><section className="panel"><div className="panel-head"><div><p className="eyebrow">PENDING REVIEW QUEUE</p><h2>우선 확인 항목</h2></div><Link href="/review" className="text-link">통합 큐 보기 →</Link></div><div className="table-wrap"><table className="dashboard-queue-table"><thead><tr><th>심각도</th><th>항목</th><th>도면</th><th>상태</th><th>담당</th></tr></thead><tbody>{reviews.map(item => <tr key={item.id}><td><span className={`severity ${item.severity}`}>{item.severity}</span></td><td><strong title={item.title}>{item.title}</strong><small title={`${item.id} · ${item.rule || "규칙 판정"}`}>{item.id} · {item.rule || "규칙 판정"}</small></td><td title={item.drawing_sheet || "-"}>{item.drawing_sheet || "-"}</td><td title={item.status}>{item.status}</td><td title={item.owner_department}>{item.owner_department}</td></tr>)}{!reviews.length && <tr><td colSpan={5}>표시할 검토 항목이 없습니다.</td></tr>}</tbody></table></div></section><section className="panel"><div className="panel-head"><div><p className="eyebrow">CONTROL RULE</p><h2>승인 통제</h2></div></div><div className="guardrail"><span className="guardrail-icon">!</span><p>{dashboard?.guardrail || "수량·금액·단가는 승인 전 자동 확정하지 않습니다."}</p></div><div className="mini-list"><div><span>수량 검산</span><strong>{status?.quantity_checks ?? 0}건</strong></div><div><span>연결 근거</span><strong>{status?.mapping_candidates ?? 0}건</strong></div><div><span>승인 이력</span><strong>{status?.approvals ?? 0}건</strong></div></div><Link href="/history" className="text-link">감사 추적 이력 →</Link></section></section>
    <section className="panel preprocessing"><div className="panel-head"><div><p className="eyebrow">PREPROCESSING STATUS</p><h2>원본 전처리 작업 현황</h2></div><span className="review-only">검토 대기 {dashboard?.pending_by_area?.reduce((sum, row) => sum + Number(row.pending || 0), 0).toLocaleString() || 0}건</span></div><div className="area-grid">{dashboard?.pending_by_area?.map(row => <div key={String(row.area)}><strong>{String(row.area)}</strong><b>{Number(row.pending || 0).toLocaleString()}건</b><small>{String(row.blocker || "검토 대기")}</small></div>)}</div></section>
  </AppShell>;
}
