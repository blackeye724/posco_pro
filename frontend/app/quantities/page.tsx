"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell, CandidateBadge, PageMessage, WorkflowStepper } from "../../components/AppShell";
import { fetchQuantityAnalysis, PROJECT_ID, QuantityAnalysis, QuantityAnalysisItem, selectQuantityCandidate } from "../../components/api";

function toneFor(severity?: string) {
  if (severity === "높음") return "high";
  if (severity === "중간") return "medium";
  return "low";
}

function display(value?: string | null) {
  return value || "추출되지 않음";
}

function titleFor(item: QuantityAnalysisItem) {
  return item.item_text || item.item_key || item.source_file || item.sheet_or_drawing || "검토 항목";
}

const WORK_PACKAGE_ORDER = ["토공사", "철골공사", "철근콘크리트공사", "조적공사", "방수공사", "타일공사", "석공사", "금속공사", "미장공사", "도장공사", "수장공사", "패널공사", "창호공사", "유리공사", "홈통공사", "미분류·원천 확인 필요"];
const MISMATCH_REASON_ORDER = ["내역·수량 필드 불일치", "연결 근거 없음", "재검산 불가", "복수 연결 후보"];

function resultCategoryFor(item: QuantityAnalysisItem) {
  return item.issue_type === "일치" ? "일치" : "불일치";
}

function mismatchReasonFor(item: QuantityAnalysisItem) {
  if (item.issue_type === "불일치") return "내역·수량 필드 불일치";
  if (MISMATCH_REASON_ORDER.includes(item.issue_type)) return item.issue_type;
  return item.issue_type || "검토 사유 확인 필요";
}

export default function QuantitiesPage() {
  const router = useRouter();
  const [analysis, setAnalysis] = useState<QuantityAnalysis | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sourceSet, setSourceSet] = useState("전체");
  const [workPackage, setWorkPackage] = useState("전체");
  const [resultCategory, setResultCategory] = useState("전체");
  const [mismatchReason, setMismatchReason] = useState("전체");
  const [severity, setSeverity] = useState("전체");
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [candidateBusy, setCandidateBusy] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const requestedSourceSet = params.get("sourceSet");
    const requestedWorkPackage = params.get("workPackage");
    const requestedResult = params.get("result");
    if (requestedSourceSet && ["전체", "기준자료", "변경자료", "기준·변경 대조"].includes(requestedSourceSet)) setSourceSet(requestedSourceSet);
    if (requestedWorkPackage) setWorkPackage(requestedWorkPackage);
    if (requestedResult && ["전체", "일치", "불일치"].includes(requestedResult)) setResultCategory(requestedResult);
    // Load the full review window exposed by the API so 공사단위 filters do
    // not disappear just because the first page happens to be one workbook.
    fetchQuantityAnalysis(PROJECT_ID, "limit=5000")
      .then(result => {
        setAnalysis(result);
        setSelectedId(result.items[0]?.id || null);
      })
      .catch(() => setNotice("내역·수량 오류 분석 결과를 불러오지 못했습니다. API 연결과 전처리 결과 경로를 확인하세요."))
      .finally(() => setLoading(false));
  }, []);

  const workPackageCounts = useMemo(() => {
    const counts = new Map<string, number>();
    const serverCounts = analysis?.work_package_counts?.[sourceSet];
    if (serverCounts) Object.entries(serverCounts).forEach(([label, count]) => counts.set(label, count));
    else (analysis?.items || [])
      .filter(item => sourceSet === "전체" || item.source_set === sourceSet)
      .forEach(item => {
        const label = item.work_package || "미분류·원천 확인 필요";
        counts.set(label, (counts.get(label) || 0) + 1);
      });
    return WORK_PACKAGE_ORDER.map(label => ({ label, count: counts.get(label) || 0 }));
  }, [analysis, sourceSet]);

  const availableWorkPackages = workPackageCounts.map(item => item.label);

  const availableMismatchReasons = useMemo(() => {
    const values = new Set((analysis?.items || [])
      .filter(item => sourceSet === "전체" || item.source_set === sourceSet)
      .filter(item => workPackage === "전체" || item.work_package === workPackage)
      .filter(item => resultCategoryFor(item) === "불일치")
      .map(mismatchReasonFor));
    return MISMATCH_REASON_ORDER.filter(value => values.has(value));
  }, [analysis, sourceSet, workPackage]);

  useEffect(() => {
    if (workPackage !== "전체" && !availableWorkPackages.includes(workPackage)) setWorkPackage("전체");
    if (resultCategory !== "불일치" && mismatchReason !== "전체") setMismatchReason("전체");
    if (mismatchReason !== "전체" && !availableMismatchReasons.includes(mismatchReason)) setMismatchReason("전체");
  }, [availableMismatchReasons, availableWorkPackages, mismatchReason, resultCategory, workPackage]);

  const filtered = useMemo(() => {
    const items = analysis?.items || [];
    const normalizedQuery = query.trim().toLowerCase();
    return items.filter(item => {
      if (sourceSet !== "전체" && item.source_set !== sourceSet) return false;
      if (workPackage !== "전체" && item.work_package !== workPackage) return false;
      if (resultCategory !== "전체" && resultCategoryFor(item) !== resultCategory) return false;
      if (mismatchReason !== "전체" && mismatchReasonFor(item) !== mismatchReason) return false;
      if (severity !== "전체" && item.severity !== severity) return false;
      if (!normalizedQuery) return true;
      return [item.item_key, item.item_text, item.source_file, item.sheet_or_drawing, item.discipline, item.issue_type, mismatchReasonFor(item), item.required_action]
        .filter(Boolean).join(" ").toLowerCase().includes(normalizedQuery);
    });
  }, [analysis, sourceSet, workPackage, resultCategory, mismatchReason, severity, query]);

  const selected = filtered.find(item => item.id === selectedId) || filtered[0] || null;
  const canSelectCandidate = selected?.issue_type === "복수 연결 후보";
  const summary = analysis?.summary || {};
  const handleSourceSetChange = (value: string) => {
    setSourceSet(value);
    setWorkPackage("전체");
    setResultCategory("전체");
    setMismatchReason("전체");
  };

  const chooseCandidate = async (quantityItemId: string) => {
    if (!selected) return;
    setCandidateBusy(quantityItemId);
    try {
      await selectQuantityCandidate(PROJECT_ID, selected.id, quantityItemId);
      const refreshed = await fetchQuantityAnalysis(PROJECT_ID, "limit=5000");
      setAnalysis(refreshed);
      setSelectedId(selected.id);
      setNotice("수량산출서 후보를 검토 대상으로 지정했습니다. 수량·승인은 자동 확정되지 않습니다.");
    } catch {
      setNotice("후보 지정에 실패했습니다. 공사부서 권한과 원본 세트·건물 범위를 확인하세요.");
    } finally {
      setCandidateBusy(null);
    }
  };

  return <AppShell eyebrow="QUANTITY / FORMULA / COST" title="내역·수량 오류 분석">
    <div className="quantity-scope-bar"><span>프로젝트 <strong>광양5 사무동</strong></span><span>분석 범위 <strong>내역서 ↔ 수량산출서</strong></span><span className="candidate-state">승인 전 후보값</span></div>
    <WorkflowStepper current="initial" />
    <p className="lead">광양5 사무동에 등록된 내역서·수량산출서만 분석합니다. 타건물 자료와 참고 단가는 이 화면의 연결 후보에 사용하지 않습니다. 파일 전체를 한 번에 판정하는 화면이 아니라 내역서의 각 항목(원본 행) 단위로 품명·규격·단위·수량을 대조합니다. 변경자료와 직접 연결되지 않은 후보는 기준·변경 대조 대상으로 남기며, 자동 검산이 불가한 항목은 오류로 확정하지 않고 추가 확인 대상으로 유지합니다.</p>
    {notice && <PageMessage tone="danger">{notice}</PageMessage>}

    <section className="quantity-kpis qa-kpis">
      <div><span>전체 연결·오류 후보</span><strong>{loading ? "—" : analysis?.total || 0}</strong><small>공사부서 승인 대기 {analysis?.approval_queue_total || 0}건 포함</small></div>
      <div><span>연결 근거 없음</span><strong className="metric-danger">{loading ? "—" : summary["연결 근거 없음"] || 0}</strong><small>원천 행 확인 필요</small></div>
      <div><span>재검산 불가</span><strong className="metric-danger">{loading ? "—" : summary["재검산 불가"] || 0}</strong><small>외부참조·복합산식 등</small></div>
      <div><span>복수 연결 후보</span><strong>{loading ? "—" : summary["복수 연결 후보"] || 0}</strong><small>자동 합산 금지</small></div>
    </section>

    <section className="qa-set-summary panel">
      <div><p className="eyebrow">SOURCE SETS</p><h2>자료 세트별 검토 현황</h2></div>
      <div className="qa-set-grid"><button type="button" className={sourceSet === "전체" ? "selected" : ""} onClick={() => handleSourceSetChange("전체")}><span>전체</span><strong>{analysis?.total ?? "—"}</strong><small>세트별 전체 검토</small></button><button type="button" className={sourceSet === "기준자료" ? "selected" : ""} onClick={() => handleSourceSetChange("기준자료")}><span>기준자료</span><strong>{summary["기준자료"] || 0}</strong><small>변경 전 자료 세트</small></button><button type="button" className={sourceSet === "변경자료" ? "selected" : ""} onClick={() => handleSourceSetChange("변경자료")}><span>변경자료</span><strong>{summary["변경자료"] || 0}</strong><small>변경 후 자료 세트</small></button><button type="button" className={sourceSet === "기준·변경 대조" ? "selected" : ""} onClick={() => handleSourceSetChange("기준·변경 대조")}><span>기준·변경 대조</span><strong>{summary["기준·변경 대조"] || 0}</strong><small>원천 행 연결 확인 필요</small></button></div>
    </section>

    {!!analysis?.baseline_changed_comparison?.length && <section className="panel qa-recheck-panel"><div className="panel-head"><div><p className="eyebrow">BASELINE / CHANGED COMPARISON</p><h2>기준·변경 내역 수량 대조 <span className="count-label">{analysis.baseline_changed_comparison.length}개 그룹</span></h2></div><span className="review-only">승인 전 비교값</span></div><p className="qa-note">내역서 표준키와 공종이 양쪽 자료에 모두 있는 항목만 대조합니다. 변경 전후 증감은 검토용 계산값이며 승인·확정값이 아닙니다. 원본 행 근거를 함께 확인하세요.</p><div className="quantity-table-wrap"><table className="quantity-table qa-table"><thead><tr><th>공사단위</th><th>내역 항목</th><th>기준 수량</th><th>변경 수량</th><th>차이</th><th>증감률</th><th>대조 결과</th><th>원본 근거</th></tr></thead><tbody>{analysis.baseline_changed_comparison.slice(0, 50).map(row => <tr key={`${row.work_package}-${row.item_key}`}><td><strong>{row.work_package}</strong></td><td><strong title={row.item_text}>{row.item_text}</strong><small>{row.item_key}</small></td><td>{row.baseline_quantity ?? "—"}<small>{row.baseline_count}행</small></td><td>{row.changed_quantity ?? "—"}<small>{row.changed_count}행</small></td><td>{row.difference ?? "—"}</td><td>{row.difference_rate ?? "—"}</td><td><span className={`severity ${row.result === "변경 없음(허용오차)" ? "low" : row.result === "변경 후 증가" ? "medium" : "high"}`}>{row.result}</span></td><td><span className="qa-evidence-ok" title={row.source_rows.join(" / ")}>기준·변경 행 확인</span></td></tr>)}</tbody></table></div>{analysis.baseline_changed_comparison.length > 50 && <small className="qa-note">화면에는 50개 그룹을 우선 표시합니다. 전체 대조 결과는 API 응답의 원본 근거를 유지합니다.</small>}</section>}

    {!!selected?.quantity_candidates?.length && <section className="panel qa-candidate-panel"><div className="panel-head"><div><p className="eyebrow">QUANTITY EVIDENCE CANDIDATES</p><h2>{canSelectCandidate ? "수량산출서 후보 행" : "수량산출서 원본 비교 행"}</h2></div><span className="review-only">{canSelectCandidate ? "선택 전" : "자동 연결 제외"}</span></div><p className="qa-note">{canSelectCandidate ? "내역서 수량과 가까운 순서입니다. 후보를 지정해도 승인 전 값은 확정되지 않습니다." : "같은 품명 후보가 있으나 단위·규격 또는 문맥이 달라 산출 수량에 반영하지 않았습니다. 원본 행을 확인한 뒤에만 별도 연결할 수 있습니다."}</p><div className="qa-candidate-list">{selected.quantity_candidates.map(candidate => <article className={candidate.selected ? "selected" : ""} key={candidate.id}><div><strong>{candidate.quantity || "수량 없음"} {candidate.unit || ""}</strong><small>{candidate.specification || "규격 미지정"} · {candidate.context || "문맥 미기록"}</small><small>{candidate.source_file || "파일 미지정"} · {candidate.source_row_ref || "행 미지정"}</small></div>{canSelectCandidate && <button type="button" className="button-secondary" disabled={candidateBusy === candidate.id || candidate.selected} onClick={() => chooseCandidate(candidate.id)}>{candidate.selected ? "지정됨" : candidateBusy === candidate.id ? "저장…" : "이 행 지정"}</button>}</article>)}</div></section>}
    <section className="quantity-workspace">
      <div className="quantity-table-panel panel"><div className="panel-head"><div><p className="eyebrow">ITEM-FIRST REVIEW</p><h2>내역 항목별 검토 결과 <span className="count-label">{filtered.length}건</span></h2></div><span className="review-only">확정 전</span></div>
        <div className="quantity-toolbar qa-toolbar"><label>자료 세트<select value={sourceSet} onChange={event => handleSourceSetChange(event.target.value)}><option>전체</option><option>기준자료</option><option>변경자료</option><option>기준·변경 대조</option></select></label><label>공사단위(내역서 분류)<select value={workPackage} onChange={event => setWorkPackage(event.target.value)}><option>전체</option>{workPackageCounts.map(item => <option key={item.label} value={item.label} disabled={item.count === 0}>{item.label} ({item.count}건)</option>)}</select></label><label>검토 결과<select value={resultCategory} onChange={event => { setResultCategory(event.target.value); setMismatchReason("전체"); }}><option>전체</option><option>일치</option><option>불일치</option></select></label><label>불일치 사유<select value={mismatchReason} disabled={resultCategory !== "불일치"} onChange={event => setMismatchReason(event.target.value)}><option>전체</option>{availableMismatchReasons.map(value => <option key={value}>{value}</option>)}</select></label><label>심각도<select value={severity} onChange={event => setSeverity(event.target.value)}><option>전체</option><option>높음</option><option>중간</option><option>낮음</option></select></label><label className="search-field">검색<input value={query} onChange={event => setQuery(event.target.value)} placeholder="내역·품명·시트·공사단위 검색" /></label><button type="button" className="button-secondary" onClick={() => { handleSourceSetChange("전체"); setSeverity("전체"); setQuery(""); }}>초기화</button></div>
        <div className="qa-result-legend"><strong>검토 결과의 의미</strong><span><b>일치</b> 표준품명·규격·단위가 맞고 수량이 정확히 같거나 PRD 금액구간별 경고 기준 이내인 항목</span><span><b>불일치</b> 필드 값이 실제로 다르거나 연결·재검산 근거가 부족해 추가 확인이 필요한 항목</span><small>산출서 여러 행의 합계는 검토용 계산값이며 승인 전 확정값이 아닙니다. 공종 괄호 숫자는 현재 자료 세트의 내역서 항목 수입니다.</small></div>
        {loading ? <div className="review-loading">전처리 결과에서 내역 항목별 검토 결과를 불러오는 중입니다…</div> : <div className="quantity-table-wrap"><table className="quantity-table qa-table"><thead><tr><th>자료 세트</th><th>공사단위</th><th>내역 항목</th><th>검토 결과</th><th>내역 수량</th><th>산출 수량</th><th>차이</th><th>원본 근거</th></tr></thead><tbody>{filtered.map(item => <tr key={item.id} className={selected?.id === item.id ? "selected" : ""} onClick={() => setSelectedId(item.id)}><td><span className={`qa-set-badge ${item.version === "변경" ? "changed" : item.version === "기준↔변경" ? "comparison" : "baseline"}`}>{item.source_set}</span><small>{item.version} 세트</small></td><td><strong title={item.work_package || ""}>{item.work_package || "공사단위 미분류"}</strong><small>{item.discipline || "분야 미지정"}</small></td><td><strong title={titleFor(item)}>{titleFor(item)}</strong><small>{item.item_key || "표준키 미지정"} · {item.sheet_or_drawing || "시트 미지정"}</small></td><td><span className={`severity ${toneFor(item.severity)}`}>{resultCategoryFor(item)}</span>{resultCategoryFor(item) === "불일치" && <small>{mismatchReasonFor(item)}</small>}</td><td>{display(item.original_value)}</td><td>{display(item.recalculated_value)}</td><td>{display(item.difference)}</td><td><span className={item.locator_status === "RESOLVED" ? "qa-evidence-ok" : "qa-evidence-missing"}>{item.locator_status === "RESOLVED" ? "행·시트 확인" : "원천 위치 확인 필요"}</span></td></tr>)}{!filtered.length && <tr><td colSpan={8} className="empty">현재 필터에 해당하는 검토 대상이 없습니다.</td></tr>}</tbody></table></div>}
      </div>
        <aside className="quantity-inspector panel" aria-label="내역·수량 오류 상세">{!selected ? <div className="inspector-empty"><strong>검토 항목을 선택하세요</strong><p>목록에서 항목을 선택하면 문제 유형과 원본 추적정보가 표시됩니다.</p></div> : <><div className="inspector-title"><div><p className="eyebrow">FINDING INSPECTOR</p><h2>오류 분석 상세</h2></div><CandidateBadge status={selected.judgement} /></div><div className="quantity-alert qa-alert"><span className={`severity ${toneFor(selected.severity)}`}>{resultCategoryFor(selected)}</span><strong>{titleFor(selected)}</strong><p>{selected.judgement} · {resultCategoryFor(selected) === "불일치" ? `${mismatchReasonFor(selected)} · ` : ""}{selected.required_action || "원본 근거와 대응 관계를 확인하세요."}</p></div><dl className="inspector-facts"><div><dt>자료 세트</dt><dd>{selected.source_set} · {selected.version}</dd></div><div><dt>공사단위</dt><dd>{selected.work_package || "미분류·원천 확인 필요"}</dd></div><div><dt>자료 분야</dt><dd>{selected.discipline || "미지정"}</dd></div><div><dt>내역서 원본값</dt><dd>{display(selected.original_value)}</dd></div><div><dt>산출서 재계산값</dt><dd>{display(selected.recalculated_value)}</dd></div><div><dt>차이</dt><dd>{display(selected.difference)}</dd></div><div><dt>산출서 문맥</dt><dd>{selected.quantity_context || "문맥 미기록"}</dd></div><div><dt>신뢰도</dt><dd>{selected.confidence || "확인 필요"}</dd></div></dl><section className="inspector-section"><h3>원본 추적</h3><div className={`qa-trace ${selected.locator_status === "RESOLVED" ? "resolved" : "unresolved"}`}><strong>{selected.locator_status === "RESOLVED" ? "원본 위치 확인 가능" : "원천 위치 확인 필요"}</strong><span>{selected.source_locator || "원본 파일·시트·행이 전처리 결과에 없습니다."}</span>{selected.evidence && <small>{selected.evidence}</small>}</div></section><section className="inspector-section"><h3>검토 기준</h3><div className="qa-rule"><span>{selected.rule_version}</span><small>표준화·그룹 합계는 검토용이며 승인 전 수량·금액은 자동 확정하지 않습니다.</small></div></section><div className="inspector-actions"><button type="button" onClick={() => router.push("/review")}>통합 검토 큐로 이동</button><button type="button" className="button-secondary" onClick={() => router.push("/approvals")}>추가자료 요청·승인 화면</button></div></>}</aside>
    </section>

    {selected?.source_set === "기준·변경 대조" && <section className="panel qa-recheck-panel comparison-detail-panel"><div className="panel-head"><div><p className="eyebrow">COMPARISON EVIDENCE</p><h2>선택 항목 기준·변경 근거</h2></div><span className="review-only">승인 전 확인</span></div><p className="qa-note">대조 목록에서 선택한 내역의 기준 원본행과 변경 원본행을 분리해 표시합니다. 변경 사유 확인 전에는 수량을 확정하지 않습니다.</p><div className="comparison-evidence-grid"><div><strong>기준자료 · 수량 {display(selected.original_value)}</strong><span>{selected.baseline_source_locator || "기준 원본행 근거 없음"}</span></div><div><strong>변경자료 · 수량 {display(selected.recalculated_value)}</strong><span>{selected.changed_source_locator || "변경 원본행 근거 없음"}</span></div></div><p className="qa-note">차이 {display(selected.difference)} · 증감률 {selected.comparison_rate || "—"} · 판정 {selected.judgement}</p></section>}
    {!!analysis?.steel_relation_summary?.length && <section className="panel qa-recheck-panel"><div className="panel-head"><div><p className="eyebrow">STEEL MATERIAL / WORK RELATION</p><h2>철골 자재·시공 총량 검토</h2></div><span className="review-only">승인 전 비교값</span></div><p className="qa-note">철골 산출서의 자재구분·부재구분·물량(TON)을 보존해 같은 부재군의 자재와 시공 총량을 비교합니다. 도장·내화 항목은 면적 산식 근거로 표시하며 TON 값에 강제 합산하지 않습니다.</p><div className="qa-recheck-grid">{analysis.steel_relation_summary.map(row => <article key={`${row.version}-${row.member_class}`}><strong>{row.version} · {row.member_class}</strong><div><span>자재 {row.material_ton ?? "—"} TON</span><span>시공 {row.construction_ton ?? "—"} TON</span><b className={row.result === "총량 일치권" ? "ok" : "danger"}>{row.result}</b></div><em>차이 {row.difference_ton ?? "—"} TON · 도장·내화 근거 {row.paint_evidence_count}행</em><small title={row.source_rows.join(" / ")}>{row.rule} · 원본행 {row.source_rows.length}개</small></article>)}</div></section>}
    {!!analysis?.material_construction_relation_summary?.length && <section className="panel qa-recheck-panel"><div className="panel-head"><div><p className="eyebrow">MATERIAL / CONSTRUCTION RELATION</p><h2>재료·시공 관계 후보</h2></div><span className="review-only">승인 전 후보</span></div><p className="qa-note">명시적인 재료·시공 역할과 동일 단위가 확인된 항목만 관계 후보로 묶습니다. 품명만 비슷한 행은 자동 연결하지 않으며, 수량은 검토용 합계입니다.</p><div className="qa-recheck-grid">{analysis.material_construction_relation_summary.map(row => <article key={`${row.version}-${row.relation_family}-${row.unit}`}><strong>{row.version} · {row.relation_family}</strong><div><span>재료 {row.material_quantity ?? "—"} {row.unit}</span><span>시공 {row.construction_quantity ?? "—"} {row.unit}</span><b className={row.result === "총량 일치권" ? "ok" : "danger"}>{row.result}</b></div><em>차이 {row.difference ?? "—"} {row.unit}</em><small title={row.source_rows.join(" / ")}>{row.rule} · 원본행 {row.source_rows.length}개</small></article>)}</div></section>}
    {!!analysis?.steel_coating_formula_summary?.length && <section className="panel qa-recheck-panel"><div className="panel-head"><div><p className="eyebrow">STEEL COATING / FIREPROOFING FORMULA</p><h2>철골 도장·내화 산식 검산</h2></div><span className="review-only">원본 산식만 사용</span></div><p className="qa-note">철골 산출서 안의 녹막이·도장·내화 항목 중 숫자와 사칙연산만으로 구성된 산식을 독립 재계산합니다. 외부 참조·복합식은 재검산 불가로 남기며, 자재 TON과 자동 연결하지 않습니다.</p><div className="qa-recheck-grid">{analysis.steel_coating_formula_summary.map(row => <article key={`${row.version}-${row.item_name}`}><strong>{row.version} · {row.item_name}</strong><div><span>원본 합계 {row.stored_quantity ?? "—"}</span><span>산식 합계 {row.recalculated_quantity ?? "—"}</span><b className={row.mismatch_count || row.source_missing_count ? "danger" : "ok"}>{row.result}</b></div><em>재계산 {row.formula_count}행 · 일치 {row.matched_count}행 · 원본 수량 미추출 {row.source_missing_count}행 · 확인 불가 {row.not_evaluable_count}행</em><small title={row.source_rows.join(" / ")}>{row.rule} · 원본행 {row.source_rows.length}개</small></article>)}</div></section>}
    <section className="panel qa-recheck-panel"><div className="panel-head"><div><p className="eyebrow">FORMULA RECHECK SUMMARY</p><h2>산식 자동 검산 요약</h2></div><span className="review-only">실제 불일치와 구분</span></div><p className="qa-note">자동 검산 결과가 일치한 항목은 오류가 아닙니다. 산식은 있으나 원본 수량이 비어 있는 행은 자동 반영하지 않고 파일·시트·행 근거와 함께 보완 검토 대상으로 남깁니다.</p><div className="qa-recheck-grid">{(analysis?.recheck_summary || []).map(row => <article key={`${row.source_file}-${row.sheet_name}`}><strong>{row.version || "자료"} · {row.sheet_name}</strong><small title={row.source_file}>{row.source_file}</small><div><span>검산 가능 {row.independently_evaluable_count.toLocaleString()}건</span><b className={row.mismatch_count ? "danger" : "ok"}>불일치 {row.mismatch_count.toLocaleString()}건</b><span>원본 수량 미추출 {row.not_evaluable_count.toLocaleString()}건</span></div><em>{row.result} · 신뢰도 {row.confidence}</em>{row.source_rows?.length ? <small title={row.source_rows.join(" / ")}>원본 행 {row.source_rows.length}개</small> : null}</article>)}</div></section>
  </AppShell>;
}
