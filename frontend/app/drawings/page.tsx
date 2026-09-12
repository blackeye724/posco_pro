"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell, CandidateBadge, PageMessage, WorkflowStepper } from "../../components/AppShell";
import { DrawingCandidate, PROJECT_ID, fetchDrawings } from "../../components/api";

const DATA_SCOPE_OPTIONS = ["전체", "운영 자료", "통합 테스트"] as const;
type DataScope = typeof DATA_SCOPE_OPTIONS[number];

function originFor(item: DrawingCandidate): "운영 자료" | "통합 테스트" {
  return [item.baseline_file, item.changed_file, item.candidate_text, item.source_row_ref].filter(Boolean).join(" ").match(/integration-source|demo_|통합 테스트/i) ? "통합 테스트" : "운영 자료";
}

function shortFileName(path?: string) {
  if (!path) return "원본 경로 확인 필요";
  return path.split(/[\\/]/).pop() || path;
}

function DrawingPreview({ changed }: { changed: boolean }) {
  return <svg className="cad-preview-svg" viewBox="0 0 400 300" role="img" aria-label={changed ? "변경 도면 미리보기" : "기준 도면 미리보기"}>
    <defs><pattern id={changed ? "cad-grid-changed" : "cad-grid-base"} width="20" height="20" patternUnits="userSpaceOnUse"><path d="M 20 0 L 0 0 0 20" fill="none" stroke="#dce5eb" strokeWidth="1" /></pattern></defs>
    <rect width="400" height="300" fill={changed ? "#fffaf4" : "#fafcfd"} />
    <rect width="400" height="300" fill={`url(#${changed ? "cad-grid-changed" : "cad-grid-base"})`} />
    <rect x="50" y="40" width="300" height="200" fill="none" stroke="#64748b" strokeWidth="2" />
    <line x1="80" y1="100" x2="320" y2="100" stroke="#314863" strokeWidth="3" />
    <line x1="80" y1="160" x2="260" y2="160" stroke="#314863" strokeWidth="3" />
    <circle cx="200" cy="210" r="30" fill={changed ? "#fff0dc" : "#eff4ff"} stroke="#314863" strokeWidth="2" />
    {changed && <><rect x="245" y="140" width="78" height="42" fill="#fff0dc" fillOpacity=".85" stroke="#e07a25" strokeWidth="3" strokeDasharray="5 3" /><line x1="255" y1="161" x2="320" y2="161" stroke="#e07a25" strokeWidth="4" /><circle cx="300" cy="161" r="6" fill="#e07a25" stroke="#fff" strokeWidth="2" /><text x="248" y="205" fill="#b45309" fontSize="11" fontFamily="ui-monospace, monospace">변경 후보</text></>}
  </svg>;
}

export default function DrawingsPage() {
  const router = useRouter();
  const [items, setItems] = useState<DrawingCandidate[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dataScope, setDataScope] = useState<DataScope>("전체");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const requestedScope = new URLSearchParams(window.location.search).get("dataScope");
    if (requestedScope && DATA_SCOPE_OPTIONS.includes(requestedScope as DataScope)) setDataScope(requestedScope as DataScope);
    fetchDrawings(PROJECT_ID, 200).then(rows => { setItems(rows); setSelectedId(rows[0]?.id || null); }).catch(() => setNotice("도면 변경 후보를 불러오지 못했습니다. API 연결과 권한을 확인하세요.")).finally(() => setLoading(false));
  }, []);

  function handleDataScopeChange(value: DataScope) {
    setDataScope(value);
    const params = new URLSearchParams(window.location.search);
    if (value === "전체") params.delete("dataScope"); else params.set("dataScope", value);
    const queryString = params.toString();
    window.history.replaceState({}, "", `${window.location.pathname}${queryString ? `?${queryString}` : ""}`);
  }

  function withDataScope(path: string) {
    if (dataScope === "전체") return path;
    const separator = path.includes("?") ? "&" : "?";
    return `${path}${separator}dataScope=${encodeURIComponent(dataScope)}`;
  }

  const filteredItems = items.filter(item => dataScope === "전체" || originFor(item) === dataScope);
  const selected = filteredItems.find(item => item.id === selectedId) || filteredItems[0];

  return <AppShell eyebrow="CAD DRAWING DELTA" title="도면 변경부위 검토">
    <div className="drawing-scope-bar"><span>프로젝트 <strong>광양5 사무동</strong></span><span>도면 후보 <strong>{loading ? "—" : `${filteredItems.length}건`}</strong></span><span>전처리 근거 <strong>06번 전후 매핑</strong></span><label>자료 범위<select value={dataScope} onChange={event => handleDataScopeChange(event.target.value as DataScope)}>{DATA_SCOPE_OPTIONS.map(option => <option key={option}>{option}</option>)}</select></label><span className="cad-state">CAD 자동 확정 없음</span></div>
    <WorkflowStepper current="change" />
    <p className="lead">기준·변경 도면의 번호·시트·Rev.를 비교한 후보입니다. 수량·내역 검토 결과와 분리된 흐름이며, CAD 워커가 없거나 연결이 확인되지 않은 경우에도 자동으로 불가 처리하지 않습니다.</p>
    {notice && <PageMessage tone="warning">{notice}</PageMessage>}
    {loading ? <section className="panel cad-loading">도면 변경 후보를 불러오는 중입니다…</section> : !selected ? <section className="panel empty">현재 범위에 도면 변경 후보가 없습니다.</section> : <section className="cad-workspace">
      <div className="cad-main panel">
        <div className="panel-head"><div><p className="eyebrow">CAD REVIEW WORKSPACE</p><h2>{selected.drawing_number || selected.sheet_number || "도면번호 미지정"}</h2><small className="muted-line">{selected.discipline || "공종 미지정"} · {selected.location_ref || "위치 확인 필요"}</small></div><CandidateBadge status={selected.status} confidence={selected.confidence} /></div>
        <div className="cad-revision-labels"><span><b>기준 도면</b>{selected.baseline_revision || "Rev. 확인 필요"}</span><span><b>변경 도면</b>{selected.changed_revision || "Rev. 확인 필요"}</span></div>
        <div className="cad-viewports"><div className="cad-viewport"><div className="cad-viewport-header">기준 · {selected.baseline_revision || "UNKNOWN"}<span>{shortFileName(selected.baseline_file)}</span></div><DrawingPreview changed={false} /></div><div className="cad-divider" aria-hidden="true" /><div className="cad-viewport changed"><div className="cad-viewport-header">변경 · {selected.changed_revision || "UNKNOWN"}<span>{shortFileName(selected.changed_file)}</span></div><DrawingPreview changed={true} /></div></div>
        <div className="cad-footer"><span>시각 비교는 후보 미리보기이며 원본 CAD 판정을 대체하지 않습니다.</span><button type="button" className="button-secondary" onClick={() => router.push("/upload")}>원본 자료 화면 열기</button></div>
      </div>
      <aside className="cad-inspector panel"><div className="panel-head"><div><p className="eyebrow">CHANGE CANDIDATE</p><h2>변경 후보 상세</h2></div><span className="review-only">확정 전 후보</span></div><div className="cad-alert"><strong>{selected.candidate_text || "변경 설명이 전처리 결과에 기록되지 않았습니다."}</strong><p>도면 연결이 확인되지 않아도 불가로 판정하지 않고 추가 확인 상태로 보존합니다.</p></div><dl className="cad-facts"><div><dt>도면번호</dt><dd>{selected.drawing_number || "-"}</dd></div><div><dt>시트</dt><dd>{selected.sheet_number || "-"}</dd></div><div><dt>기준 Rev.</dt><dd>{selected.baseline_revision || "UNKNOWN"}</dd></div><div><dt>변경 Rev.</dt><dd>{selected.changed_revision || "UNKNOWN"}</dd></div><div><dt>원본 행</dt><dd>{selected.source_row_ref || "확인 필요"}</dd></div><div><dt>변경 유형</dt><dd>{selected.change_type || "-"}</dd></div></dl><section className="cad-links"><h3>연결 검증</h3><div>도면 → 변경 내역 <b>{selected.link_status || "연결 근거 없음"}</b></div><div>연결된 내역 행 <b>{selected.linked_estimate_count ?? 0}건</b></div>{selected.linked_estimate_names?.length ? <small title={selected.linked_estimate_names.join(" · ")}>품명 {selected.linked_estimate_names.join(" · ")}</small> : <small>도면번호가 일치하는 사무동 내역서 행을 찾지 못했습니다.</small>}<div>수량산출서 → 내역서 <b>별도 수량 검토</b></div></section><div className="cad-actions"><button type="button" onClick={() => router.push(withDataScope("/quantities?sourceSet=변경자료"))}>변경 내역·수량 검토</button><button type="button" onClick={() => router.push("/approvals")}>근거 확인·승인 화면</button><button type="button" className="button-secondary" onClick={() => router.push("/approvals")}>추가자료 요청 화면</button></div></aside>
    </section>}
    {!loading && filteredItems.length > 1 && <section className="panel cad-candidate-list"><div className="panel-head"><div><p className="eyebrow">CANDIDATE LIST</p><h2>도면 변경 후보 목록</h2></div><span className="muted-line">행을 선택하면 비교 화면이 바뀝니다.</span></div><div className="candidate-list compact-list">{filteredItems.map(item => <button type="button" className={`cad-candidate-row ${item.id === selected?.id ? "selected" : ""}`} key={item.id} onClick={() => setSelectedId(item.id)}><span className={`severity ${item.status === "추가 확인 필요" ? "중간" : "낮음"}`}>{item.status || "검토 대기"}</span><strong>{item.drawing_number || item.sheet_number || item.id}</strong><span>{item.baseline_revision || "-"} → {item.changed_revision || "-"}</span><small>{item.candidate_text || "변경 설명 확인 필요"}</small></button>)}</div></section>}
  </AppShell>;
}
