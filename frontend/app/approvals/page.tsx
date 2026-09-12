"use client";

import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AppShell, CandidateBadge, EvidenceBlock, PageMessage } from "../../components/AppShell";
import { Approval, DrawingCandidate, Evidence, PriceResult, PROJECT_ID, QuantityAnalysisItem, Warning, createApproval, createBatchApproval, fetchDrawings, fetchEvidence, fetchHistory, fetchPriceResults, fetchQuantityAnalysis } from "../../components/api";

const stages = ["공사부서", "설계부서", "구매부서"];
const dataScopeOptions = ["전체", "운영 자료", "통합 테스트"] as const;
type DataScope = typeof dataScopeOptions[number];
type ReviewStage = "all" | "initial" | "change" | "price";
const stageLabels: Record<ReviewStage, string> = { all: "전체 확인 요청", initial: "01 최초자료", change: "02 설계변경", price: "03 신규내역 단가" };

function warningOrigin(item: Warning): DataScope {
  if (item.data_origin) return item.data_origin;
  return [item.id, item.title, item.detail, item.rule_code].filter(Boolean).join(" ").match(/integration-source|demo_|통합 테스트/i) ? "통합 테스트" : "운영 자료";
}

function originFor(...values: unknown[]): Exclude<DataScope, "전체"> {
  return values.filter(Boolean).join(" ").match(/integration-source|demo_|통합 테스트/i) ? "통합 테스트" : "운영 자료";
}

function queueQuantity(item: QuantityAnalysisItem): Warning {
  return { id: item.id, project_id: item.project_id, warning_type: item.issue_type, severity: item.severity, title: item.item_text || item.item_key || "내역 항목", detail: item.required_action || item.judgement, expected_value: item.original_value, actual_value: item.recalculated_value, status: item.status || "승인 대기", rule_code: item.rule_version, data_origin: originFor(item.source_file, item.evidence), stage: item.source_set === "기준자료" ? "initial" : "change" };
}

function queueDrawing(item: DrawingCandidate): Warning {
  return { id: `drawing:${item.id}`, project_id: item.project_id, warning_type: "도면 변경 후보", severity: item.confidence === "높음" ? "높음" : item.confidence === "중간" ? "중간" : "낮음", title: item.drawing_number || item.sheet_number || "도면번호 확인 필요", detail: item.candidate_text || item.next_action || "변경 도면 근거 확인이 필요합니다.", status: "추가 확인 필요", rule_code: "DRAWING_DELTA_CANDIDATE", data_origin: originFor(item.baseline_file, item.changed_file, item.candidate_text), stage: "change" };
}

function queuePrice(item: PriceResult): Warning {
  const status = item.lookup_status?.includes("보류") || item.lookup_status?.includes("미검토") ? "추가 확인 필요" : "승인 대기";
  return { id: `price:${item.id}`, project_id: item.project_id, warning_type: "신규내역 단가 후보", severity: "중간", title: item.item_name || item.candidate_id || "신규내역 품명 확인 필요", detail: item.lookup_status || "단가 출처와 기준일 확인이 필요합니다.", expected_value: item.price == null ? undefined : `${item.price}`, status, rule_code: "NEW_ITEM_PRICE_CANDIDATE", data_origin: originFor(item.item_name, item.evidence, item.candidate_id), stage: "price" };
}

function warningStage(item: Warning): Exclude<ReviewStage, "all"> {
  if (item.stage) return item.stage;
  // 상세 사유에는 "도면 연결 실패가 아님"처럼 부정 표현이 자주 포함되므로,
  // 단계 추론은 유형·제목·규칙 ID의 명시적 신호만 사용한다.
  const text = [item.warning_type, item.title, item.rule_code].filter(Boolean).join(" ");
  if (/단가|가격|price/i.test(text)) return "price";
  if (/도면|설계변경|변경 후보|drawing/i.test(text)) return "change";
  return "initial";
}

function currentStage(item: Warning, decisions: Map<string, Approval>) {
  const firstPending = stages.findIndex(stage => !decisions.has(`${item.id}:${stage}`));
  return firstPending < 0 ? stages.length - 1 : firstPending;
}

function ApprovalsContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const focusedWarningId = searchParams.get("warning_id");
  const [warnings, setWarnings] = useState<Warning[]>([]);
  const [history, setHistory] = useState<Approval[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [batchDepartment, setBatchDepartment] = useState("공사부서");
  const [batchDecision, setBatchDecision] = useState("승인");
  const [batchReviewer, setBatchReviewer] = useState("");
  const [batchComment, setBatchComment] = useState("");
  const [notice, setNotice] = useState("");
  const [lastBatch, setLastBatch] = useState<{ succeeded_count: number; failed_count: number; items: { source_id: string; status: string; error_message?: string }[] } | null>(null);
  const [busy, setBusy] = useState("");
  const [batchBusy, setBatchBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [dataScope, setDataScope] = useState<DataScope>(() => {
    const value = searchParams.get("dataScope");
    return value && dataScopeOptions.includes(value as DataScope) ? value as DataScope : "전체";
  });
  const [reviewStage, setReviewStage] = useState<ReviewStage>(() => {
    const value = searchParams.get("stage");
    return value === "initial" || value === "change" || value === "price" ? value : "all";
  });

  const reload = () => Promise.all([fetchQuantityAnalysis(PROJECT_ID, "limit=5000"), fetchDrawings(PROJECT_ID, 200), fetchPriceResults(PROJECT_ID), fetchHistory(PROJECT_ID), fetchEvidence(PROJECT_ID)]).then(([analysis, drawingRows, priceRows, historyRows, evidenceRows]) => { setWarnings([...analysis.items.map(queueQuantity), ...drawingRows.map(queueDrawing), ...priceRows.map(queuePrice)]); setHistory(historyRows); setEvidence(evidenceRows); }).catch(() => setNotice("승인 대기열을 불러오지 못했습니다. API 연결과 권한을 확인하세요."));
  useEffect(() => { reload().finally(() => setLoading(false)); }, []);
  useEffect(() => {
    if (!focusedWarningId || loading) return;
    const target = document.getElementById(`warning-${focusedWarningId}`);
    target?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focusedWarningId, loading, warnings.length]);
  const decisions = useMemo(() => new Map(history.map(item => [`${item.source_id}:${item.department}`, item])), [history]);
  const scopedWarnings = useMemo(() => warnings.filter(item => dataScope === "전체" || warningOrigin(item) === dataScope), [warnings, dataScope]);
  const stageWarnings = useMemo(() => scopedWarnings.filter(item => reviewStage === "all" || warningStage(item) === reviewStage), [scopedWarnings, reviewStage]);
  const pendingCount = stageWarnings.filter(item => item.status !== "승인").length;
  const stageCounts = stages.map(stage => stageWarnings.filter(item => !decisions.has(`${item.id}:${stage}`)).length);
  const reviewStageCounts = useMemo(() => ({
    all: scopedWarnings.length,
    initial: scopedWarnings.filter(item => warningStage(item) === "initial").length,
    change: scopedWarnings.filter(item => warningStage(item) === "change").length,
    price: scopedWarnings.filter(item => warningStage(item) === "price").length,
  }), [scopedWarnings]);

  function handleDataScopeChange(value: DataScope) {
    setDataScope(value);
    setSelected(new Set());
    const params = new URLSearchParams(window.location.search);
    if (value === "전체") params.delete("dataScope"); else params.set("dataScope", value);
    const queryString = params.toString();
    window.history.replaceState({}, "", `${window.location.pathname}${queryString ? `?${queryString}` : ""}`);
  }

  function handleReviewStageChange(value: ReviewStage) {
    setReviewStage(value);
    setSelected(new Set());
    const params = new URLSearchParams(window.location.search);
    if (value === "all") params.delete("stage"); else params.set("stage", value);
    const queryString = params.toString();
    window.history.replaceState({}, "", `${window.location.pathname}${queryString ? `?${queryString}` : ""}`);
  }

  function toggle(sourceId: string) { setSelected(previous => { const next = new Set(previous); if (next.has(sourceId)) next.delete(sourceId); else next.add(sourceId); return next; }); }
  function selectAll() { setSelected(previous => previous.size === stageWarnings.slice(0, 30).length ? new Set() : new Set(stageWarnings.slice(0, 30).map(item => item.id))); }
  async function submit(event: FormEvent<HTMLFormElement>, sourceId: string) {
    event.preventDefault(); const form = new FormData(event.currentTarget); const department = String(form.get("department")); setBusy(`${sourceId}:${department}`);
    try { await createApproval(PROJECT_ID, sourceId, { department, decision: String(form.get("decision")), reviewer: String(form.get("reviewer")), comment: String(form.get("comment")) }); setNotice(`${department} 승인 이력을 저장했습니다.`); await reload(); } catch (error) { setNotice(error instanceof Error ? error.message : "승인 처리에 실패했습니다."); } finally { setBusy(""); }
  }
  async function submitBatch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected.size) { setNotice("일괄 처리할 항목을 먼저 선택하세요."); return; }
    setBatchBusy(true); setLastBatch(null);
    try { const result = await createBatchApproval(PROJECT_ID, { source_ids: Array.from(selected), department: batchDepartment, decision: batchDecision, reviewer: batchReviewer, comment: batchComment }); setLastBatch(result); setNotice(`일괄 처리 완료: 성공 ${result.succeeded_count}건, 실패 ${result.failed_count}건`); setSelected(new Set()); setBatchComment(""); await reload(); } catch (error) { setNotice(error instanceof Error ? error.message : "일괄 승인 처리에 실패했습니다."); } finally { setBatchBusy(false); }
  }

  const withContext = (path: string) => {
    const params = new URLSearchParams();
    if (dataScope !== "전체") params.set("dataScope", dataScope);
    if (reviewStage !== "all") params.set("stage", reviewStage);
    const queryString = params.toString();
    const separator = path.includes("?") ? "&" : "?";
    return `${path}${queryString ? `${separator}${queryString}` : ""}`;
  };
  const targetPath = (item: Warning) => {
    const itemStage = warningStage(item);
    if (itemStage === "price") return withContext("/prices?sourceSet=변경자료");
    if (itemStage === "change" && /도면|drawing/i.test([item.warning_type, item.title, item.detail].join(" "))) return withContext("/drawings");
    return withContext(itemStage === "initial" ? "/quantities?sourceSet=기준자료" : "/quantities?sourceSet=변경자료");
  };

  return <AppShell eyebrow="APPROVAL QUEUE" title="부서별 승인 대기열">
    <div className="approval-scope-bar"><span>프로젝트 <strong>광양5 사무동</strong></span><span>승인 순서 <strong>공사 → 설계 → 구매</strong></span><label>자료 범위<select value={dataScope} onChange={event => handleDataScopeChange(event.target.value as DataScope)}>{dataScopeOptions.map(option => <option key={option}>{option}</option>)}</select></label><span className="candidate-state">승인 ≠ 값 확정</span></div>
    <p className="lead">부서별 검토 이력을 순서대로 저장합니다. 앞 단계 승인 전에는 다음 단계가 잠기며, 승인 후에도 수량·금액·단가는 별도 확정 전까지 후보값입니다.</p>
    <nav className="review-stage-tabs" aria-label="승인 대상 검토 단계">{(Object.keys(stageLabels) as ReviewStage[]).map(key => <button type="button" key={key} className={reviewStage === key ? "active" : ""} onClick={() => handleReviewStageChange(key)}>{stageLabels[key]} <small>{loading ? "—" : reviewStageCounts[key].toLocaleString()}건</small></button>)}</nav>
    <p className="review-stage-note">단계를 선택하면 해당 업무의 승인 요청만 남습니다. 카드의 검토 화면에서 원본 행·산출 근거를 먼저 확인한 후 부서별 승인을 기록하세요.</p>
    {notice && <PageMessage tone={notice.includes("실패") || notice.includes("권한") ? "danger" : "info"}>{notice}</PageMessage>}
    <section className="approval-kpis"><div><span>{reviewStage === "all" ? "전체 승인 대기" : `${stageLabels[reviewStage]} 승인 대기`}</span><strong>{loading ? "—" : pendingCount}</strong><small>{reviewStage === "all" ? "세 단계 합계" : "선택 단계 후보"}</small></div>{stages.map((stage, index) => <div key={stage}><span>{stage} 대기</span><strong>{loading ? "—" : stageCounts[index]}</strong><small>{index === 0 ? "검토 착수" : `${stages[index - 1]} 승인 후 진행`}</small></div>)}</section>
    <section className="approval-stage-strip">{stages.map((stage, index) => <div className={`approval-stage stage-${index + 1}`} key={stage}><span>0{index + 1}</span><div><strong>{stage}</strong><small>{index === 0 ? "공사 검토" : `${stages[index - 1]} 승인 이후`}</small></div>{index < stages.length - 1 && <b>→</b>}</div>)}</section>
    <section className="approval-review-list">{loading ? <section className="panel review-loading">승인 대기열을 불러오는 중입니다…</section> : stageWarnings.slice(0, focusedWarningId ? 1000 : 30).map(item => { const itemStage = currentStage(item, decisions); return <article id={`warning-${item.id}`} className={`approval-card approval-card-enhanced ${item.id === focusedWarningId ? "approval-card-focused" : ""}`} key={item.id}><div className="approval-card-head"><label className="selection-check"><input type="checkbox" checked={selected.has(item.id)} onChange={() => toggle(item.id)} /><span>선택</span></label><div className="approval-item-summary"><span className={`severity ${item.severity}`}>{item.severity}</span><h3>{item.title}</h3><p>{item.detail || "판정 사유 미기록"}</p><EvidenceBlock evidence={evidence.filter(row => row.warning_id === item.id)} /><div className="approval-card-links"><button type="button" className="button-secondary" onClick={() => router.push(targetPath(item))}>검토 화면 열기 →</button><small>{stageLabels[warningStage(item)]}</small></div></div><CandidateBadge status={item.status} /></div><div className="approval-actions">{stages.map((stage, stageIndex) => { const decision = decisions.get(`${item.id}:${stage}`); const locked = stageIndex > itemStage || (stageIndex === itemStage && Boolean(decision)); return <form key={stage} onSubmit={event => submit(event, item.id)} className={`${decision ? "approval-form complete" : "approval-form"} ${locked ? "approval-form-locked" : ""}`}><input type="hidden" name="department" value={stage} /><strong>{stage}</strong>{decision ? <span className="approved">{decision.decision} · {decision.reviewer}</span> : <><span className="stage-state">{stageIndex === itemStage ? "현재 단계" : "선행 승인 필요"}</span><select name="decision" defaultValue="추가 확인 필요" disabled={locked}><option>추가 확인 필요</option><option>승인</option><option>수정 요청</option><option>반려</option><option>오탐</option></select><input name="reviewer" required placeholder="검토자" disabled={locked} /><input name="comment" required placeholder="사유·근거" disabled={locked} /><button disabled={locked || busy === `${item.id}:${stage}`}>{busy === `${item.id}:${stage}` ? "저장…" : "처리"}</button></>}</form>; })}</div></article>; })}{!loading && !stageWarnings.length && <section className="panel empty">현재 범위와 검토 단계에 승인 대기 항목이 없습니다.</section>}</section>
  </AppShell>;
}

export default function ApprovalsPage() {
  return <Suspense fallback={<AppShell eyebrow="APPROVAL QUEUE" title="부서별 승인 대기열"><section className="panel review-loading">승인 대기열을 불러오는 중입니다…</section></AppShell>}><ApprovalsContent /></Suspense>;
}
