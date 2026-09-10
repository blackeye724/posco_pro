"use client";

import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";
import { AppShell, PageMessage } from "../../components/AppShell";
import { Evidence, PROJECT_ID, PreprocessingRecord, PreprocessingRun, ProjectScope, SourceFile, Warning, fetchEvidence, fetchPreprocessing, fetchPreprocessingRecords, fetchProjectFiles, fetchProjectScope, fetchWarnings, retryPreprocessing, uploadProjectFile } from "../../components/api";

const accepted = ".pdf,.dwg,.xlsx,.xlsm,.xls,.csv";
const maxBytesByExtension: Record<string, number> = { pdf: 1024 ** 3, dwg: 500 * 1024 ** 2, xlsx: 200 * 1024 ** 2, xlsm: 200 * 1024 ** 2, xls: 200 * 1024 ** 2, csv: 500 * 1024 ** 2 };
const documentTypeLabel: Record<string, string> = { drawing: "도면", estimate: "내역서", quantity: "수량산출서", price_reference: "단가자료", source: "원본 파일", preprocessing_report: "전처리 보고서(레거시)" };
const versionLabel: Record<string, string> = { 기준: "기준자료", 변경: "변경자료", 검토본: "검토본" };
const preprocessingLabel: Record<string, string> = { pending: "처리 대기", queued: "처리 대기", running: "전처리 중", completed: "전처리 완료", failed: "전처리 실패" };
function formatDate(value?: string) { return value ? new Date(value).toLocaleString("ko-KR") : "-"; }

export default function UploadPage() {
  const [scope, setScope] = useState<ProjectScope | null>(null);
  const [buildingId, setBuildingId] = useState("");
  const [workPackageId, setWorkPackageId] = useState("");
  const [versionType, setVersionType] = useState("기준");
  const [referenceDate, setReferenceDate] = useState("");
  const [documentType, setDocumentType] = useState("estimate");
  const [file, setFile] = useState<File | null>(null);
  const [files, setFiles] = useState<SourceFile[]>([]);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [runs, setRuns] = useState<PreprocessingRun[]>([]);
  const [selectedRun, setSelectedRun] = useState("");
  const [records, setRecords] = useState<PreprocessingRecord[]>([]);
  const [recordsBusy, setRecordsBusy] = useState(false);
  const [runWarnings, setRunWarnings] = useState<Warning[]>([]);
  const [runEvidence, setRunEvidence] = useState<Evidence[]>([]);
  const [loading, setLoading] = useState(true);

  const availableWorkPackages = useMemo(() => {
    if (!scope) return [];
    return scope.work_packages.filter(item => !item.building_id || !buildingId || item.building_id === buildingId);
  }, [scope, buildingId]);

  const reload = async () => {
    try {
      const [fileRows, data] = await Promise.all([fetchProjectFiles(PROJECT_ID), fetchPreprocessing(PROJECT_ID)]);
      setFiles(fileRows); setRuns(data.runs || []);
      if (!selectedRun && data.runs?.[0]) setSelectedRun(data.runs[0].id);
    } catch { setNotice("업로드 파일과 전처리 실행 목록을 불러오지 못했습니다."); }
  };
  useEffect(() => {
    Promise.all([fetchProjectScope(PROJECT_ID), reload()]).then(([scopeData]) => {
      setScope(scopeData);
      const firstBuilding = scopeData.buildings[0]?.id || "";
      setBuildingId(firstBuilding);
      setWorkPackageId(scopeData.work_packages.find(item => !item.building_id || item.building_id === firstBuilding)?.id || "");
    }).catch(() => setNotice("프로젝트 범위를 불러오지 못했습니다.")).finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    if (workPackageId && !availableWorkPackages.some(item => item.id === workPackageId)) setWorkPackageId(availableWorkPackages[0]?.id || "");
  }, [availableWorkPackages, workPackageId]);
  useEffect(() => {
    if (!selectedRun) { setRunWarnings([]); setRunEvidence([]); return; }
    Promise.all([fetchWarnings(PROJECT_ID, 1000, selectedRun), fetchEvidence(PROJECT_ID)])
      .then(([warnings, evidence]) => {
        setRunWarnings(warnings.filter(item => item.warning_type === "formula_quantity_missing"));
        setRunEvidence(evidence);
      })
      .catch(() => { setRunWarnings([]); setRunEvidence([]); });
  }, [selectedRun]);

  function choose(event: ChangeEvent<HTMLInputElement>) {
    const candidate = event.target.files?.[0] || null;
    if (!candidate) { setFile(null); return; }
    const extension = candidate.name.split(".").pop()?.toLowerCase() || "";
    const limit = maxBytesByExtension[extension];
    if (!limit) { setFile(null); setNotice("지원하지 않는 파일 형식입니다. PDF·DWG·XLSX·XLSM·XLS·CSV만 업로드하세요."); event.target.value = ""; return; }
    if (candidate.size > limit) { setFile(null); setNotice(`${extension.toUpperCase()} 파일이 허용 크기를 초과했습니다.`); event.target.value = ""; return; }
    setNotice(""); setFile(candidate);
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) { setNotice("업로드할 원본 파일을 선택하세요."); return; }
    if (!buildingId || !workPackageId) { setNotice("건물과 공사단위를 먼저 선택하세요."); return; }
    if (!referenceDate) { setNotice("자료 기준일을 입력하세요. 승인 전 금액·단가는 확정하지 않습니다."); return; }
    setBusy(true);
    const data = new FormData(event.currentTarget);
    const isDrawing = documentType === "drawing";
    try {
      const uploaded = await uploadProjectFile(PROJECT_ID, file, { document_type: documentType, version_type: versionType, building_id: buildingId, work_package_id: workPackageId, reference_date: referenceDate, revision: String(data.get("revision") || (isDrawing ? "UNKNOWN" : "")), drawing_number: String(data.get("drawing_number") || (isDrawing ? "UNKNOWN" : "")), sheet_name: String(data.get("sheet_name") || (isDrawing ? "UNKNOWN" : "")) });
      setNotice(`원본을 보존하고 전처리 작업을 접수했습니다. 작업 ID: ${uploaded.preprocessing_run_id || "확인 중"}`);
      event.currentTarget.reset(); setFile(null); await reload();
    } catch (error) { setNotice(error instanceof Error ? error.message : "파일 업로드에 실패했습니다."); }
    finally { setBusy(false); }
  }
  async function retry(runId: string) {
    setRetrying(runId);
    try { await retryPreprocessing(PROJECT_ID, runId); setNotice(`전처리 작업을 재접수했습니다. 작업 ID: ${runId}`); await reload(); }
    catch (error) { setNotice(error instanceof Error ? error.message : "전처리 재시도에 실패했습니다."); }
    finally { setRetrying(null); }
  }
  async function loadRecords() {
    if (!selectedRun) { setNotice("재검토할 전처리 실행을 선택하세요."); return; }
    setRecordsBusy(true);
    try { setRecords(await fetchPreprocessingRecords(selectedRun, PROJECT_ID, "limit=200")); setNotice("선택한 실행의 원본값·표준화값·근거 위치를 다시 불러왔습니다. 승인 전 검토 후보입니다."); }
    catch (error) { setNotice(error instanceof Error ? error.message : "전처리 결과를 불러오지 못했습니다."); }
    finally { setRecordsBusy(false); }
  }

  return <AppShell eyebrow="00 / SOURCE INTAKE" title="자료 업로드·검증">
    <div className="upload-scope-bar"><span>프로젝트 <strong>{scope?.project.name || "광양5 사무동"}</strong></span><span>건물 <strong>{scope?.buildings.find(item => item.id === buildingId)?.name || "-"}</strong></span><span>상위 공사단위 <strong>{scope?.work_packages.find(item => item.id === workPackageId)?.name || "-"}</strong></span><span className="candidate-state">원본 본문은 파일 저장소에 보존</span></div>
    <p className="lead">자료 세트와 적용 범위를 먼저 지정한 뒤 원본 파일을 등록하세요. 파일 검증 후 내부 표준화·산식 검산·연결 후보 생성은 비동기로 진행되며, DB에는 경로·해시·추적 메타데이터만 기록합니다.</p>
    {notice && <PageMessage tone={notice.includes("실패") || notice.includes("지원") || notice.includes("초과") || notice.includes("먼저") || notice.includes("입력") ? "danger" : "info"}>{notice}</PageMessage>}
    <section className="panel upload-intake-panel"><div className="panel-head"><div><p className="eyebrow">STEP 1 · REVIEW SCOPE</p><h2>검토 범위 지정</h2></div><span className="review-only">승인 전 임시값</span></div>
      <div className="upload-scope-grid"><label>프로젝트<input value={scope?.project.name || "광양5 사무동"} disabled /></label><label>건물<select value={buildingId} onChange={event => setBuildingId(event.target.value)} disabled={!scope}><option value="">선택하세요</option>{scope?.buildings.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>상위 공사단위<select value={workPackageId} onChange={event => setWorkPackageId(event.target.value)} disabled={!scope}><option value="">선택하세요</option>{availableWorkPackages.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>자료 세트<select value={versionType} onChange={event => setVersionType(event.target.value)}><option value="기준">기준자료</option><option value="변경">변경자료</option><option value="검토본">검토본</option></select></label><label>자료 기준일<input type="date" value={referenceDate} onChange={event => setReferenceDate(event.target.value)} /></label></div>
      <p className="field-help scope-hierarchy-note">파일 단위는 상위 공사단위로 지정합니다. 조적·방수·철골 등 세부 공종은 전처리 후 내역 항목의 품명·규격·시트에서 자동 분류되며, 검토 화면에서 필터링합니다.</p>
    </section>
    <section className="split-layout"><section className="panel upload-form-panel"><div className="panel-head"><div><p className="eyebrow">STEP 2 · SOURCE FILE</p><h2>검증된 원본 등록</h2></div><span className="review-only">원본 보존</span></div>
      <form onSubmit={submit}><label className="file-picker"><span className="file-picker-title">파일 선택</span><input type="file" accept={accepted} required onChange={choose}/><small className="field-help">{file ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)}MB` : "PDF(1GB) · DWG(500MB) · XLSX/XLSM(200MB) · CSV(500MB)"}</small></label>
        <label>문서 유형<select value={documentType} onChange={event => setDocumentType(event.target.value)}><option value="drawing">도면</option><option value="estimate">내역서</option><option value="quantity">수량산출서</option><option value="price_reference">단가자료</option></select></label>
        {documentType === "drawing" ? <div className="form-two"><label>도면 Rev.<input name="revision" placeholder="예: Rev.F" /></label><label>도면번호<input name="drawing_number" placeholder="예: A-101" /></label><label>시트<input name="sheet_name" placeholder="예: 합본" /></label></div> : <p className="field-help source-note">도면이 아닌 원본은 파일명·시트·행·셀 정보를 전처리 결과의 근거 위치로 연결합니다.</p>}
        <button disabled={busy || loading}>{busy ? "검증·전처리 접수 중…" : "파일 검증 및 전처리 시작"}</button></form>
    </section><section className="panel compact"><p className="eyebrow">STEP 3 · ASYNC PROCESSING</p><h2>자동 전처리</h2><div className="guardrail"><span className="guardrail-icon">i</span><p>원본 검증 후 내부 워커가 표준화·산식 검산·연결 후보 생성을 수행합니다. 전처리 결과 파일을 별도로 올리지 않으며, 승인 전 수량·금액·단가는 확정하지 않습니다.</p></div><ol className="upload-process-steps"><li><span>1</span>파일 형식·크기·해시 확인</li><li><span>2</span>원본 경로와 추적정보 저장</li><li><span>3</span>전처리 실행과 검토 후보 생성</li></ol><a className="text-link" href="/">현황 대시보드에서 작업 상태 확인 →</a></section></section>
    <section className="panel"><div className="panel-head"><div><p className="eyebrow">SOURCE FILES</p><h2>등록된 원본 {loading ? "—" : `${files.length}건`}</h2></div><span className="review-only">경로·해시·추적정보</span></div>{loading ? <div className="review-loading">원본 파일 목록을 불러오는 중입니다…</div> : <div className="table-wrap"><table className="upload-files-table"><thead><tr><th>파일</th><th>적용 범위</th><th>문서·세트</th><th>도면 식별정보</th><th>상태</th><th>재시도</th></tr></thead><tbody>
      {files.map(item => <tr key={item.id}><td><strong title={item.original_name}>{item.original_name}</strong><small>{formatDate(item.created_at)}</small></td><td>{scope?.buildings.find(row => row.id === item.building_id)?.name || "범위 미지정"}<small>{scope?.work_packages.find(row => row.id === item.work_package_id)?.name || "이전 등록 파일"}</small></td><td><span className="source-type-badge">{documentTypeLabel[item.document_type] || item.document_type}</span><small>{versionLabel[item.version_type] || item.version_type} · 기준일 {item.reference_date ? formatDate(item.reference_date).split(" ")[0] : "미지정"}</small></td><td title={`${item.revision || "-"} · ${item.drawing_number || "-"} · ${item.sheet_name || "-"}`}>{item.revision || item.drawing_number || item.sheet_name ? `${item.revision || "-"} · ${item.drawing_number || "-"} · ${item.sheet_name || "-"}` : "비도면 원본"}</td><td><span className={`status-badge ${item.preprocessing_status === "failed" ? "status-error" : "status-complete"}`}>{item.is_valid ? `검증 완료 · ${preprocessingLabel[item.preprocessing_status || ""] || item.preprocessing_status || "처리 대기"}` : "검증 실패"}</span>{item.preprocessing_error && <small className="field-help">{item.preprocessing_error}</small>}<details><summary>추적정보</summary><code>{item.sha256?.slice(0, 16) || "-"}…</code><small>실행 {item.preprocessing_run_id || "-"}</small></details></td><td>{item.preprocessing_status === "failed" && item.preprocessing_run_id ? <button type="button" className="button-secondary" disabled={retrying === item.preprocessing_run_id} onClick={() => retry(item.preprocessing_run_id as string)}>{retrying === item.preprocessing_run_id ? "재접수 중…" : "재시도"}</button> : "-"}</td></tr>)}
      {!files.length && <tr><td colSpan={6}>등록된 원본 파일이 없습니다.</td></tr>}</tbody></table></div>}</section>
    {selectedRun && <section className="panel upload-exception-panel"><div className="panel-head"><div><p className="eyebrow">PREPROCESSING EXCEPTIONS</p><h2>보완 확인이 필요한 전처리 행 {runWarnings.length ? `${runWarnings.length}건` : "없음"}</h2></div><span className="review-only">자동 확정 금지</span></div><p className="lead">선택한 전처리 실행에서 산식은 추출됐지만 원본 수량이 비어 있는 행입니다. 산식 계산값을 내역 수량으로 자동 적용하지 않고, 원본 위치와 함께 추가자료 요청 대상으로 유지합니다.</p>{runWarnings.length ? <div className="upload-exception-list">{runWarnings.map(warning => <article key={warning.id}><div><strong>{warning.title}</strong><p>{warning.detail}</p><small>원본 수량: {warning.expected_value || "미추출"} · 산식: {warning.actual_value || "미기록"}</small>{runEvidence.filter(item => item.warning_id === warning.id).map(item => <small key={item.id}>근거: {item.file_path || "파일 미지정"} · {item.sheet_name || "시트 미지정"} · {item.row_ref || "행 미지정"}</small>)}</div><a className="button-secondary" href={`/approvals?warning_id=${encodeURIComponent(warning.id)}`}>추가자료 요청·승인 화면 →</a></article>)}</div> : <div className="empty">현재 실행에서 산식·수량 누락 행이 발견되지 않았습니다.</div>}</section>}
    <section className="panel"><div className="panel-head"><div><p className="eyebrow">SELECTIVE RE-REVIEW</p><h2>저장된 전처리 결과 다시 보기</h2></div><span className="review-only">DB 저장·선택 로딩</span></div><p className="lead">필요한 실행만 선택해 원본값·표준화값·근거 위치를 다시 불러옵니다. 이 결과는 승인 전 검토 후보이며 확정값이 아닙니다.</p><div className="form-two"><label>전처리 실행<select value={selectedRun} onChange={event => setSelectedRun(event.target.value)}><option value="">선택하세요</option>{runs.map(run => <option key={run.id} value={run.id}>{formatDate(run.created_at)} · {preprocessingLabel[run.status] || run.status} · {run.processed_count}건</option>)}</select></label><div><button type="button" onClick={loadRecords} disabled={recordsBusy || !selectedRun}>{recordsBusy ? "불러오는 중…" : "선택 실행 결과 로딩"}</button></div></div>{records.length > 0 && <div className="table-wrap"><table className="preprocessing-record-table"><thead><tr><th>종류</th><th>원본 위치</th><th>원본 값</th><th>표준화 값</th><th>상태·신뢰도</th></tr></thead><tbody>{records.map(record => <tr key={record.id}><td>{record.item_kind}</td><td><code title={record.source_locator || "-"}>{record.source_locator || "-"}</code></td><td><code title={JSON.stringify(record.raw_payload)}>{JSON.stringify(record.raw_payload)}</code></td><td><code title={JSON.stringify(record.normalized_payload)}>{JSON.stringify(record.normalized_payload)}</code></td><td>{record.status} · {record.confidence}</td></tr>)}</tbody></table></div>}</section>
  </AppShell>;
}
