"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AppShell, EvidenceBlock, PageMessage } from "../../components/AppShell";
import { DrawingCandidate, Evidence, PROJECT_ID, Warning, fetchDrawings, fetchEvidence, fetchWarnings } from "../../components/api";

type ChatAnswer = { id: string; question: string; state: string; answer: string; warnings: Warning[]; drawings: DrawingCandidate[]; evidence: Evidence[] };
const prompts = ["높음 경고만 보여줘", "A-101 Rev.04 변경 후보의 근거는?", "현재 추가 확인이 필요한 항목은?"];

function includesQuery(value: string | undefined, query: string) { return Boolean(value && value.toLowerCase().includes(query.toLowerCase())); }

export default function ChatPage() {
  const [warnings, setWarnings] = useState<Warning[]>([]);
  const [drawings, setDrawings] = useState<DrawingCandidate[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [question, setQuestion] = useState("");
  const [answers, setAnswers] = useState<ChatAnswer[]>([]);
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => { Promise.all([fetchWarnings(PROJECT_ID, 200), fetchDrawings(PROJECT_ID, 200), fetchEvidence(PROJECT_ID)]).then(([warningRows, drawingRows, evidenceRows]) => { setWarnings(warningRows); setDrawings(drawingRows); setEvidence(evidenceRows); }).catch(() => setNotice("근거 검색에 필요한 자료를 불러오지 못했습니다." )).finally(() => setLoading(false)); }, []);

  const answer = (rawQuestion: string) => {
    const text = rawQuestion.trim(); if (!text) return;
    const highOnly = text.includes("높음") || text.toLowerCase().includes("high");
    const pendingOnly = text.includes("추가 확인") || text.includes("대기");
    const queryTokens = text.replace(/높음|경고|보여줘|현재|추가|확인이|필요한|항목은|근거는|변경|후보의|[?？]/g, " ").split(/\s+/).filter(token => token.length > 1);
    const matches = warnings.filter(item => (!highOnly || item.severity === "높음") && (!pendingOnly || item.status !== "승인") && (!queryTokens.length || queryTokens.some(token => [item.title, item.detail, item.warning_type, item.rule_code, item.id].filter(Boolean).join(" ").toLowerCase().includes(token.toLowerCase()))));
    const drawingMatches = drawings.filter(item => !queryTokens.length || queryTokens.some(token => [item.drawing_number, item.sheet_number, item.baseline_revision, item.changed_revision, item.candidate_text, item.location_ref].filter(Boolean).join(" ").toLowerCase().includes(token.toLowerCase())));
    const relatedEvidence = evidence.filter(item => matches.some(warning => warning.id === item.warning_id));
    const noResult = !matches.length && !drawingMatches.length;
    setAnswers(previous => [...previous, { id: `${Date.now()}-${previous.length}`, question: text, state: noResult ? "추가 확인 필요" : relatedEvidence.length ? "근거 확인" : "검토 후보", answer: noResult ? "현재 자료에서 확인되지 않습니다. 프로젝트·건물·공종 범위를 좁히거나 원본 자료를 추가해 주세요." : `${matches.length + drawingMatches.length}건의 관련 검토 후보를 찾았습니다. 아래 인용은 읽기 전용 근거 목록입니다. 승인·반려·단가 확정은 실행하지 않습니다.`, warnings: matches.slice(0, 8), drawings: drawingMatches.slice(0, 8), evidence: relatedEvidence.slice(0, 12) }]); setQuestion("");
  };
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); answer(question); }
  const latest = useMemo(() => answers.slice(-1)[0], [answers]);

    return <AppShell eyebrow="READ-ONLY EVIDENCE ASSISTANT" title="검토 챗봇">
    <div className="chat-scope-bar"><span>프로젝트 <strong>광양5 사무동</strong></span><span>범위 <strong>현재 프로젝트 자료만</strong></span><span className="candidate-state">읽기 전용 · 외부 모델 미사용</span></div>
    <p className="lead">현재 프로젝트의 경고·도면 후보·원본 근거를 검색합니다. 근거가 없으면 추정하지 않으며 승인·반려·단가 확정·원본 수정은 실행하지 않습니다.</p>
    {notice && <PageMessage tone="danger">{notice}</PageMessage>}
    <section className="chat-layout"><section className="panel chat-panel"><div className="panel-head"><div><p className="eyebrow">EVIDENCE SEARCH</p><h2>근거 검색 대화</h2></div><span className="review-only">읽기 전용</span></div><div className="chat-messages">{!answers.length && <div className="chat-empty"><strong>무엇을 확인할까요?</strong><p>아래 추천 질문을 선택하거나 경고·도면번호·규칙 ID를 입력하세요.</p><div className="prompt-list">{prompts.map(prompt => <button type="button" className="prompt-chip" key={prompt} onClick={() => answer(prompt)}>{prompt}</button>)}</div></div>}{answers.map(item => <article className="chat-turn" key={item.id}><div className="chat-question">질문 · {item.question}</div><div className="chat-answer"><span className={`answer-state ${item.state === "추가 확인 필요" ? "needs-check" : ""}`}>{item.state}</span><p>{item.answer}</p>{item.warnings.map(warning => <div className="chat-result" key={warning.id}><strong>{warning.title}</strong><span>{warning.severity} · {warning.status} · {warning.rule_code || "규칙 ID 확인 필요"}</span><small>{warning.detail || "판정 사유 미기록"}</small></div>)}{item.drawings.map(drawing => <div className="chat-result" key={drawing.id}><strong>{drawing.drawing_number || drawing.sheet_number || drawing.id}</strong><span>{drawing.baseline_revision || "UNKNOWN"} → {drawing.changed_revision || "UNKNOWN"} · {drawing.status}</span><small>{drawing.candidate_text || "변경 설명 확인 필요"}</small></div>)}{item.evidence.length > 0 && <EvidenceBlock evidence={item.evidence} />}<div className="chat-next-actions"><Link href="/review">통합 검토 큐 열기</Link><Link href="/drawings">도면 검토 열기</Link><Link href="/quantities">수량 검토 열기</Link></div></div></article>)}</div><form className="chat-form" onSubmit={submit}><input value={question} onChange={event => setQuestion(event.target.value)} disabled={loading} placeholder={loading ? "근거 자료를 불러오는 중입니다…" : "예: A-101 Rev.04 변경 후보의 근거는?"} /><button disabled={loading || !question.trim()}>검색</button></form></section><aside className="panel chat-context"><p className="eyebrow">SEARCH CONTEXT</p><h2>현재 검색 범위</h2><dl className="inspector-facts"><div><dt>프로젝트</dt><dd>광양5 사무동</dd></div><div><dt>경고 자료</dt><dd>{loading ? "—" : `${warnings.length}건`}</dd></div><div><dt>도면 후보</dt><dd>{loading ? "—" : `${drawings.length}건`}</dd></div><div><dt>근거 링크</dt><dd>{loading ? "—" : `${evidence.length}건`}</dd></div><div><dt>외부 모델</dt><dd>사용하지 않음</dd></div></dl><section className="chat-guardrail"><strong>실행 제한</strong><p>이 화면은 검색과 근거 제시만 수행합니다. 승인·반려·단가 확정·원본 수정 요청은 관련 검토 화면에서 직접 처리하세요.</p></section>{latest && <section className="chat-latest"><strong>최근 답변 상태</strong><span>{latest.state}</span></section>}</aside></section>
  </AppShell>;
}
