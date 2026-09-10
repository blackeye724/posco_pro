"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { AppShell, CandidateBadge, EvidenceBlock, PageMessage } from "../../components/AppShell";
import { Approval, Evidence, PROJECT_ID, Warning, createApproval, createBatchApproval, fetchEvidence, fetchHistory, fetchWarnings } from "../../components/api";

const stages = ["공사부서", "설계부서", "구매부서"];

export default function ApprovalsPage() {
  const [warnings, setWarnings] = useState<Warning[]>([]);
  const [history, setHistory] = useState<Approval[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [batchDepartment, setBatchDepartment] = useState("공사부서");
  const [batchDecision, setBatchDecision] = useState("승인");
  const [batchReviewer, setBatchReviewer] = useState("");
  const [batchComment, setBatchComment] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [batchBusy, setBatchBusy] = useState(false);
  const reload = () => Promise.all([fetchWarnings(PROJECT_ID, 80), fetchHistory(PROJECT_ID), fetchEvidence(PROJECT_ID)]).then(([w, h, e]) => { setWarnings(w); setHistory(h); setEvidence(e); }).catch(() => setNotice("승인 대기열을 불러오지 못했습니다."));
  useEffect(() => { reload(); }, []);
  const decisions = useMemo(() => new Map(history.map(item => [`${item.source_id}:${item.department}`, item])), [history]);
  function toggle(sourceId: string) { setSelected(previous => { const next = new Set(previous); if (next.has(sourceId)) next.delete(sourceId); else next.add(sourceId); return next; }); }
  function selectAll() { setSelected(previous => previous.size === warnings.slice(0, 30).length ? new Set() : new Set(warnings.slice(0, 30).map(item => item.id))); }
  async function submit(event: FormEvent<HTMLFormElement>, sourceId: string) {
    event.preventDefault(); const form = new FormData(event.currentTarget); const department = String(form.get("department")); setBusy(`${sourceId}:${department}`);
    try { await createApproval(PROJECT_ID, sourceId, { department, decision: String(form.get("decision")), reviewer: String(form.get("reviewer")), comment: String(form.get("comment")) }); setNotice(`${department} 승인 이력을 저장했습니다.`); reload(); } catch (error) { setNotice(error instanceof Error ? error.message : "승인 처리에 실패했습니다."); } finally { setBusy(""); }
  }
  async function submitBatch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected.size) { setNotice("일괄 처리할 항목을 먼저 선택하세요."); return; }
    setBatchBusy(true);
    try { const result = await createBatchApproval(PROJECT_ID, { source_ids: Array.from(selected), department: batchDepartment, decision: batchDecision, reviewer: batchReviewer, comment: batchComment }); setNotice(`일괄 처리 완료: 성공 ${result.succeeded_count}건, 실패 ${result.failed_count}건. 실패 항목은 개별 사유를 확인하세요.`); setSelected(new Set()); setBatchComment(""); reload(); } catch (error) { setNotice(error instanceof Error ? error.message : "일괄 승인 처리에 실패했습니다."); } finally { setBatchBusy(false); }
  }
  return <AppShell eyebrow="04 / APPROVAL QUEUE" title="부서별 승인 대기열"><p className="lead">공사부서 → 설계부서 → 구매부서 순서로 승인합니다. 앞 단계 승인 전에는 다음 부서의 확정 처리를 할 수 없습니다. 개별 처리와 동일 단계 선택 일괄 처리를 지원합니다.</p>{notice && <PageMessage tone={notice.includes("실패") || notice.includes("필요") ? "danger" : "info"}>{notice}</PageMessage>}<section className="stage-strip">{stages.map((stage, index) => <div key={stage} className="stage"><span>0{index + 1}</span><strong>{stage}</strong><small>{index === 0 ? "검토 착수" : `${stages[index - 1]} 승인 후 진행`}</small></div>)}</section><section className="panel compact"><div className="panel-head"><div><p className="eyebrow">BATCH REVIEW</p><h2>{selected.size}건 선택</h2></div><button type="button" className="button-secondary" onClick={selectAll}>{selected.size === warnings.slice(0, 30).length ? "전체 선택 해제" : "현재 목록 전체 선택"}</button></div><form className="form-two" onSubmit={submitBatch}><label>부서<select value={batchDepartment} onChange={event => setBatchDepartment(event.target.value)}>{stages.map(stage => <option key={stage}>{stage}</option>)}</select></label><label>판정<select value={batchDecision} onChange={event => setBatchDecision(event.target.value)}><option>승인</option><option>수정 요청</option><option>반려</option><option>추가 확인 필요</option><option>오탐</option></select></label><label>검토자<input required value={batchReviewer} onChange={event => setBatchReviewer(event.target.value)} placeholder="검토자"/></label><label>의견·근거<input required value={batchComment} onChange={event => setBatchComment(event.target.value)} placeholder="일괄 처리 사유"/></label><button disabled={batchBusy || !selected.size}>{batchBusy ? "일괄 처리 중…" : "선택 항목 일괄 처리"}</button></form><small className="field-help">각 항목의 선행 승인·권한·상태를 개별 검사하며 실패 항목은 별도 사유로 남습니다.</small></section><section className="approval-list">{warnings.slice(0, 30).map(item => <article className="approval-card" key={item.id}><div className="approval-card-head"><label className="selection-check"><input type="checkbox" checked={selected.has(item.id)} onChange={() => toggle(item.id)}/><span>선택</span></label><div><span className={`severity ${item.severity}`}>{item.severity}</span><h3>{item.title}</h3><p>{item.detail || "판정 사유 미기록"}</p><EvidenceBlock evidence={evidence.filter(row => row.warning_id === item.id)}/></div><CandidateBadge status={item.status}/></div><div className="approval-actions">{stages.map(stage => { const decision = decisions.get(`${item.id}:${stage}`); return <form key={stage} onSubmit={event => submit(event, item.id)} className={decision ? "approval-form complete" : "approval-form"}><input type="hidden" name="department" value={stage}/><strong>{stage}</strong>{decision ? <span className="approved">{decision.decision} · {decision.reviewer}</span> : <><select name="decision" defaultValue="추가 확인 필요"><option>추가 확인 필요</option><option>승인</option><option>수정 요청</option><option>반려</option><option>오탐</option></select><input name="reviewer" required placeholder="검토자"/><input name="comment" required placeholder="사유·근거"/><button disabled={busy === `${item.id}:${stage}`}>{busy === `${item.id}:${stage}` ? "저장…" : "처리"}</button></>}</form>; })}</div></article>)}{!warnings.length && <div className="empty">승인 대기 항목이 없습니다.</div>}</section></AppShell>;
}
