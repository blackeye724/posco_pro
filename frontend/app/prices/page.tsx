"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { AppShell, CandidateBadge, PageMessage, WorkflowStepper } from "../../components/AppShell";
import { PROJECT_ID, PriceReference, PriceResult, fetchPriceReferences, fetchPriceResults, importPriceReferences, requestPriceLookup, retryPriceLookup, savePriceDecision } from "../../components/api";

const sourceOrder = [
  { key: "same_project", title: "동일 프로젝트 타건물", description: "승인 완료 참고단가", tone: "teal" },
  { key: "official", title: "공식 자료", description: "조달청 CSV·표준시장단가", tone: "blue" },
  { key: "api", title: "조달청 API", description: "앞선 자료가 없을 때 조회", tone: "amber" },
];
const DATA_SCOPE_OPTIONS = ["전체", "운영 자료", "통합 테스트"] as const;
type DataScope = typeof DATA_SCOPE_OPTIONS[number];
const PRICE_SCOPE_OPTIONS = ["전체", "변경자료 신규내역", "기준·변경 대조"] as const;
type PriceScope = typeof PRICE_SCOPE_OPTIONS[number];
function originFor(item: PriceResult): "운영 자료" | "통합 테스트" {
  return [item.item_name, item.evidence, item.candidate_id].filter(Boolean).join(" ").match(/integration-source|demo_|통합 테스트/i) ? "통합 테스트" : "운영 자료";
}

function sourceLabel(item: PriceResult) {
  if (item.source_set === "기준·변경 대조") return "변경 대조 신규";
  if (item.source_set === "변경자료 신규내역") return "변경자료 신규내역";
  if (item.lookup_status.includes("타건물") || item.lookup_status.includes("공식 CSV") || item.lookup_status.includes("표준")) return "공식·참고자료 후보";
  if (item.service_name) return item.service_name;
  return "출처 확인 필요";
}

function priceValueLabel(item: PriceResult) {
  if (item.price != null) return `${item.price.toLocaleString()}원`;
  if (item.lookup_status.includes("조회 결과 없음")) return "조회 결과 없음";
  if (item.lookup_status.includes("조회 보류")) return "조회 보류";
  return "조회값 대기";
}

function priceValueNote(item: PriceResult) {
  return item.price == null ? (item.lookup_status.includes("조회 요청 대기") ? "결과 수신 대기" : "단가 미수신 · 적용 판단 필요") : "확정 전 후보값";
}

export default function PricesPage() {
  const [items, setItems] = useState<PriceResult[]>([]);
  const [dataScope, setDataScope] = useState<DataScope>("전체");
  const [priceScope, setPriceScope] = useState<PriceScope>("전체");
  const [references, setReferences] = useState<PriceReference[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [queryBusy, setQueryBusy] = useState(false);
  const [retryBusy, setRetryBusy] = useState<string | null>(null);
  const [decisionBusy, setDecisionBusy] = useState<string | null>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const reload = () => Promise.all([fetchPriceResults(PROJECT_ID), fetchPriceReferences(PROJECT_ID)]).then(([resultRows, referenceRows]) => { setItems(resultRows); setReferences(referenceRows); setSelectedId(previous => previous && resultRows.some(item => item.id === previous) ? previous : resultRows[0]?.id || null); return resultRows; }).catch(() => { setNotice("단가 검토 결과를 불러오지 못했습니다. API 연결과 권한을 확인하세요."); return []; });
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const requestedScope = params.get("dataScope");
    const requestedPriceScope = params.get("sourceSet");
    if (requestedScope && DATA_SCOPE_OPTIONS.includes(requestedScope as DataScope)) setDataScope(requestedScope as DataScope);
    // Dashboard and drawing links use sourceSet=변경자료 as a concise
    // hand-off. The price queue's concrete source label is 변경자료 신규내역.
    if (requestedPriceScope === "변경자료") setPriceScope("변경자료 신규내역");
    else if (requestedPriceScope && PRICE_SCOPE_OPTIONS.includes(requestedPriceScope as PriceScope)) setPriceScope(requestedPriceScope as PriceScope);
    reload().finally(() => setLoading(false));
  }, []);
  function handleDataScopeChange(value: DataScope) {
    setDataScope(value);
    const params = new URLSearchParams(window.location.search);
    if (value === "전체") params.delete("dataScope"); else params.set("dataScope", value);
    const queryString = params.toString();
    window.history.replaceState({}, "", `${window.location.pathname}${queryString ? `?${queryString}` : ""}`);
  }
  function handlePriceScopeChange(value: PriceScope) {
    setPriceScope(value);
    const params = new URLSearchParams(window.location.search);
    if (value === "전체") params.delete("sourceSet"); else params.set("sourceSet", value);
    const queryString = params.toString();
    window.history.replaceState({}, "", `${window.location.pathname}${queryString ? `?${queryString}` : ""}`);
  }
  const filteredItems = useMemo(() => items.filter(item => (dataScope === "전체" || originFor(item) === dataScope) && (priceScope === "전체" || item.source_set === priceScope)), [items, dataScope, priceScope]);
  const selected = filteredItems.find(item => item.id === selectedId) || filteredItems[0] || null;
  const selectedReferences = useMemo(() => selected ? references.filter(item => [item.original_item, item.standard_item, item.specification, item.unit].filter(Boolean).join(" ").toLowerCase().includes([selected.item_name, selected.specification, selected.unit].filter(Boolean).join(" ").toLowerCase())) : references.slice(0, 6), [references, selected]);

  async function watchLookup(response: PriceResult, initialStatus: string) {
    let rows = await reload();
    setSelectedId(response.id);
    if (initialStatus !== "조회 요청 대기") return;
    for (let attempt = 0; attempt < 5; attempt += 1) {
      await new Promise(resolve => window.setTimeout(resolve, 1000));
      rows = await reload();
      const current = rows.find(item => item.id === response.id || item.candidate_id === response.candidate_id);
      if (current && current.lookup_status !== "조회 요청 대기") {
        setSelectedId(current.id);
        setNotice(`단가 조회 ${current.lookup_status}. ${current.lookup_detail || "결과 수신 후 구매부서 적용 판단이 필요합니다."}`);
        break;
      }
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // React의 submit 이벤트는 await 이후 currentTarget이 null이 될 수 있으므로
    // 폼 참조를 먼저 보관해 요청 완료 후에도 안전하게 초기화합니다.
    const form = event.currentTarget;
    const data = new FormData(event.currentTarget);
    const itemName = String(data.get("item_name") || "").trim();
    const specification = String(data.get("specification") || "").trim();
    const unit = String(data.get("unit") || "").trim();
    if (itemName.length < 2) { setNotice("품명은 2자 이상 입력하세요."); return; }
    if (itemName.length > 200 || specification.length > 200 || unit.length > 40) { setNotice("품명·규격·단위의 입력 길이를 확인하세요."); return; }
    setQueryBusy(true);
    try {
      const response = await requestPriceLookup(PROJECT_ID, { item_name: itemName, specification, unit });
      const status = response.lookup_status || "조회 요청 대기";
      // 수동 조회 결과는 source_set이 없는 API 조회 이력으로 저장됩니다.
      // 대시보드에서 넘어온 '변경자료 신규내역' 필터가 켜져 있으면
      // 방금 만든 후보가 목록에서 사라진 것처럼 보이므로, 요청 직후
      // 전체 후보로 전환해 결과를 바로 확인할 수 있게 합니다.
      if (priceScope !== "전체") handlePriceScopeChange("전체");
      if (dataScope !== "전체") handleDataScopeChange("전체");
      setNotice(status.includes("저장 참고") || status.includes("대체자료") ? `${status}. 조달청 실시간값이 아니라 저장된 참고 후보입니다.` : `단가 조회 ${status}. 결과 수신 후 구매부서 적용 판단이 필요합니다.`);
      form.reset();
      await watchLookup(response, status);
    } catch (error) { setNotice(error instanceof Error ? error.message : "단가 조회 요청에 실패했습니다."); } finally { setQueryBusy(false); }
  }
  async function retry(item: PriceResult) {
    setRetryBusy(item.id);
    try {
      const response = await retryPriceLookup(PROJECT_ID, item.id);
      setNotice("단가 재조회 요청을 접수했습니다. 결과 수신 후 적용 판단이 필요합니다.");
      await watchLookup(response, response.lookup_status || "조회 요청 대기");
    } catch (error) { setNotice(error instanceof Error ? error.message : "단가 재조회 요청에 실패했습니다."); } finally { setRetryBusy(null); }
  }
  async function decide(item: PriceResult, decision: "적용 예정" | "적용 보류") {
    setDecisionBusy(item.id); try { await savePriceDecision(PROJECT_ID, item.id, { decision, reason: decision === "적용 예정" ? "구매부서 검토 결과 적용 후보로 저장" : "출처·조건 추가 확인 후 적용 보류", applied_price: decision === "적용 예정" ? item.price : undefined }); setNotice(`단가를 ${decision} 상태로 저장했습니다. 최종 확정은 별도 승인 전까지 금지됩니다.`); await reload(); } catch (error) { setNotice(error instanceof Error ? error.message : "단가 적용 판단 저장에 실패했습니다."); } finally { setDecisionBusy(null); }
  }
  async function importReferences() { setImportBusy(true); try { const result = await importPriceReferences(PROJECT_ID); setNotice(`${result.imported_count}건의 참고 단가를 저장했습니다. 신규내역 비교용 후보이며 자동 적용되지 않습니다.`); await reload(); } catch (error) { setNotice(error instanceof Error ? error.message : "참고 단가 저장에 실패했습니다."); } finally { setImportBusy(false); } }

  return <AppShell eyebrow="NEW ITEM PRICE REVIEW" title="신규내역 단가 검토">
    <div className="price-scope-bar"><span>프로젝트 <strong>광양5 사무동</strong></span><span>적용 순서 <strong>참고단가 → 공식자료 → API</strong></span><label>자료 범위<select value={dataScope} onChange={event => handleDataScopeChange(event.target.value as DataScope)}>{DATA_SCOPE_OPTIONS.map(option => <option key={option}>{option}</option>)}</select></label><label>검토 대상<select value={priceScope} onChange={event => handlePriceScopeChange(event.target.value as PriceScope)}>{PRICE_SCOPE_OPTIONS.map(option => <option key={option}>{option}</option>)}</select></label><span className="candidate-state">자동 적용 금지</span></div>
    <WorkflowStepper current="price" />
    <p className="lead">출처와 기준일을 비교해 구매부서 적용 후보 또는 보류로 판단합니다. 승인 전 단가는 확정값이 아닙니다.</p>
    {notice && <PageMessage tone={notice.includes("실패") || notice.includes("권한") ? "danger" : "info"}>{notice}</PageMessage>}
    <section className="price-source-order">{sourceOrder.map((source, index) => <div className={`price-source-step ${source.tone}`} key={source.key}><span>0{index + 1}</span><div><strong>{source.title}</strong><small>{source.description}</small></div>{index < sourceOrder.length - 1 && <b className="source-arrow">→</b>}</div>)}</section>
    {!loading && !references.length && <PageMessage tone="warning">저장된 참고단가가 없어 신규내역은 자동 매칭되지 않습니다. 관리자가 참고단가 CSV를 배치한 뒤 아래의 <strong>참고 단가 저장</strong>을 실행하면, 품명·규격·단위가 일치하는 항목만 후보로 표시됩니다.</PageMessage>}
    <section className="price-workspace">
      <div className="price-results-panel panel"><div className="panel-head"><div><p className="eyebrow">PRICE CANDIDATES</p><h2>{loading ? "—" : filteredItems.length}건의 단가 후보</h2></div><span className="review-only">적용 판단 대기</span></div>{loading ? <div className="review-loading">단가 결과를 불러오는 중입니다…</div> : <div className="price-result-list">{filteredItems.map(item => <button type="button" className={`price-result-row ${item.id === selected?.id ? "selected" : ""}`} key={item.id} onClick={() => setSelectedId(item.id)}><div><span className="row-kicker"><span className="tag">{sourceLabel(item)}</span><span>{item.candidate_id}</span></span><strong>{item.item_name || "품명 확인 필요"}</strong><small>{item.specification || "규격 미지정"} · {item.unit || "단위 미지정"}{item.changed_quantity ? ` · 변경수량 ${item.changed_quantity}` : ""}{item.difference ? ` · 차이 ${item.difference}` : ""}{item.reference_match_count ? ` · ${item.reference_match_status} ${item.reference_match_count}건` : " · 참고단가 미확인"}</small></div><div className="price-result-value"><b>{priceValueLabel(item)}</b><CandidateBadge status={item.lookup_status} /></div></button>)}{!filteredItems.length && <div className="empty">현재 자료 범위에 단가 검토 후보가 없습니다.<br /><a className="text-link" href="/quantities?sourceSet=기준·변경 대조&result=불일치">변경자료 대조에서 신규내역 확인 →</a></div>}</div>}</div>
      <aside className="price-inspector panel" aria-label="단가 검토 상세">{!selected ? <div className="inspector-empty"><strong>단가 후보를 선택하세요</strong><p>목록에서 항목을 선택하면 출처와 적용 조건이 표시됩니다.</p></div> : <><div className="inspector-title"><div><p className="eyebrow">PRICE INSPECTOR</p><h2>단가 후보 상세</h2></div><CandidateBadge status={selected.lookup_status} /></div><div className="price-alert"><strong>{selected.item_name || "품명 확인 필요"}</strong><p>{selected.specification || "규격 미지정"} · {selected.unit || "단위 미지정"}</p><div className="price-inspector-value">{priceValueLabel(selected)}<small>{priceValueNote(selected)}</small></div></div><dl className="inspector-facts"><div><dt>조회 서비스</dt><dd>{selected.service_name || "-"}</dd></div><div><dt>조회 상태</dt><dd>{selected.lookup_status || "-"}</dd></div><div><dt>조회 상세</dt><dd>{selected.lookup_detail || "상세 정보 수신 대기"}</dd></div><div><dt>기준일</dt><dd>{selected.reference_date ? new Date(selected.reference_date).toLocaleDateString("ko-KR") : "확인 필요"}</dd></div><div><dt>출처 파일</dt><dd>{selected.source_file_id || "응답·파일 근거 확인 필요"}</dd></div></dl><section className="inspector-section"><h3>우선순위 참고자료</h3>{selectedReferences.slice(0, 5).map(reference => <div className="price-reference-mini" key={reference.id}><strong>{reference.standard_item || reference.original_item || "품명 미지정"}</strong><span>{reference.building_label || "건물 미지정"} · {reference.reference_date ? new Date(reference.reference_date).toLocaleDateString("ko-KR") : "기준일 -"}</span><b>{reference.price == null ? "단가 없음" : `${reference.price.toLocaleString()}원`}</b><small>{reference.provenance || reference.restriction || "비교 참고"}</small></div>)}{!selectedReferences.length && <div className="evidence-empty">일치하는 저장 참고자료가 없습니다.</div>}</section><div className="decision-actions"><button type="button" className="button-secondary" disabled={decisionBusy === selected.id || selected.price == null} onClick={() => decide(selected, "적용 예정")}>적용 후보</button><button type="button" className="button-secondary" disabled={decisionBusy === selected.id} onClick={() => decide(selected, "적용 보류")}>적용 보류</button>{selected.retry_available && <button type="button" className="button-secondary" disabled={retryBusy === selected.id} onClick={() => retry(selected)}>{retryBusy === selected.id ? "재조회 중…" : "재조회"}</button>}{selected.price == null && <small className="evidence-empty">가격이 없어 적용 후보는 비활성화되었습니다. 규격을 보완해 재조회하거나 참고단가를 확인하세요.</small>}</div></>}</aside>
    </section>
    {selected && <section className="panel price-provisional-summary"><div><p className="eyebrow">PROVISIONAL APPLICATION</p><h2>승인 단가 적용 시 잠정 금액</h2><small>{selected.item_name || "품명 확인 필요"} · 검토 수량 {selected.quantity_for_pricing == null ? "확인 필요" : selected.quantity_for_pricing.toLocaleString()} {selected.unit || "단위"}</small></div><div className="price-provisional-value"><b>{selected.provisional_amount == null ? "승인 후 계산" : `${selected.provisional_amount.toLocaleString()}원`}</b><span>{selected.provisional_amount_status || "구매부서 적용 판단 및 수량 확인 후 계산"}</span></div></section>}
    <section className="price-lower-grid"><section className="panel compact"><div className="panel-head"><div><p className="eyebrow">REQUEST LOOKUP</p><h2>조달청 단가 조회 요청</h2><small>요청 후 후보 목록을 전체 범위로 전환해 결과를 바로 표시합니다.</small></div></div><form onSubmit={submit}><label>품명<input name="item_name" required placeholder="예: 시스템 판넬" /></label><label>규격<input name="specification" placeholder="예: 100T, 1200×2400" /></label><label>단위<input name="unit" placeholder="식 / ㎡ / 개" /></label><button disabled={queryBusy}>{queryBusy ? "요청 중…" : "조회 요청"}</button></form></section><section className="panel compact"><div className="panel-head"><div><p className="eyebrow">SAVED REFERENCES</p><h2>저장된 참고 단가 {references.length}건</h2><small>동일 프로젝트 타건물은 후보로, 다른 프로젝트는 참고로만 표시</small></div><button type="button" className="button-secondary" onClick={importReferences} disabled={importBusy}>{importBusy ? "저장 중…" : "참고 단가 저장"}</button></div><div className="reference-summary">{references.slice(0, 6).map(reference => <div key={reference.id}><strong>{reference.standard_item || reference.original_item || "품명 미지정"}</strong><span>{reference.building_label || "건물 미지정"} · {reference.reference_date ? new Date(reference.reference_date).toLocaleDateString("ko-KR") : "기준일 -"}</span><b>{reference.price == null ? "단가 없음" : `${reference.price.toLocaleString()}원`}</b></div>)}{!references.length && <div className="empty">저장된 참고 단가가 없습니다.</div>}</div></section></section>
  </AppShell>;
}
