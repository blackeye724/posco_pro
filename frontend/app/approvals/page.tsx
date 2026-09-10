"use client";

import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AppShell, CandidateBadge, EvidenceBlock, PageMessage } from "../../components/AppShell";
import { Approval, Evidence, PROJECT_ID, Warning, createApproval, createBatchApproval, fetchEvidence, fetchHistory, fetchWarnings } from "../../components/api";

const stages = ["공사부서", "설계부서", "구매부서"];

function currentStage(item: Warning, decisions: Map<string, Approval>) {
  const firstPending = stages.findIndex(stage => !decisions.has(`${item.id}:${stage}`));
  return firstPending < 0 ? stages.length - 1 : firstPending;
}

function ApprovalsContent() {
  const searchParams = useSearchParams();
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

  const reload = () => Promise.all([fetchWarnings(PROJECT_ID, focusedWarningId ? 1000 : 80), fetchHistory(PROJECT_ID), fetchEvidence(PROJECT_ID)]).then(([warningRows, historyRows, evidenceRows]) => { setWarnings(warningRows); setHistory(historyRows); setEvidence(evidenceRows); }).catch(() => setNotice("승인 대기열을 불러오지 못했습니다. API 연결과 권한을 확인하세요."));
  useEffect(() => { reload().finally(() => setLoading(false)); }, []);
  useEffect(() => {
    if (!focusedWarningId || loading) return;
    const target = document.getElementById(`warning-${focusedWarningId}`);
    target?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focusedWarningId, loading, warnings.length]);
  const decisions = useMemo(() => new Map(history.map(item => [`${item.source_id}:${item.department}`, item])), [history]);
  const pendingCount = warnings.filter(item => item.status !== "승인").length;
  const stageCounts = stages.map(stage => warnings.filter(item => !decisions.has(`${item.id}:${stage}`)).length);

  function toggle(sourceId: string) { setSelected(previous => { const next = new Set(previous); if (next.has(sourceId)) next.delete(sourceId); else next.add(sourceId); return next; }); }
  function selectAll() { setSelected(previous => previous.size === warnings.slice(0, 30).length ? new Set() : new Set(warnings.slice(0, 30).map(item => item.id))); }
  async function submit(event: FormEvent<HTMLFormElement>, sourceId: string) {
    event.preventDefault(); const form = new FormData(event.currentTarget); const department = String(form.get("department")); setBusy(`${sourceId}:${department}`);
    try { await createApproval(PROJECT_ID, sourceId, { department, decision: String(form.get("decision")), reviewer: String(form.get("reviewer")), comment: String(form.get("comment")) }); setNotice(`${department} 승인 이력을 저장했습니다.`); await reload(); } catch (error) { setNotice(error instanceof Error ? error.message : "승인 처리에 실패했습니다."); } finally { setBusy(""); }
  }
  async function submitBatch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected.size) { setNotice("일괄 처리할 항목을 먼저 선택하세요."); return; }
    setBatchBusy(true); setLastBatch(null);
    try { const result = await createBatchApproval(PROJECT_ID, { source_ids: Array.from(selected), department: batchDepartment, decision: batchDecision, reviewer: batchReviewer, comment: batchComment }); setLastBatch(result); setNotice(`일괄 처리 완료: 성공 ${result.succeeded_count}건, 실패 ${result.failed_count}건`); setSelected(new Set()); setBatchComment(""); await reload(); } catch (error) { setNotice(error instanceof Error ? error.message : "일괄 승인 처리에 실패했습니다."); } finally { setBatchBusy(false); }
  }

  return <AppShell eyebrow="APPROVAL QUEUE" title="부서별 승인 대기열">
    <div className="approval-scope-bar"><span>프로젝트 <strong>광양5 사무동</strong></span><span>승인 순서 <strong>공사 → 설계 → 구매</strong></span><span className="candidate-state">승인 ≠ 값 확정</span></div>
    <p className="lead">부서별 검토 이력을 순서대로 저장합니다. 앞 단계 승인 전에는 다음 단계가 잠기며, 승인 후에도 수량·금액·단가는 별도 확정 전까지 후보값입니다.</p>
    {notice && <PageMessage tone={notice.includes("실패") || notice.includes("권한") ? "danger" : "info"}>{notice}</PageMessage>}
    <section className="approval-kpis"><div><span>승인 대기 항목</span><strong>{loading ? "—" : pendingCount}</strong><small>현재 검토 후보</small></div>{stages.map((stage, index) => <div key={stage}><span>{stage} 대기</span><strong>{loading ? "—" : stageCounts[index]}</strong><small>{index === 0 ? "검토 착수" : `${stages[index - 1]} 승인 후 진행`}</small></div>)}</section>
    <section className="approval-stage-strip">{stages.map((stage, index) => <div className={`approval-stage stage-${index + 1}`} key={stage}><span>0{index + 1}</span><div><strong>{stage}</strong><small>{index === 0 ? "공사 검토" : `${stages[index - 1]} 승인 이후`}</small></div>{index < stages.length - 1 && <b>→</b>}</div>)}</section>
    <section className="panel compact approval-batch-panel"><div className="panel-head"><div><p className="eyebrow">BATCH REVIEW</p><h2>{selected.size}건 선택</h2></div><button type="button" className="button-secondary" onClick={selectAll}>{selected.size === warnings.slice(0, 30).length ? "전체 선택 해제" : "현재 목록 전체 선택"}</button></div><form className="form-two" onSubmit={submitBatch}><label>부서<select value={batchDepartment} onChange={event => setBatchDepartment(event.target.value)}>{stages.map(stage => <option key={stage}>{stage}</option>)}</select></label><label>판정<select value={batchDecision} onChange={event => setBatchDecision(event.target.value)}><option>승인</option><option>수정 요청</option><option>반려</option><option>추가 확인 필요</option><option>오탐</option></select></label><label>검토자<input required value={batchReviewer} onChange={event => setBatchReviewer(event.target.value)} placeholder="검토자" /></label><label>의견·근거<input required value={batchComment} onChange={event => setBatchComment(event.target.value)} placeholder="일괄 처리 사유" /></label><button disabled={batchBusy || !selected.size}>{batchBusy ? "일괄 처리 중…" : "선택 항목 일괄 처리"}</button></form><small className="field-help">각 항목의 선행 승인·권한·상태를 개별 검사하며 실패 항목은 별도 사유로 남습니다.</small>{lastBatch && <div className="batch-result"><strong>항목별 처리 결과</strong>{lastBatch.items.map(item => <span key={item.source_id} className={item.status === "success" ? "batch-success" : "batch-failure"}>{item.source_id} · {item.status === "success" ? "성공" : `실패: ${item.error_message || "사유 확인 필요"}`}</span>)}</div>}</section>
    <section className="approval-review-list">{loading ? <section className="panel review-loading">승인 대기열을 불러오는 중입니다…</section> : warnings.slice(0, focusedWarningId ? 1000 : 30).map(item => { const itemStage = currentStage(item, decisions); return <article id={`warning-${item.id}`} className={`approval-card approval-card-enhanced ${item.id === focusedWarningId ? "approval-card-focused" : ""}`} key={item.id}><div className="approval-card-head"><label className="selection-check"><input type="checkbox" checked={selected.has(item.id)} onChange={() => toggle(item.id)} /><span>선택</span></label><div className="approval-item-summary"><span className={`severity ${item.severity}`}>{item.severity}</span><h3>{item.title}</h3><p>{item.detail || "판정 사유 미기록"}</p><EvidenceBlock evidence={evidence.filter(row => row.warning_id === item.id)} /></div><CandidateBadge status={item.status} /></div><div className="approval-actions">{stages.map((stage, stageIndex) => { const decision = decisions.get(`${item.id}:${stage}`); const locked = stageIndex > itemStage || (stageIndex === itemStage && Boolean(decision)); return <form key={stage} onSubmit={event => submit(event, item.id)} className={`${decision ? "approval-form complete" : "approval-form"} ${locked ? "approval-form-locked" : ""}`}><input type="hidden" name="department" value={stage} /><strong>{stage}</strong>{decision ? <span className="approved">{decision.decision} · {decision.reviewer}</span> : <><span className="stage-state">{stageIndex === itemStage ? "현재 단계" : "선행 승인 필요"}</span><select name="decision" defaultValue="추가 확인 필요" disabled={locked}><option>추가 확인 필요</option><option>승인</option><option>수정 요청</option><option>반려</option><option>오탐</option></select><input name="reviewer" required placeholder="검토자" disabled={locked} /><input name="comment" required placeholder="사유·근거" disabled={locked} /><button disabled={locked || busy === `${item.id}:${stage}`}>{busy === `${item.id}:${stage}` ? "저장…" : "처리"}</button></>}</form>; })}</div></article>; })}{!loading && !warnings.length && <section className="panel empty">현재 범위에 승인 대기 항목이 없습니다.</section>}</section>
  </AppShell>;
}

export default function ApprovalsPage() {
  return <Suspense fallback={<AppShell eyebrow="APPROVAL QUEUE" title="부서별 승인 대기열"><section className="panel review-loading">승인 대기열을 불러오는 중입니다…</section></AppShell>}><ApprovalsContent /></Suspense>;
}
