"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell, CandidateBadge, EvidenceBlock, PageMessage } from "../../components/AppShell";
import { Approval, Evidence, PROJECT_ID, Warning, fetchEvidence, fetchHistory, fetchWarnings } from "../../components/api";

const statusOptions = ["전체 상태", "검토 대기", "추가 확인 필요", "적용 보류", "승인"];

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
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([fetchWarnings(PROJECT_ID, 200), fetchEvidence(PROJECT_ID), fetchHistory(PROJECT_ID)])
      .then(([warningRows, evidenceRows, historyRows]) => {
        setWarnings(warningRows);
        setEvidence(evidenceRows);
        setHistory(historyRows);
        setSelectedId(previous => previous && warningRows.some(item => item.id === previous) ? previous : warningRows[0]?.id || null);
      })
      .catch(() => setNotice("통합 검토 큐를 불러오지 못했습니다. API 연결과 권한을 확인하세요."))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => warnings.filter(item => {
    const matchesStatus = status === "전체 상태" || item.status === status;
    const haystack = [item.title, item.detail, item.warning_type, item.rule_code, item.id].filter(Boolean).join(" ").toLowerCase();
    return matchesStatus && (!query || haystack.includes(query.toLowerCase()));
  }), [warnings, status, query]);

  const selected = filtered.find(item => item.id === selectedId) || filtered[0] || null;
  const selectedEvidence = selected ? evidence.filter(item => item.warning_id === selected.id) : [];
  const selectedHistory = selected ? history.filter(item => item.source_id === selected.id) : [];
  const highCount = warnings.filter(item => item.severity === "높음").length;
  const pendingCount = warnings.filter(item => item.status !== "승인").length;

  return <AppShell eyebrow="INTEGRATED REVIEW QUEUE" title="통합 검토 큐">
    <div className="review-scope-bar"><span>프로젝트 <strong>광양5 사무동</strong></span><span>건물 <strong>전체</strong></span><span>공종 <strong>전체</strong></span><span>자료 회차 <code>API 기준</code></span><span className="scope-state">승인 전 후보값</span></div>
    <p className="lead">검토 대상과 원본 근거를 한 화면에서 확인합니다. 수량·금액·단가는 승인 전 확정값으로 표시하지 않습니다.</p>
    <nav className="review-stage-tabs" aria-label="검토 단계">
      <a href="/review" className="active">전체 대기</a><a href="/quantities">01 최초 자료 검토</a><a href="/drawings">02 설계변경 검토</a><a href="/prices">03 신규내역 단가</a>
    </nav>
    {notice && <PageMessage tone="danger">{notice}</PageMessage>}
    <section className="review-kpis">
      <div><span>검토 대기 항목</span><strong>{loading ? "—" : pendingCount.toLocaleString()}</strong><small>산식·도면·단가 복합 대상</small></div>
      <div><span>높음 경고</span><strong className="metric-danger">{loading ? "—" : highCount.toLocaleString()}</strong><small>근거 확인 필요</small></div>
      <div><span>원본 근거 연결</span><strong>{loading ? "—" : evidence.length.toLocaleString()}</strong><small>파일·행·셀·도면 위치</small></div>
      <div><span>승인 전 상태</span><strong className="metric-teal">후보</strong><small>자동 확정 금지</small></div>
    </section>
    <section className="review-workspace">
      <div className="review-table-panel panel">
        <div className="panel-head"><div><p className="eyebrow">AUDIT QUEUE</p><h2>통합 검토 목록 <span className="count-label">{filtered.length}건</span></h2></div><span className="review-only">원본 근거 우선</span></div>
        <div className="review-toolbar"><label>상태<select value={status} onChange={event => setStatus(event.target.value)}>{statusOptions.map(option => <option key={option}>{option}</option>)}</select></label><label className="search-field">검색<input value={query} onChange={event => setQuery(event.target.value)} placeholder="경고·품명·규칙 ID 검색" /></label><button type="button" className="button-secondary" onClick={() => { setStatus("전체 상태"); setQuery(""); }}>필터 초기화</button></div>
        {loading ? <div className="review-loading">검토 목록과 근거를 불러오는 중입니다…</div> : <div className="review-table-wrap"><table className="review-table"><thead><tr><th>심각도</th><th>검토 대상</th><th>유형</th><th>상태</th><th>담당 단계</th><th>근거</th></tr></thead><tbody>{filtered.map(item => <tr key={item.id} className={selected?.id === item.id ? "selected" : ""} onClick={() => setSelectedId(item.id)}><td><span className={`severity ${item.severity}`}>{item.severity || "-"}</span></td><td><strong>{item.title}</strong><small>{item.id}</small></td><td>{item.warning_type || "검토 경고"}</td><td><CandidateBadge status={item.status} /></td><td>공사부서</td><td>{evidence.some(row => row.warning_id === item.id) ? "연결됨" : "확인 필요"}</td></tr>)}{!filtered.length && <tr><td colSpan={6} className="empty">현재 범위에 검토 대상이 없습니다.</td></tr>}</tbody></table></div>}
      </div>
      <aside className="review-inspector panel" aria-label="검토 근거 상세">
        {!selected ? <div className="inspector-empty"><strong>검토 항목을 선택하세요</strong><p>목록에서 항목을 선택하면 원본 근거와 승인 이력이 표시됩니다.</p></div> : <>
          <div className="inspector-title"><div><p className="eyebrow">EVIDENCE INSPECTOR</p><h2>왜 검토가 필요한가</h2></div><CandidateBadge status={selected.status} /></div>
          <div className="inspector-alert"><span className={`severity ${selected.severity}`}>{selected.severity}</span><strong>{selected.title}</strong><p>{selected.detail || "판정 사유가 기록되지 않았습니다."}</p></div>
          <dl className="inspector-facts"><div><dt>규칙 ID</dt><dd>{selected.rule_code || "확인 필요"}</dd></div><div><dt>경고 유형</dt><dd>{selected.warning_type || "-"}</dd></div><div><dt>근거 강도</dt><dd>확정 여부가 아닌 후보 근거</dd></div></dl>
          <section className="inspector-section"><h3>원본 근거</h3>{selectedEvidence.length ? <EvidenceBlock evidence={selectedEvidence.map(item => ({ ...item, file_path: shortFileName(item.file_path) }))} /> : <div className="evidence-empty">원본 파일·시트·행·도면 위치 확인 필요</div>}</section>
          <section className="inspector-section"><h3>승인 이력</h3>{selectedHistory.length ? selectedHistory.slice(0, 4).map(item => <div className="inspector-history" key={item.id}><strong>{item.department} · {item.decision}</strong><small>{item.reviewer} · {item.comment}</small></div>) : <div className="evidence-empty">아직 기록된 승인 이력이 없습니다.</div>}</section>
          <div className="inspector-actions"><button type="button" className="button-secondary" onClick={() => router.push("/upload")}>원본 자료 화면 열기</button><button type="button" onClick={() => router.push(selected.warning_type?.toLowerCase().includes("도면") ? "/drawings" : "/quantities")}>검토 화면으로 이동</button><button type="button" className="button-secondary" onClick={() => router.push("/approvals")}>추가자료 요청·승인 화면</button></div>
        </>}
      </aside>
    </section>
  </AppShell>;
}
