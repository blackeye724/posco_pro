"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { AppShell, CandidateBadge, PageMessage, WorkflowStepper } from "../../components/AppShell";
import { PROJECT_ID, PriceReference, PriceResult, fetchPriceReferences, fetchPriceResults, importPriceReferences, requestPriceLookup, savePriceDecision } from "../../components/api";

const sourceOrder = [
  { key: "same_project", title: "동일 프로젝트 타건물", description: "승인 완료 참고단가", tone: "teal" },
  { key: "official", title: "공식 자료", description: "조달청 CSV·표준시장단가", tone: "blue" },
  { key: "api", title: "조달청 API", description: "앞선 자료가 없을 때 조회", tone: "amber" },
];

function sourceLabel(item: PriceResult) {
  if (item.lookup_status.includes("타건물") || item.lookup_status.includes("공식 CSV") || item.lookup_status.includes("표준")) return "공식·참고자료 후보";
  if (item.service_name) return item.service_name;
  return "출처 확인 필요";
}

export default function PricesPage() {
  const [items, setItems] = useState<PriceResult[]>([]);
  const [references, setReferences] = useState<PriceReference[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [queryBusy, setQueryBusy] = useState(false);
  const [decisionBusy, setDecisionBusy] = useState<string | null>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const reload = () => Promise.all([fetchPriceResults(PROJECT_ID), fetchPriceReferences(PROJECT_ID)]).then(([resultRows, referenceRows]) => { setItems(resultRows); setReferences(referenceRows); setSelectedId(previous => previous && resultRows.some(item => item.id === previous) ? previous : resultRows[0]?.id || null); }).catch(() => setNotice("단가 검토 결과를 불러오지 못했습니다. API 연결과 권한을 확인하세요."));
  useEffect(() => { reload().finally(() => setLoading(false)); }, []);
  const selected = items.find(item => item.id === selectedId) || items[0] || null;
  const selectedReferences = useMemo(() => selected ? references.filter(item => [item.original_item, item.standard_item, item.specification, item.unit].filter(Boolean).join(" ").toLowerCase().includes([selected.item_name, selected.specification, selected.unit].filter(Boolean).join(" ").toLowerCase())) : references.slice(0, 6), [references, selected]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const itemName = String(data.get("item_name") || "").trim();
    const specification = String(data.get("specification") || "").trim();
    const unit = String(data.get("unit") || "").trim();
    if (itemName.length < 2) { setNotice("품명은 2자 이상 입력하세요."); return; }
    if (itemName.length > 200 || specification.length > 200 || unit.length > 40) { setNotice("품명·규격·단위의 입력 길이를 확인하세요."); return; }
    setQueryBusy(true);
    try { await requestPriceLookup(PROJECT_ID, { item_name: itemName, specification, unit }); setNotice("조달청 단가 조회를 요청했습니다. 결과 수신 후 구매부서 적용 판단이 필요합니다."); event.currentTarget.reset(); await reload(); } catch (error) { setNotice(error instanceof Error ? error.message : "단가 조회 요청에 실패했습니다."); } finally { setQueryBusy(false); }
  }
  async function decide(item: PriceResult, decision: "적용 예정" | "적용 보류") {
    setDecisionBusy(item.id); try { await savePriceDecision(PROJECT_ID, item.id, { decision, reason: decision === "적용 예정" ? "구매부서 검토 결과 적용 후보로 저장" : "출처·조건 추가 확인 후 적용 보류", applied_price: decision === "적용 예정" ? item.price : undefined }); setNotice(`단가를 ${decision} 상태로 저장했습니다. 최종 확정은 별도 승인 전까지 금지됩니다.`); await reload(); } catch (error) { setNotice(error instanceof Error ? error.message : "단가 적용 판단 저장에 실패했습니다."); } finally { setDecisionBusy(null); }
  }
  async function importReferences() { setImportBusy(true); try { const result = await importPriceReferences(PROJECT_ID); setNotice(`${result.imported_count}건의 참고 단가를 저장했습니다. 신규내역 비교용 후보이며 자동 적용되지 않습니다.`); await reload(); } catch (error) { setNotice(error instanceof Error ? error.message : "참고 단가 저장에 실패했습니다."); } finally { setImportBusy(false); } }

  return <AppShell eyebrow="NEW ITEM PRICE REVIEW" title="신규내역 단가 검토">
    <div className="price-scope-bar"><span>프로젝트 <strong>광양5 사무동</strong></span><span>적용 순서 <strong>참고단가 → 공식자료 → API</strong></span><span className="candidate-state">자동 적용 금지</span></div>
    <WorkflowStepper current="price" />
    <p className="lead">출처와 기준일을 비교해 구매부서 적용 후보 또는 보류로 판단합니다. 승인 전 단가는 확정값이 아닙니다.</p>
    {notice && <PageMessage tone={notice.includes("실패") || notice.includes("권한") ? "danger" : "info"}>{notice}</PageMessage>}
    <section className="price-source-order">{sourceOrder.map((source, index) => <div className={`price-source-step ${source.tone}`} key={source.key}><span>0{index + 1}</span><div><strong>{source.title}</strong><small>{source.description}</small></div>{index < sourceOrder.length - 1 && <b className="source-arrow">→</b>}</div>)}</section>
    <section className="price-workspace">
      <div className="price-results-panel panel"><div className="panel-head"><div><p className="eyebrow">PRICE CANDIDATES</p><h2>{loading ? "—" : items.length}건의 단가 후보</h2></div><span className="review-only">적용 판단 대기</span></div>{loading ? <div className="review-loading">단가 결과를 불러오는 중입니다…</div> : <div className="price-result-list">{items.map(item => <button type="button" className={`price-result-row ${item.id === selected?.id ? "selected" : ""}`} key={item.id} onClick={() => setSelectedId(item.id)}><div><span className="row-kicker"><span className="tag">{sourceLabel(item)}</span><span>{item.candidate_id}</span></span><strong>{item.item_name || "품명 확인 필요"}</strong><small>{item.specification || "규격 미지정"} · {item.unit || "단위 미지정"}</small></div><div className="price-result-value"><b>{item.price == null ? "조회값 대기" : `${item.price.toLocaleString()}원`}</b><CandidateBadge status={item.lookup_status} /></div></button>)}{!items.length && <div className="empty">단가 검토 후보가 없습니다.</div>}</div>}</div>
      <aside className="price-inspector panel" aria-label="단가 검토 상세">{!selected ? <div className="inspector-empty"><strong>단가 후보를 선택하세요</strong><p>목록에서 항목을 선택하면 출처와 적용 조건이 표시됩니다.</p></div> : <><div className="inspector-title"><div><p className="eyebrow">PRICE INSPECTOR</p><h2>단가 후보 상세</h2></div><CandidateBadge status={selected.lookup_status} /></div><div className="price-alert"><strong>{selected.item_name || "품명 확인 필요"}</strong><p>{selected.specification || "규격 미지정"} · {selected.unit || "단위 미지정"}</p><div className="price-inspector-value">{selected.price == null ? "조회값 대기" : `${selected.price.toLocaleString()}원`}<small>확정 전 후보값</small></div></div><dl className="inspector-facts"><div><dt>조회 서비스</dt><dd>{selected.service_name || "-"}</dd></div><div><dt>조회 상태</dt><dd>{selected.lookup_status || "-"}</dd></div><div><dt>기준일</dt><dd>{selected.reference_date ? new Date(selected.reference_date).toLocaleDateString("ko-KR") : "확인 필요"}</dd></div><div><dt>출처 파일</dt><dd>{selected.source_file_id || "응답·파일 근거 확인 필요"}</dd></div></dl><section className="inspector-section"><h3>우선순위 참고자료</h3>{selectedReferences.slice(0, 5).map(reference => <div className="price-reference-mini" key={reference.id}><strong>{reference.standard_item || reference.original_item || "품명 미지정"}</strong><span>{reference.building_label || "건물 미지정"} · {reference.reference_date ? new Date(reference.reference_date).toLocaleDateString("ko-KR") : "기준일 -"}</span><b>{reference.price == null ? "단가 없음" : `${reference.price.toLocaleString()}원`}</b><small>{reference.provenance || reference.restriction || "비교 참고"}</small></div>)}{!selectedReferences.length && <div className="evidence-empty">일치하는 저장 참고자료가 없습니다.</div>}</section><div className="decision-actions"><button type="button" className="button-secondary" disabled={decisionBusy === selected.id || selected.price == null} onClick={() => decide(selected, "적용 예정")}>적용 후보</button><button type="button" className="button-secondary" disabled={decisionBusy === selected.id} onClick={() => decide(selected, "적용 보류")}>적용 보류</button></div></>}</aside>
    </section>
    <section className="price-lower-grid"><section className="panel compact"><div className="panel-head"><div><p className="eyebrow">REQUEST LOOKUP</p><h2>조달청 단가 조회 요청</h2></div></div><form onSubmit={submit}><label>품명<input name="item_name" required placeholder="예: 시스템 판넬" /></label><label>규격<input name="specification" placeholder="예: 100T, 1200×2400" /></label><label>단위<input name="unit" placeholder="식 / ㎡ / 개" /></label><button disabled={queryBusy}>{queryBusy ? "요청 중…" : "조회 요청"}</button></form></section><section className="panel compact"><div className="panel-head"><div><p className="eyebrow">SAVED REFERENCES</p><h2>저장된 참고 단가 {references.length}건</h2><small>동일 프로젝트 타건물은 후보로, 다른 프로젝트는 참고로만 표시</small></div><button type="button" className="button-secondary" onClick={importReferences} disabled={importBusy}>{importBusy ? "저장 중…" : "참고 단가 저장"}</button></div><div className="reference-summary">{references.slice(0, 6).map(reference => <div key={reference.id}><strong>{reference.standard_item || reference.original_item || "품명 미지정"}</strong><span>{reference.building_label || "건물 미지정"} · {reference.reference_date ? new Date(reference.reference_date).toLocaleDateString("ko-KR") : "기준일 -"}</span><b>{reference.price == null ? "단가 없음" : `${reference.price.toLocaleString()}원`}</b></div>)}{!references.length && <div className="empty">저장된 참고 단가가 없습니다.</div>}</div></section></section>
  </AppShell>;
}
