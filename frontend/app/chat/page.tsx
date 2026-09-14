"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { AppShell, EvidenceBlock, PageMessage } from "../../components/AppShell";
import { DrawingCandidate, Evidence, PROJECT_ID, Warning, fetchDrawings, fetchEvidence, fetchWarnings } from "../../components/api";

type ChatAnswer = { id: string; question: string; state: string; answer: string; warnings: Warning[]; drawings: DrawingCandidate[]; evidence: Evidence[] };
const prompts = ["높음 경고만 보여줘", "A-101 Rev.04 변경 후보의 근거는?", "현재 추가 확인이 필요한 항목은?"];

const STOP_WORDS = new Set(["보여줘", "보여", "현재", "추가", "확인이", "확인", "필요한", "필요", "항목은", "항목", "근거는", "근거", "후보의", "후보", "어떤", "무엇", "알려줘", "대해", "변경", "설계변경", "경고", "도면", "수량", "물량", "단가", "높음", "high", "대기", "only"]);
const SEARCH_ALIASES: Record<string, string[]> = {
  "설계변경": ["변경", "변경후보", "revision", "rev"],
  "변경": ["설계변경", "변경후보", "revision", "rev"],
  "도면": ["drawing", "sheet", "도면번호"],
  "수량": ["물량", "수량산출", "산출수량"],
  "물량": ["수량", "수량산출", "산출수량"],
  "경고": ["warning", "주의", "검토"],
  "단가": ["가격", "금액", "price"],
  "벽돌": ["조적", "벽돌공사"],
  "조적": ["벽돌", "벽돌공사"],
};

function normalizeSearch(value: string | undefined) {
  return (value || "").normalize("NFKC").toLowerCase().replace(/[^0-9a-z가-힣._/-]+/g, " ").replace(/\s+/g, " ").trim();
}

function expandQuery(raw: string) {
  const base = normalizeSearch(raw).split(" ").filter(token => token.length > 1 && !STOP_WORDS.has(token));
  return [...new Set(base.flatMap(token => [token, ...(SEARCH_ALIASES[token] || [])].map(normalizeSearch)))];
}

type Scored<T> = { item: T; score: number };
function scoreFields<T>(item: T, fields: [string | undefined, number][], tokens: string[], phrase: string): Scored<T> {
  const normalizedFields = fields.map(([value, weight]) => [normalizeSearch(value), weight] as const);
  let score = 0;
  for (const token of tokens) for (const [value, weight] of normalizedFields) if (value.includes(token)) score += weight;
  if (phrase && normalizedFields.some(([value]) => value.includes(phrase))) score += 8;
  return { item, score };
}

export default function ChatPage() {
  const [warnings, setWarnings] = useState<Warning[]>([]);
  const [drawings, setDrawings] = useState<DrawingCandidate[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [question, setQuestion] = useState("");
  const [answers, setAnswers] = useState<ChatAnswer[]>([]);
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const queryCache = useRef(new Map<string, { warnings: Warning[]; drawings: DrawingCandidate[] }>());

  const warningIndex = useMemo(() => warnings.map(item => ({ item, fields: [item.title, item.detail, item.warning_type, item.rule_code, item.id] })), [warnings]);
  const drawingIndex = useMemo(() => drawings.map(item => ({ item, fields: [item.drawing_number, item.sheet_number, item.baseline_revision, item.changed_revision, item.candidate_text, item.location_ref, item.id] })), [drawings]);

  useEffect(() => { Promise.all([fetchWarnings(PROJECT_ID, 200), fetchDrawings(PROJECT_ID, 200), fetchEvidence(PROJECT_ID)]).then(([warningRows, drawingRows, evidenceRows]) => { setWarnings(warningRows); setDrawings(drawingRows); setEvidence(evidenceRows); }).catch(() => setNotice("근거 검색에 필요한 자료를 불러오지 못했습니다." )).finally(() => setLoading(false)); }, []);

  const answer = (rawQuestion: string) => {
    const text = rawQuestion.trim(); if (!text) return;
    const cacheKey = normalizeSearch(text);
    let result = queryCache.current.get(cacheKey);
    if (!result) {
      const highOnly = normalizeSearch(text).includes("높음") || normalizeSearch(text).includes("high");
      const pendingOnly = normalizeSearch(text).includes("추가 확인") || normalizeSearch(text).includes("대기");
      const normalizedText = normalizeSearch(text);
      const warningIntent = highOnly || pendingOnly || /warning|경고|규칙|판정/.test(normalizedText);
      const drawingIntent = /drawing|sheet|도면|rev\.?|a-\d/.test(normalizedText);
      const phrase = normalizedText;
      const queryTokens = expandQuery(text);
      const warningMatches = warningIndex
        .filter(({ item }) => (!highOnly || item.severity === "높음") && (!pendingOnly || item.status !== "승인"))
        .map(({ item, fields }) => scoreFields(item, fields.map(value => [value, value === item.rule_code || value === item.id ? 6 : value === item.title || value === item.warning_type ? 4 : 2]), queryTokens, phrase))
        .filter(({ score }) => queryTokens.length ? score > 0 : warningIntent)
        .sort((a, b) => b.score - a.score || String(a.item.title).localeCompare(String(b.item.title), "ko"))
        .map(({ item }) => item);
      const drawingMatches = drawingIndex
        .map(({ item, fields }) => scoreFields(item, fields.map(value => [value, value === item.drawing_number || value === item.sheet_number ? 5 : 2]), queryTokens, phrase))
        .filter(({ score }) => queryTokens.length ? score > 0 : drawingIntent)
        .sort((a, b) => b.score - a.score || String(a.item.drawing_number || a.item.sheet_number).localeCompare(String(b.item.drawing_number || b.item.sheet_number), "ko"))
        .map(({ item }) => item);
      result = { warnings: warningMatches, drawings: drawingMatches };
      queryCache.current.set(cacheKey, result);
    }
    const matches = result.warnings;
    const drawingMatches = result.drawings;
    const relatedEvidence = evidence.filter(item => matches.some(warning => warning.id === item.warning_id));
    const noResult = !matches.length && !drawingMatches.length;
    setAnswers(previous => [...previous, { id: `${Date.now()}-${previous.length}`, question: text, state: noResult ? "추가 확인 필요" : relatedEvidence.length ? "근거 확인" : "검토 후보", answer: noResult ? "현재 자료에서 확인되지 않습니다. 프로젝트·건물·공종 범위를 좁히거나 원본 자료를 추가해 주세요." : `${matches.length + drawingMatches.length}건의 관련 검토 후보를 찾았습니다. 아래 인용은 원본 근거 목록입니다. 승인·반려·단가 확정은 실행하지 않습니다.`, warnings: matches.slice(0, 8), drawings: drawingMatches.slice(0, 8), evidence: relatedEvidence.slice(0, 12) }]); setQuestion("");
  };
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); answer(question); }
  const latest = useMemo(() => answers.slice(-1)[0], [answers]);

    return <AppShell className="chat-page" eyebrow="EVIDENCE SEARCH ASSISTANT" title="검토 챗봇">
    <div className="chat-scope-bar"><span>프로젝트 <strong>광양5 사무동</strong></span><span>범위 <strong>현재 프로젝트 자료만</strong></span></div>
    <p className="lead">현재 프로젝트의 경고·도면 후보·원본 근거를 검색합니다. 근거가 없으면 추정하지 않으며 승인·반려·단가 확정·원본 수정은 실행하지 않습니다.</p>
    {notice && <PageMessage tone="danger">{notice}</PageMessage>}
    <section className="chat-layout"><section className="panel chat-panel"><div className="panel-head"><div><p className="eyebrow">EVIDENCE SEARCH</p><h2>근거 검색 대화</h2></div></div><div className="chat-messages">{!answers.length && <div className="chat-empty"><strong>무엇을 확인할까요?</strong><p>아래 추천 질문을 선택하거나 경고·도면번호·규칙 ID를 입력하세요.</p><div className="prompt-list">{prompts.map(prompt => <button type="button" className="prompt-chip" key={prompt} onClick={() => answer(prompt)}>{prompt}</button>)}</div></div>}{answers.map(item => <article className="chat-turn" key={item.id}><div className="chat-question">질문 · {item.question}</div><div className="chat-answer"><span className={`answer-state ${item.state === "추가 확인 필요" ? "needs-check" : ""}`}>{item.state}</span><p>{item.answer}</p>{item.warnings.map(warning => <div className="chat-result" key={warning.id}><strong>{warning.title}</strong><span>{warning.severity} · {warning.status} · {warning.rule_code || "규칙 ID 확인 필요"}</span><small>{warning.detail || "판정 사유 미기록"}</small></div>)}{item.drawings.map(drawing => <div className="chat-result" key={drawing.id}><strong>{drawing.drawing_number || drawing.sheet_number || drawing.id}</strong><span>{drawing.baseline_revision || "UNKNOWN"} → {drawing.changed_revision || "UNKNOWN"} · {drawing.status}</span><small>{drawing.candidate_text || "변경 설명 확인 필요"}</small></div>)}{item.evidence.length > 0 && <EvidenceBlock evidence={item.evidence} />}<div className="chat-next-actions"><Link href="/review">통합 검토 큐 열기</Link><Link href="/drawings">도면 검토 열기</Link><Link href="/quantities">수량 검토 열기</Link></div></div></article>)}</div><form className="chat-form" onSubmit={submit}><input value={question} onChange={event => setQuestion(event.target.value)} disabled={loading} placeholder={loading ? "근거 자료를 불러오는 중입니다…" : "예: A-101 Rev.04 변경 후보의 근거는?"} /><button disabled={loading || !question.trim()}>검색</button></form></section><aside className="panel chat-context"><p className="eyebrow">SEARCH CONTEXT</p><h2>현재 검색 범위</h2><dl className="inspector-facts"><div><dt>프로젝트</dt><dd>광양5 사무동</dd></div><div><dt>경고 자료</dt><dd>{loading ? "—" : `${warnings.length}건`}</dd></div><div><dt>도면 후보</dt><dd>{loading ? "—" : `${drawings.length}건`}</dd></div><div><dt>근거 링크</dt><dd>{loading ? "—" : `${evidence.length}건`}</dd></div></dl><section className="chat-guardrail"><strong>실행 제한</strong><p>이 화면은 검색과 근거 제시만 수행합니다. 승인·반려·단가 확정·원본 수정 요청은 관련 검토 화면에서 직접 처리하세요.</p></section>{latest && <section className="chat-latest"><strong>최근 답변 상태</strong><span>{latest.state}</span></section>}</aside></section>
  </AppShell>;
}
