"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell, CandidateBadge, EvidenceBlock, PageMessage } from "../../components/AppShell";
import { Approval, DrawingCandidate, Evidence, PriceResult, PROJECT_ID, QuantityAnalysisItem, Warning, fetchDrawings, fetchEvidence, fetchHistory, fetchPriceResults, fetchQuantityAnalysis } from "../../components/api";

const statusOptions = ["전체 상태", "승인 대기", "추가 확인 필요", "적용 보류", "승인"];
const dataScopeOptions = ["전체", "운영 자료", "통합 테스트"] as const;
type DataScope = typeof dataScopeOptions[number];
type ReviewStage = "all" | "initial" | "change" | "price";
const stageLabels: Record<ReviewStage, string> = { all: "전체 확인 요청", initial: "01 최초자료", change: "02 설계변경", price: "03 신규내역 단가" };
function originFor(...values: unknown[]): "운영 자료" | "통합 테스트" {
  return values.filter(Boolean).join(" ").match(/integration-source|demo_|통합 테스트/i) ? "통합 테스트" : "운영 자료";
}

function queueItem(item: QuantityAnalysisItem): Warning {
  return { id: item.id, project_id: item.project_id, warning_type: item.issue_type, severity: item.severity, title: item.item_text || item.item_key || "내역 항목", detail: item.required_action || item.judgement, expected_value: item.original_value, actual_value: item.recalculated_value, status: item.status || "승인 대기", rule_code: item.rule_version, data_origin: originFor(item.source_file, item.evidence), stage: item.source_set === "기준자료" ? "initial" : "change" };
}

function queueDrawing(item: DrawingCandidate): Warning {
  return { id: `drawing:${item.id}`, project_id: item.project_id, warning_type: "도면 변경 후보", severity: item.confidence === "높음" ? "높음" : item.confidence === "중간" ? "중간" : "낮음", title: item.drawing_number || item.sheet_number || "도면번호 확인 필요", detail: item.candidate_text || item.next_action || "변경 도면 근거 확인이 필요합니다.", status: "추가 확인 필요", rule_code: "DRAWING_DELTA_CANDIDATE", data_origin: originFor(item.baseline_file, item.changed_file, item.candidate_text), stage: "change" };
}

function queuePrice(item: PriceResult): Warning {
  const status = item.lookup_status?.includes("보류") || item.lookup_status?.includes("미검토") ? "추가 확인 필요" : "승인 대기";
  return { id: `price:${item.id}`, project_id: item.project_id, warning_type: "신규내역 단가 후보", severity: "중간", title: item.item_name || item.candidate_id || "신규내역 품명 확인 필요", detail: item.lookup_status || "단가 출처와 기준일 확인이 필요합니다.", expected_value: item.price == null ? undefined : `${item.price}`, status, rule_code: "NEW_ITEM_PRICE_CANDIDATE", data_origin: originFor(item.item_name, item.evidence, item.candidate_id), stage: "price" };
}

function shortFileName(path?: string) {
  if (!path) return "원본 파일명 확인 필요";
  return path.split(/[\\/]/).pop() || path;
}

export default function ReviewQueuePage() {
  const router = useRouter();
  const [warnings, setWarnings] = useState<Warning[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [history, setHistory] = useState<Approval[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [status, setStatus] = useState("전체 상태");
  const [dataScope, setDataScope] = useState<DataScope>("전체");
  const [stage, setStage] = useState<ReviewStage>("all");
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const requestedScope = new URLSearchParams(window.location.search).get("dataScope");
    const requestedStage = new URLSearchParams(window.location.search).get("stage");
    if (requestedScope && dataScopeOptions.includes(requestedScope as DataScope)) setDataScope(requestedScope as DataScope);
    if (requestedStage === "initial" || requestedStage === "change" || requestedStage === "price") setStage(requestedStage);
    Promise.all([fetchQuantityAnalysis(PROJECT_ID, "limit=5000"), fetchDrawings(PROJECT_ID, 200), fetchPriceResults(PROJECT_ID), fetchEvidence(PROJECT_ID), fetchHistory(PROJECT_ID)])
      .then(([analysis, drawingRows, priceRows, evidenceRows, historyRows]) => {
        const warningRows = [...analysis.items.map(queueItem), ...drawingRows.map(queueDrawing), ...priceRows.map(queuePrice)];
        setWarnings(warningRows);
        setEvidence(evidenceRows);
        setHistory(historyRows);
        setSelectedId(previous => previous && warningRows.some(item => item.id === previous) ? previous : warningRows[0]?.id || null);
      })
      .catch(() => setNotice("검토 대상 목록을 불러오지 못했습니다. API 연결과 권한을 확인하세요."))
      .finally(() => setLoading(false));
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
    if (value === "all") params.delete("stage"); else params.set("stage", value);
    const queryString = params.toString();
    window.history.replaceState({}, "", `${window.location.pathname}${queryString ? `?${queryString}` : ""}`);
  }

  const scopedWarnings = useMemo(() => warnings.filter(item => dataScope === "전체" || item.data_origin === dataScope), [warnings, dataScope]);
  const stageWarnings = useMemo(() => scopedWarnings.filter(item => stage === "all" || item.stage === stage), [scopedWarnings, stage]);
  const filtered = useMemo(() => stageWarnings.filter(item => {
    const matchesStatus = status === "전체 상태" || item.status === status;
    const haystack = [item.title, item.detail, item.warning_type, item.rule_code, item.id].filter(Boolean).join(" ").toLowerCase();
    return matchesStatus && (!query || haystack.includes(query.toLowerCase()));
  }), [stageWarnings, status, query]);
  const stageCounts = useMemo(() => ({
    all: scopedWarnings.length,
    initial: scopedWarnings.filter(item => item.stage === "initial").length,
    change: scopedWarnings.filter(item => item.stage === "change").length,
    price: scopedWarnings.filter(item => item.stage === "price").length,
  }), [scopedWarnings]);

  const selected = filtered.find(item => item.id === selectedId) || filtered[0] || null;
  const selectedEvidence = selected ? evidence.filter(item => item.warning_id === selected.id) : [];
  const selectedHistory = selected ? history.filter(item => item.source_id === selected.id) : [];
  const highCount = stageWarnings.filter(item => item.severity === "높음").length;
  const withDataScope = (path: string) => {
    if (dataScope === "전체") return path;
    const separator = path.includes("?") ? "&" : "?";
    return `${path}${separator}dataScope=${encodeURIComponent(dataScope)}`;
  };

  return <AppShell eyebrow="REVIEW TARGETS" title="검토 대상 목록">
    <div className="review-scope-bar"><span>프로젝트 <strong>광양5 사무동</strong></span><span>건물 <strong>전체</strong></span><span>공종 <strong>전체</strong></span><span>자료 회차 <code>API 기준</code></span><span className="scope-state">승인 전 후보값</span></div>
    <p className="lead">{stage === "all" ? "세 단계의 확인 요청을 모아 보되, 각 항목의 검토 단계를 구분합니다." : `${stageLabels[stage]}에 해당하는 확인 요청만 표시합니다.`} 수량·금액·단가는 승인 전 확정값으로 표시하지 않습니다.</p>
    <nav className="review-stage-tabs" aria-label="검토 단계">
      {(Object.keys(stageLabels) as ReviewStage[]).map(key => <button type="button" key={key} className={stage === key ? "active" : ""} onClick={() => handleStageChange(key)}>{stageLabels[key]} <small>{loading ? "—" : stageCounts[key].toLocaleString()}건</small></button>)}
    </nav>
    <p className="review-stage-note">전체 확인 요청은 세 단계의 미처리 항목을 모은 보조함입니다. 단계를 선택하면 해당 업무의 항목·상태·근거만 표시됩니다.</p>
    {notice && <PageMessage tone="danger">{notice}</PageMessage>}
    <section className="review-kpis">
      <div><span>{stage === "all" ? "전체 확인 요청" : `${stageLabels[stage]} 대상`}</span><strong>{loading ? "—" : stageWarnings.length.toLocaleString()}</strong><small>{stage === "all" ? "세 단계 합계" : "선택 단계 항목"}</small></div>
      <div><span>높음 경고</span><strong className="metric-danger">{loading ? "—" : highCount.toLocaleString()}</strong><small>근거 확인 필요</small></div>
      <div><span>원본 근거 연결</span><strong>{loading ? "—" : evidence.length.toLocaleString()}</strong><small>파일·행·셀·도면 위치</small></div>
      <div><span>승인 전 상태</span><strong className="metric-teal">후보</strong><small>자동 확정 금지</small></div>
    </section>
    <section className="review-workspace">
      <div className="review-table-panel panel">
        <div className="panel-head"><div><p className="eyebrow">REVIEW TARGETS</p><h2>검토 대상 목록 <span className="count-label">{filtered.length}건</span></h2></div><span className="review-only">원본 근거 우선</span></div>
        <div className="review-toolbar"><label>자료 범위<select value={dataScope} onChange={event => handleDataScopeChange(event.target.value as DataScope)}>{dataScopeOptions.map(option => <option key={option}>{option}</option>)}</select></label><label>상태<select value={status} onChange={event => setStatus(event.target.value)}>{statusOptions.map(option => <option key={option}>{option}</option>)}</select></label><label className="search-field">검색<input value={query} onChange={event => setQuery(event.target.value)} placeholder="경고·품명·규칙 ID 검색" /></label><button type="button" className="button-secondary" onClick={() => { handleDataScopeChange("전체"); setStatus("전체 상태"); setQuery(""); }}>필터 초기화</button></div>
        {loading ? <div className="review-loading">검토 목록과 근거를 불러오는 중입니다…</div> : <div className="review-table-wrap"><table className="review-table"><thead><tr><th>심각도</th><th>검토 대상</th><th>유형</th><th>상태</th><th>검토 단계</th><th>근거</th></tr></thead><tbody>{filtered.map(item => <tr key={item.id} className={selected?.id === item.id ? "selected" : ""} onClick={() => setSelectedId(item.id)}><td><span className={`severity ${item.severity}`}>{item.severity || "-"}</span></td><td><strong>{item.title}</strong><small>{item.id}</small></td><td>{item.warning_type || "검토 경고"}</td><td><CandidateBadge status={item.status} /></td><td>{item.stage ? stageLabels[item.stage] : "확인 필요"}</td><td>{evidence.some(row => row.warning_id === item.id) ? "연결됨" : "확인 필요"}</td></tr>)}{!filtered.length && <tr><td colSpan={6} className="empty">현재 범위에 검토 대상이 없습니다.</td></tr>}</tbody></table></div>}
      </div>
      <aside className="review-inspector panel" aria-label="검토 근거 상세">
        {!selected ? <div className="inspector-empty"><strong>검토 항목을 선택하세요</strong><p>목록에서 항목을 선택하면 원본 근거와 승인 이력이 표시됩니다.</p></div> : <>
          <div className="inspector-title"><div><p className="eyebrow">EVIDENCE INSPECTOR</p><h2>왜 검토가 필요한가</h2></div><CandidateBadge status={selected.status} /></div>
          <div className="inspector-alert"><span className={`severity ${selected.severity}`}>{selected.severity}</span><strong>{selected.title}</strong><p>{selected.detail || "판정 사유가 기록되지 않았습니다."}</p></div>
          <dl className="inspector-facts"><div><dt>검토 단계</dt><dd>{selected.stage ? stageLabels[selected.stage] : "확인 필요"}</dd></div><div><dt>규칙 ID</dt><dd>{selected.rule_code || "확인 필요"}</dd></div><div><dt>경고 유형</dt><dd>{selected.warning_type || "-"}</dd></div><div><dt>근거 강도</dt><dd>확정 여부가 아닌 후보 근거</dd></div></dl>
          <section className="inspector-section"><h3>원본 근거</h3>{selectedEvidence.length ? <EvidenceBlock evidence={selectedEvidence.map(item => ({ ...item, file_path: shortFileName(item.file_path) }))} /> : <div className="evidence-empty">원본 파일·시트·행·도면 위치 확인 필요</div>}</section>
          <section className="inspector-section"><h3>승인 이력</h3>{selectedHistory.length ? selectedHistory.slice(0, 4).map(item => <div className="inspector-history" key={item.id}><strong>{item.department} · {item.decision}</strong><small>{item.reviewer} · {item.comment}</small></div>) : <div className="evidence-empty">아직 기록된 승인 이력이 없습니다.</div>}</section>
          <div className="inspector-actions"><button type="button" className="button-secondary" onClick={() => router.push(withDataScope("/upload"))}>원본 자료 화면 열기</button><button type="button" onClick={() => router.push(withDataScope(selected.warning_type?.includes("도면") ? "/drawings" : selected.warning_type?.includes("단가") ? "/prices" : "/quantities"))}>검토 화면으로 이동</button><button type="button" className="button-secondary" onClick={() => router.push(withDataScope("/approvals"))}>추가자료 요청·승인 화면</button></div>
        </>}
      </aside>
    </section>
  </AppShell>;
}
