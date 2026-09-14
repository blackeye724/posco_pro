"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AppShell, PageMessage } from "../components/AppShell";
import { Dashboard, DrawingCandidate, PriceResult, QuantityAnalysis, createReviewExport, fetchDashboard, fetchDrawings, fetchJob, fetchPriceResults, fetchQuantityAnalysis, fetchReviewExport, runRules } from "../components/api";

const DATA_SCOPE_OPTIONS = ["전체", "운영 자료", "통합 테스트"] as const;
type DataScope = typeof DATA_SCOPE_OPTIONS[number];
function originFor(...values: unknown[]): "운영 자료" | "통합 테스트" {
  return values.filter(Boolean).join(" ").match(/integration-source|demo_|통합 테스트/i) ? "통합 테스트" : "운영 자료";
}

type ReviewStage = "initial" | "change" | "price";
const REVIEW_STAGES: Record<ReviewStage, { step: string; title: string; description: string; href: string }> = {
  initial: { step: "01 · 최초 자료", title: "내역서 ↔ 수량산출서", description: "사무동 기준자료의 내역서 행을 기준으로 산출수량·산식·원본 근거를 확인합니다.", href: "/quantities?sourceSet=기준자료" },
  change: { step: "02 · 설계변경", title: "기준 ↔ 변경 자료", description: "기준·변경 내역과 수량산출서, 도면 변경 후보를 연결해 변경 근거를 확인합니다.", href: "/drawings" },
  price: { step: "03 · 신규내역", title: "신규내역 단가 검토", description: "설계변경에서 확인된 신규내역만 참고단가·공식자료·API 후보를 비교합니다.", href: "/prices?sourceSet=변경자료" },
};

export default function Home() {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [analysis, setAnalysis] = useState<QuantityAnalysis | null>(null);
  const [drawingCount, setDrawingCount] = useState<number | null>(null);
  const [priceCount, setPriceCount] = useState<number | null>(null);
  const [drawingItems, setDrawingItems] = useState<DrawingCandidate[]>([]);
  const [priceItems, setPriceItems] = useState<PriceResult[]>([]);
  const [dataScope, setDataScope] = useState<DataScope>("전체");
  const [stage, setStage] = useState<ReviewStage>("initial");
  const [message, setMessage] = useState("원본 전처리 작업 상태를 불러오는 중입니다.");
  const [running, setRunning] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [showAllWorkPackages, setShowAllWorkPackages] = useState(false);

  const reload = () => Promise.all([fetchDashboard(), fetchQuantityAnalysis(undefined, "limit=5000"), fetchDrawings(undefined, 200), fetchPriceResults()]).then(([summary, quantity, drawings, prices]) => {
    setDashboard(summary);
    setAnalysis(quantity);
    setDrawingItems(drawings);
    setPriceItems(prices);
    setDrawingCount(drawings.length);
    setPriceCount(prices.length);
    setMessage("");
  }).catch(() => setMessage("API에 연결하지 못했습니다. 백엔드와 원본 전처리 작업 상태를 확인하세요."));
  useEffect(() => {
    const requestedScope = new URLSearchParams(window.location.search).get("dataScope");
    const requestedStage = new URLSearchParams(window.location.search).get("stage");
    if (requestedScope && DATA_SCOPE_OPTIONS.includes(requestedScope as DataScope)) setDataScope(requestedScope as DataScope);
    if (requestedStage === "initial" || requestedStage === "change" || requestedStage === "price") setStage(requestedStage);
    reload();
  }, []);

  function handleDataScopeChange(value: DataScope) {
    setDataScope(value);
    const params = new URLSearchParams(window.location.search);
    if (value === "전체") params.delete("dataScope"); else params.set("dataScope", value);
    const queryString = params.toString();
    window.history.replaceState({}, "", `${window.location.pathname}${queryString ? `?${queryString}` : ""}`);
  }

  function handleStageChange(value: ReviewStage) {
    setStage(value);
    const params = new URLSearchParams(window.location.search);
    params.set("stage", value);
    const queryString = params.toString();
    window.history.replaceState({}, "", `${window.location.pathname}?${queryString}`);
  }

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

  const resultOrder = ["불일치", "연결 근거 없음", "재검산 불가", "일치"];
  const visibleQuantityItems = (analysis?.items || []).filter(item => dataScope === "전체" || originFor(item.source_file, item.evidence) === dataScope);
  const stageQuantityItems = visibleQuantityItems.filter(item => stage === "initial" ? item.source_set === "기준자료" : stage === "change" ? item.source_set !== "기준자료" : false);
  const visibleDrawingItems = drawingItems.filter(item => dataScope === "전체" || originFor(item.baseline_file, item.changed_file, item.candidate_text) === dataScope);
  const visiblePriceItems = priceItems.filter(item => dataScope === "전체" || originFor(item.item_name, item.evidence, item.candidate_id) === dataScope);
  const resultRows = resultOrder.map(result => ({ result, count: stageQuantityItems.filter(item => (item.issue_type === "일치" ? "일치" : item.issue_type) === result).length }));
  const attentionTotal = resultRows.filter(row => row.result !== "일치").reduce((sum, row) => sum + row.count, 0);
  const scopeLabel = dataScope === "전체" ? (dashboard?.data_scope || "전체 자료") : `${dataScope}만 표시`;
  const workPackageRows = Object.entries(stageQuantityItems.reduce<Record<string, { total: number; attention: number }>>((groups, item) => {
    const workPackage = item.work_package || "미분류·원천 확인 필요";
    const current = groups[workPackage] || { total: 0, attention: 0 };
    current.total += 1;
    if (item.issue_type !== "일치") current.attention += 1;
    groups[workPackage] = current;
    return groups;
  }, {})).map(([workPackage, row]) => ({ workPackage, ...row }))
    .sort((left, right) => right.total - left.total);
  const visibleWorkPackageRows = showAllWorkPackages ? workPackageRows : workPackageRows.slice(0, 5);
  const maxWorkPackageTotal = Math.max(...workPackageRows.map(row => row.total), 1);

  const selectedStage = REVIEW_STAGES[stage];
  const stageCount = stage === "initial" ? visibleQuantityItems.filter(item => item.source_set === "기준자료").length : stage === "change" ? visibleQuantityItems.filter(item => item.source_set !== "기준자료").length + visibleDrawingItems.length : visiblePriceItems.length;
  const stageHref = dataScope === "전체" ? selectedStage.href : `${selectedStage.href}${selectedStage.href.includes("?") ? "&" : "?"}dataScope=${encodeURIComponent(dataScope)}`;

  return <AppShell eyebrow="PROJECT OVERVIEW / MVP" title="공사비 적정성 검토">
    <div className="review-scope-bar"><span>프로젝트 <strong>광양5 사무동</strong></span><span>건물 <strong>전체</strong></span><span>공사·공종 <strong>전체</strong></span><span>현재 회차 <code>{dashboard?.generated_from || "API 기준"}</code></span><label>자료 범위<select value={dataScope} onChange={event => handleDataScopeChange(event.target.value as DataScope)}>{DATA_SCOPE_OPTIONS.map(option => <option key={option}>{option}</option>)}</select></label><span className="scope-state" title="현재 화면에 적용된 자료 범위">{scopeLabel}{dataScope === "전체" && dashboard?.demo_source_count ? ` · 데모 원본 ${dashboard.demo_source_count}건 포함` : ""}</span><Link href={dataScope === "전체" ? `/review?stage=${stage}` : `/review?stage=${stage}&dataScope=${encodeURIComponent(dataScope)}`} className="scope-state scope-link">검토 대상 목록 열기 →</Link></div>
    <div className="dashboard-intro"><div><p className="lead">광양5 사무동 · 원본 업로드 기반 자동 전처리·규칙 검토</p><p className="muted-line">{dashboard?.generated_from || "원본 전처리 작업 상태 확인 중"}</p></div><div className="decision-actions"><button onClick={handleRuleRun} disabled={running}>{running ? "규칙 실행 중…" : "검토 규칙 실행"}</button><button className="button-secondary" onClick={handleExport} disabled={exporting}>{exporting ? "패키지 생성 중…" : "검토 결과 패키지 생성"}</button></div></div>
    {message && <PageMessage>{message}</PageMessage>}
    <section className="workflow-grid" aria-label="핵심 검토 흐름">
      {(Object.entries(REVIEW_STAGES) as [ReviewStage, typeof REVIEW_STAGES[ReviewStage]][]).map(([key, item]) => <button type="button" key={key} className={`workflow-card ${stage === key ? "selected" : ""}`} onClick={() => handleStageChange(key)} aria-pressed={stage === key}><span className="workflow-step">{item.step}</span><h3>{item.title}</h3><p>{item.description}</p><small>{key === "initial" ? `${visibleQuantityItems.filter(row => row.source_set === "기준자료").length.toLocaleString()}건 내역서 행` : key === "change" ? `${(visibleDrawingItems.length + visibleQuantityItems.filter(row => row.source_set !== "기준자료").length).toLocaleString()}건 변경 검토 대상` : `${visiblePriceItems.length.toLocaleString()}건 단가 후보`}</small></button>)}
    </section>
    <section className="panel stage-focus" aria-live="polite"><div><p className="eyebrow">현재 선택한 검토 흐름</p><h2>{selectedStage.title}</h2><p>{selectedStage.description}</p></div><div className="stage-focus-actions"><span><strong>{stageCount.toLocaleString()}건</strong><small>현재 자료 범위 검토 대상</small></span><Link className="button-link" href={stageHref}>검토 화면 열기 →</Link></div></section>
    {stage !== "price" && <section className="dashboard-insights">
      <div className="panel insight-panel">
        <div className="panel-head"><div><p className="eyebrow">REVIEW SIGNALS</p><h2>판정 결과 분포</h2></div><span className="review-only">내역서 행 기준</span></div>
        <p className="insight-caption">내역서 각 행을 기준으로 수량산출서 근거를 판정한 결과입니다. 일치도 포함해 전체 흐름을 확인할 수 있습니다.</p>
        <div className="signal-bars">{analysis ? resultRows.map(row => {
          const maximum = Math.max(...resultRows.map(item => item.count), 1);
          return <div className="signal-row" key={row.result}><div className="signal-label"><strong>{row.result}</strong><span>{row.count.toLocaleString()}건</span></div><div className="signal-track"><span style={{ width: `${Math.max((row.count / maximum) * 100, row.count ? 8 : 0)}%` }} /></div><small>{row.result === "일치" ? "검토 기준 충족" : "확인 또는 근거 보완 필요"}</small></div>;
        }) : <div className="insight-empty">내역서 행 판정 결과를 불러오는 중입니다.</div>}</div>
      </div>
      <div className="panel insight-panel insight-summary">
        <div className="panel-head"><div><p className="eyebrow">CONTROL SNAPSHOT</p><h2>검토 신호 요약</h2></div></div>
        <div className="signal-summary-list"><div><span>{stage === "initial" ? "기준 내역서 행" : "변경 내역서 행"}</span><strong>{analysis ? stageQuantityItems.length.toLocaleString() : "—"}건</strong></div><div><span>수량 확인 필요</span><strong>{analysis ? attentionTotal.toLocaleString() : "—"}건</strong></div><div><span>도면 변경 후보</span><strong>{drawingItems.length ? visibleDrawingItems.length.toLocaleString() : drawingCount == null ? "—" : drawingCount.toLocaleString()}건</strong></div><div><span>신규내역 단가</span><strong>{priceItems.length ? visiblePriceItems.length.toLocaleString() : priceCount == null ? "—" : priceCount.toLocaleString()}건</strong></div><div><span>현재 단계 수량 후보</span><strong>{analysis ? stageQuantityItems.length.toLocaleString() : "—"}건</strong></div></div>
        <p className="insight-note">일치·불일치 판정은 승인 전 검토 결과이며, 수량·금액·단가는 승인 전 확정하지 않습니다.</p>
      </div>
    </section>}
    {stage !== "price" && <section className="panel review-home-next"><div className="panel-head"><div><p className="eyebrow">NEXT REVIEW STEP</p><h2>세부 확인은 검토 대상 목록에서 이어서 진행합니다</h2><p className="insight-caption">현재 선택한 흐름의 판정 분포와 공종별 현황을 확인한 뒤, 원본 근거가 필요한 항목은 검토 대상 목록에서 상세 검토합니다.</p></div><Link href={dataScope === "전체" ? `/review?stage=${stage}` : `/review?stage=${stage}&dataScope=${encodeURIComponent(dataScope)}`} className="button-link">검토 대상 목록 열기 →</Link></div></section>}
    {stage === "initial" && <section className="panel preprocessing"><div className="panel-head"><div><p className="eyebrow">WORK PACKAGE STATUS</p><h2>공종별 검토 현황</h2></div><div className="work-package-status-actions"><span className="review-only">내역서 행 {analysis ? stageQuantityItems.length.toLocaleString() : "—"}건</span>{analysis && workPackageRows.length > 5 && <button type="button" className="button-secondary compact-toggle" onClick={() => setShowAllWorkPackages(value => !value)}>{showAllWorkPackages ? "상위 5개만 보기" : `전체 공종 보기 (${workPackageRows.length})`}</button>}</div></div><div className="work-package-legend" aria-label="공종 현황 그래프 범례"><span><i className="legend-total" /> 전체 내역</span><span><i className="legend-attention" /> 확인 필요</span></div><div className="work-package-list">{analysis ? visibleWorkPackageRows.map(row => { const attentionRate = row.total ? Math.round((row.attention / row.total) * 100) : 0; return <div className="work-package-row" key={row.workPackage}><div className="work-package-name"><strong>{row.workPackage}</strong><small>전체 {row.total.toLocaleString()}건 · 확인 필요 {row.attention.toLocaleString()}건</small></div><div className="work-package-track" aria-label={`${row.workPackage} 전체 ${row.total}건, 확인 필요 ${row.attention}건`}><span style={{ width: `${(row.total / maxWorkPackageTotal) * 100}%` }}><i style={{ width: `${attentionRate}%` }} /></span></div><b>{row.total.toLocaleString()}건</b></div>}) : <div className="insight-empty">공종별 집계를 불러오는 중입니다.</div>}</div>{analysis && workPackageRows.length > 5 && !showAllWorkPackages && <p className="work-package-note">물량이 많은 상위 5개 공종을 먼저 표시했습니다. 전체 공종은 버튼으로 펼칠 수 있습니다.</p>}</section>}
    {stage === "price" && <section className="panel stage-placeholder"><div className="panel-head"><div><p className="eyebrow">PRICE REVIEW</p><h2>변경 검토에서 생성된 신규내역만 단가를 검토합니다</h2><p className="insight-caption">현재 자료 범위에서 {visiblePriceItems.length.toLocaleString()}건의 단가 후보가 대기 중입니다. 참고단가 → 공식자료 → API 순서로 근거를 확인합니다.</p></div><Link className="button-link" href={stageHref}>단가 검토 열기 →</Link></div></section>}
  </AppShell>;
}
