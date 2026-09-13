"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell, CandidateBadge, PageMessage, WorkflowStepper } from "../../components/AppShell";
import { BaselineChangedComparison, DrawingCandidate, PROJECT_ID, drawingPdfPreviewUrl, fetchDrawings, fetchDrawingPdf, fetchQuantityAnalysis } from "../../components/api";

const DATA_SCOPE_OPTIONS = ["전체", "운영 자료", "통합 테스트"] as const;
type DataScope = typeof DATA_SCOPE_OPTIONS[number];

function originFor(item: DrawingCandidate): "운영 자료" | "통합 테스트" {
  return [item.baseline_file, item.changed_file, item.candidate_text, item.source_row_ref].filter(Boolean).join(" ").match(/integration-source|demo_|통합 테스트/i) ? "통합 테스트" : "운영 자료";
}

function locationBucketFor(item: DrawingCandidate): "자동 위치 후보 가능" | "위치 후보" | "부위 미확정" {
  const status = item.location_status || "";
  if (status.includes("자동 위치 후보 사용 가능") || status.includes("좌표 정렬 가능")) return "자동 위치 후보 가능";
  if (status.includes("위치 후보만 기록")) return "위치 후보";
  return "부위 미확정";
}

function shortFileName(path?: string) {
  if (!path) return "원본 경로 확인 필요";
  return path.split(/[\\/]/).pop() || path;
}

function pdfPageRef(page?: number) {
  return page ? `PDF p.${page}` : "PDF 페이지 확인 필요";
}

type HighlightRegion = { left: string; top: string; width: string; height: string; label: string };
type ScaffoldSummary = BaselineChangedComparison & { secondary_item_text: string; secondary_baseline_quantity: string; secondary_changed_quantity: string; secondary_difference: string };

function workPackageParts(value?: string) {
  return (value || "").split("·").map(part => part.trim()).filter(Boolean);
}

const CANONICAL_DRAWING_PACKAGES = [
  "가설공사", "단열공사", "방수공사", "조적공사", "철골공사", "철근콘크리트공사", "토공사",
  "타일공사", "석공사", "유리공사", "금속공사", "미장공사", "도장공사", "수장공사", "패널공사",
  "창호공사", "홈통공사", "승강기공사",
] as const;

function canonicalWorkPackages(value?: string) {
  return CANONICAL_DRAWING_PACKAGES.filter(packageName => workPackageParts(value).includes(packageName)).sort((left, right) => summaryPriority(left) - summaryPriority(right));
}

function displayWorkPackage(value?: string) {
  return canonicalWorkPackages(value)[0] || "기타·원천 확인 필요";
}

function candidateTextForTrade(candidate: DrawingCandidate, selectedTrade?: string) {
  const text = candidate.candidate_text || "변경 설명이 전처리 결과에 기록되지 않았습니다.";
  if (!selectedTrade || !text.includes("/") && !text.includes("|") && !text.includes("·")) return text;
  const parts = text.split(/\s*[\|\/·]\s*/).map(part => part.trim()).filter(Boolean);
  const tokenByTrade: Record<string, RegExp> = {
    "가설공사": /가설|비계|규준틀|먹매김|현장정리|동바리|안전/,
    "단열공사": /단열|보온|압출|글라스울|그라스울/,
    "조적공사": /조적|벽돌|블록/,
    "방수공사": /방수|우레탄|시트방수/,
    "타일공사": /타일|자기질|도기질/,
    "철골공사": /철골|형강|H[- ]?빔|강재/,
    "철근콘크리트공사": /콘크리트|철근|거푸집|무근|레미콘/,
    "토공사": /토공|잡석|흙|되메우기|굴착|성토|지반/,
    "석공사": /석재|화강석|대리석|인조대리석|포천석/,
    "유리공사": /유리|강화|복층|로이|GLASS/,
    "금속공사": /금속|몰딩|알루미늄|AL[.]|난간|논슬립|철판|스텐|사인/,
    "미장공사": /미장|몰탈|모르타르|시멘트몰탈|바름|조면/,
    "도장공사": /도장|페인트|분체|도료|도막/,
    "수장공사": /수장|천장|텍스|마감|벽지|흡음|도배|마루|장판/,
    "패널공사": /패널|판넬|메탈|샌드위치|외벽|외장/,
    "창호공사": /창호|문|DOOR|FSD|SSD|ASD|SD[ _-]?E?|알루미늄창/,
    "홈통공사": /홈통|루프드레인|선홈통|우수|배수|거터|GUTTER/,
    "승강기공사": /승강기|엘리베이터|ELEV/,
  };
  const pattern = tokenByTrade[selectedTrade];
  const match = pattern ? parts.find(part => pattern.test(part)) : undefined;
  return match || text;
}

function drawingReferenceLabel(candidate: DrawingCandidate, selectedTrade?: string) {
  const sheet = candidate.drawing_number || candidate.sheet_number || "확인 필요";
  // 유리공사는 평면도보다 창호도·외부측면도에서 규격과 위치를
  // 이해하기 쉽다. 실제 시트 분류를 단정하지 않고, 해당 후보가
  // 참고해야 할 도면 종류임을 화면에 명시한다.
  if (selectedTrade === "유리공사") {
    if (sheet === "1A-701") return `외부측면도 후보 ${sheet}`;
    if (sheet === "1A-401") return `창호도 후보 ${sheet}`;
    return `창호도·외부측면도 후보 ${sheet}`;
  }
  if (selectedTrade === "석공사") {
    if (sheet === "1A-701") return `외부측면도 후보 ${sheet}`;
    return `석재 상세도 후보 ${sheet}`;
  }
  if (selectedTrade === "조적공사") return `조적 평면도 후보 ${sheet}`;
  if (selectedTrade === "방수공사") return `방수 평면·상세도 후보 ${sheet}`;
  if (selectedTrade === "단열공사") return `단열 도면 후보 ${sheet}`;
  if (selectedTrade === "철골공사") return `철골 구조도 후보 ${sheet}`;
  if (selectedTrade === "철근콘크리트공사") return `구조 평면·상세도 후보 ${sheet}`;
  if (selectedTrade === "토공사") return `토공·기초도 후보 ${sheet}`;
  if (selectedTrade === "타일공사") return `타일 마감도 후보 ${sheet}`;
  if (selectedTrade === "금속공사") return `금속 상세도 후보 ${sheet}`;
  if (selectedTrade === "미장공사") return `미장 마감도 후보 ${sheet}`;
  if (selectedTrade === "도장공사") return `도장 마감도 후보 ${sheet}`;
  if (selectedTrade === "수장공사") return `실내 마감도 후보 ${sheet}`;
  if (selectedTrade === "패널공사") return `패널 외벽도 참고 ${sheet}`;
  if (selectedTrade === "창호공사") return `창호도 후보 ${sheet}`;
  if (selectedTrade === "홈통공사") return `지붕·우수 배수도 참고 ${sheet}`;
  if (selectedTrade === "승강기공사") return `승강기 사양도 참고 ${sheet}`;
  if (selectedTrade === "가설공사") return "4층·5층 평면도 참고";
  return `도면 구간 ${sheet}`;
}

function glassDrawingPriority(candidate: DrawingCandidate) {
  const sheet = candidate.drawing_number || candidate.sheet_number || "";
  const text = candidate.candidate_text || "";
  const isGlazingSpec = /로이복층유리|복층유리/.test(text);
  if (sheet === "1A-701" && isGlazingSpec) return 0;
  if (sheet === "1A-401" && isGlazingSpec) return 1;
  if (isGlazingSpec) return 2;
  if (/강화유리/.test(text)) return 3;
  return 4;
}

function stoneDrawingPriority(candidate: DrawingCandidate) {
  const sheet = candidate.drawing_number || candidate.sheet_number || "";
  const text = candidate.candidate_text || "";
  if (sheet === "1A-701" && /화강석.*물갈기/.test(text)) return 0;
  if (sheet === "1A-111" && /화강석.*물갈기/.test(text)) return 1;
  if (/화강석.*물갈기/.test(text)) return 2;
  if (/화강석|인조대리석/.test(text)) return 3;
  return 4;
}

function insulationDrawingPriority(candidate: DrawingCandidate) {
  const sheet = candidate.drawing_number || candidate.sheet_number || "";
  const text = candidate.candidate_text || "";
  if (sheet === "1A-701" && /90\s*(?:mm|㎜)?[^\n]*압출법보온판/.test(text)) return 0;
  if (/90\s*(?:mm|㎜)?[^\n]*압출법보온판/.test(text)) return 1;
  if (/압출법보온판/.test(text)) return 2;
  if (/단열재/.test(text)) return 3;
  if (/완충스티로폼/.test(text)) return 4;
  return 4;
}

function quantityText(value?: string | null) {
  if (value === undefined || value === null || value === "") return "—";
  const numeric = Number(value);
  return Number.isFinite(numeric) ? new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 3 }).format(numeric) : value;
}

function textMatchScore(candidateText?: string, itemText?: string) {
  const normalizedItem = (itemText || "").replace(/[^\p{L}\p{N}]/gu, "").toLowerCase();
  if (!normalizedItem) return 0;
  const terms = Array.from(new Set((candidateText || "").toLowerCase().match(/[\p{L}\p{N}]+/gu) || []));
  return terms.filter(term => term.length >= 2 && normalizedItem.includes(term)).reduce((score, term) => score + term.length, 0);
}

function officeDoorComparison(comparisons: BaselineChangedComparison[]) {
  const rows = comparisons.filter(item => item.work_package === "창호공사"
    && /^(?:FSD|SSD|ASD|AD|SD(?:[_-]?E)?)/i.test(item.item_text || "")
    && /2[.]?사무동/.test(item.item_text || "")
    && item.baseline_count <= 1
    && item.changed_count <= 1
    && (item.baseline_quantity == null || (Number.isFinite(Number(item.baseline_quantity)) && Number(item.baseline_quantity) <= 100))
    && (item.changed_quantity == null || (Number.isFinite(Number(item.changed_quantity)) && Number(item.changed_quantity) <= 100))
    && (item.baseline_quantity != null || item.changed_quantity != null));
  if (!rows.length) return undefined;
  const baseline = rows.reduce((sum, item) => sum + Number(item.baseline_quantity || 0), 0);
  const changed = rows.reduce((sum, item) => sum + Number(item.changed_quantity || 0), 0);
  const difference = changed - baseline;
  const sourceRows = rows.flatMap(item => item.source_rows || []).slice(0, 20);
  return {
    work_package: "창호공사",
    item_key: "사무동전체문수량",
    comparison_key: "사무동전체문수량|ea",
    representative_baseline_quantity: String(baseline),
    representative_changed_quantity: String(changed),
    representative_source_rows: sourceRows,
    item_text: "사무동 전체 문 수량(EA)",
    baseline_quantity: String(baseline),
    changed_quantity: String(changed),
    difference: String(difference),
    difference_rate: baseline ? `${((difference / baseline) * 100).toFixed(2)}%` : null,
    comparison_band: "mismatch",
    comparison_tolerance: null,
    comparison_tolerance_rate: null,
    comparison_rule: "사무동 문 본체 코드(SD/AD/ASD) 전체 수량 비교",
    result: difference >= 0 ? "변경 후 증가" : "변경 후 감소",
    baseline_count: rows.filter(item => item.baseline_quantity != null).length,
    changed_count: rows.filter(item => item.changed_quantity != null).length,
    source_rows: sourceRows,
    rule: "사무동 문 본체 코드(SD/AD/ASD) 전체 수량 비교",
  } satisfies BaselineChangedComparison;
}

function scaffoldSummary(comparisons: BaselineChangedComparison[]): ScaffoldSummary | undefined {
  const cleanup = comparisons.find(item => item.work_package === "가설공사"
    && item.item_key === "건축물현장정리"
    && item.comparison_key?.includes("|철콘공사|m2")
    && item.representative_baseline_quantity != null
    && item.representative_changed_quantity != null);
  const setout = comparisons.find(item => item.work_package === "가설공사"
    && item.item_key === "구조부먹매김"
    && item.comparison_key?.includes("|일반|m2")
    && item.representative_baseline_quantity != null
    && item.representative_changed_quantity != null);
  if (!cleanup || !setout) return undefined;
  const baseline = Number(cleanup.representative_baseline_quantity);
  const changed = Number(cleanup.representative_changed_quantity);
  const secondaryBaseline = Number(setout.representative_baseline_quantity);
  const secondaryChanged = Number(setout.representative_changed_quantity);
  if (![baseline, changed, secondaryBaseline, secondaryChanged].every(Number.isFinite)) return undefined;
  return {
    ...cleanup,
    item_text: "현장정리·구조부 먹매김 (4층→5층 증축)",
    baseline_quantity: String(baseline),
    changed_quantity: String(changed),
    difference: String(changed - baseline),
    difference_rate: baseline ? `${(((changed - baseline) / baseline) * 100).toFixed(2)}%` : null,
    comparison_rule: "4층→5층 증축 면적에 따른 가설공사 병렬 지표",
    rule: "현장정리·구조부 먹매김은 동일 증축 면적의 교차 근거로 표시하며 합산하지 않음",
    secondary_item_text: "구조부 먹매김",
    secondary_baseline_quantity: String(secondaryBaseline),
    secondary_changed_quantity: String(secondaryChanged),
    secondary_difference: String(secondaryChanged - secondaryBaseline),
  };
}

function panelRepresentative(comparisons: BaselineChangedComparison[]) {
  // 패널공사는 설치·재료비를 각각 대표 카드로 나누지 않고,
  // 외벽 100T 메탈패널 설치 면적을 단일 기준으로 표시한다.
  // 재료비 행(그라스울 외벽 100T)은 보조 교차 근거로만 사용하며,
  // 서로 다른 규격·부위를 합산하지 않는다.
  return comparisons.find(item => item.work_package === "패널공사"
    && item.item_key === "메탈패널설치"
    && item.comparison_key?.includes("|외벽100t|m2")
    && item.baseline_quantity != null
    && item.changed_quantity != null
    && item.result.includes("변경 후"));
}

function gutterRepresentative(comparisons: BaselineChangedComparison[]) {
  // 홈통공사는 선홈통 길이·상자홈통·루프드레인이 서로 다른 단위와
  // 규격으로 반복된다. 기준·변경이 1:1로 연결되는 루프드레인 L형
  // D150을 대표 EA 항목으로 고정하고 다른 규격은 섞지 않는다.
  return comparisons.find(item => item.work_package === "홈통공사"
    && item.item_key === "루프드레인설치"
    && item.comparison_key?.includes("|l형d150mm코킹포함|ea")
    && item.baseline_quantity != null
    && item.changed_quantity != null
    && item.result.includes("변경 후"));
}

function elevatorRepresentative(comparisons: BaselineChangedComparison[]) {
  // 승강기는 대수보다 정차층 사양 전환이 핵심이다. 4STOP 기존행과
  // 5STOP 변경행을 짝지어 표시하고, 변경자료에서 잘못 읽힌 대수값
  // (7.6646e+07)는 대표 물량에 사용하지 않는다.
  const baseline = comparisons.find(item => item.work_package === "승강기공사"
    && item.item_key === "승객용엘리베이터"
    && item.comparison_key?.includes("|24인승4stop장애인용|대")
    && item.baseline_quantity != null);
  const changed = comparisons.find(item => item.work_package === "승강기공사"
    && item.item_key === "승객용엘리베이터"
    && item.comparison_key?.includes("|24인승5stop장애인용|대")
    && item.changed_quantity != null);
  if (!baseline || !changed) return undefined;
  const sourceRows = Array.from(new Set([...(baseline.source_rows || []), ...(changed.source_rows || [])]));
  return {
    work_package: "승강기공사",
    item_key: "승객용엘리베이터사양변경",
    comparison_key: "승객용엘리베이터|24인승4stop장애인용→24인승5stop장애인용|대",
    representative_baseline_quantity: "1",
    representative_changed_quantity: "1",
    representative_source_rows: sourceRows,
    item_text: "승객용 엘리베이터 (4STOP→5STOP)",
    baseline_quantity: "1",
    changed_quantity: "1",
    difference: "0",
    difference_rate: "0%",
    comparison_band: "spec_change",
    comparison_tolerance: null,
    comparison_tolerance_rate: null,
    comparison_rule: "승객용 엘리베이터 정차층 사양 전환(수량 오류 행 제외)",
    result: "사양 변경",
    baseline_count: 1,
    changed_count: 1,
    source_rows: sourceRows,
    rule: "24인승 4STOP 기존행과 24인승 5STOP 변경행을 사양 변경으로 표시",
  } satisfies BaselineChangedComparison;
}

function representativeComparison(candidate: DrawingCandidate, comparisons: BaselineChangedComparison[]) {
  const packages = workPackageParts(candidate.work_package);
  // 대표 변경 카드는 설계변경으로 실제 증감이 보이는 품목을 우선한다.
  // 철골보는 내역서↔수량산출서 일치 검증용이므로 이 화면의 대표 변경에서
  // 제외하고, 사용자가 선택한 H형강(SM355A)을 대표로 고정한다.
  if (packages.includes("철골공사")) {
    const steelRepresentative = comparisons.find(item => item.work_package === "철골공사" && item.item_text === "H형강(SM355A)" && item.result.includes("변경 후"));
    if (steelRepresentative) return steelRepresentative;
  }
  if (packages.includes("조적공사")) {
    const masonryRepresentative = comparisons.find(item => item.work_package === "조적공사" && item.item_text === "0.5B 시멘트벽돌쌓기" && item.result.includes("변경 후"));
    if (masonryRepresentative) return masonryRepresentative;
  }
  if (packages.includes("방수공사")) {
    const waterproofRepresentative = comparisons.find(item => item.work_package === "방수공사" && item.item_text === "무기질탄성도막방수(내부)" && item.result.includes("변경 후"));
    if (waterproofRepresentative) return waterproofRepresentative;
  }
  if (packages.includes("금속공사")) {
    // 금속공사는 같은 품명으로 추가행이 생긴 경우 합계가 부풀 수 있으므로,
    // 대표 1:1 연결값(AL몰딩설치)을 카드에 표시한다.
    const metalRepresentative = comparisons.find(item => item.work_package === "금속공사"
      && item.item_key === "al몰딩설치"
      && item.comparison_key?.includes("|w형1515151510mm|m")
      && item.result.includes("변경 후"));
    if (metalRepresentative) {
      const baseline = Number(metalRepresentative.representative_baseline_quantity ?? metalRepresentative.baseline_quantity);
      const changed = Number(metalRepresentative.representative_changed_quantity ?? metalRepresentative.changed_quantity);
      const difference = Number.isFinite(baseline) && Number.isFinite(changed) ? changed - baseline : undefined;
      return {
        ...metalRepresentative,
        baseline_quantity: metalRepresentative.representative_baseline_quantity ?? metalRepresentative.baseline_quantity,
        changed_quantity: metalRepresentative.representative_changed_quantity ?? metalRepresentative.changed_quantity,
        difference: difference === undefined ? metalRepresentative.difference : String(Number(difference.toFixed(3))),
        difference_rate: Number.isFinite(baseline) && baseline !== 0 && difference !== undefined ? `${((difference / baseline) * 100).toFixed(2)}%` : metalRepresentative.difference_rate,
        source_rows: metalRepresentative.representative_source_rows?.length ? metalRepresentative.representative_source_rows : metalRepresentative.source_rows,
      };
    }
  }
  if (packages.includes("미장공사")) {
    // 미장공사는 바닥 모르타르가 두께별로 반복되므로 대표 규격을
    // 고정해 서로 다른 산식·단위를 합산하지 않는다.
    const plasterRepresentative = comparisons.find(item => item.work_package === "미장공사"
      && item.item_key === "모르타르바름바닥"
      && item.comparison_key?.includes("|t77mm기계마감몰탈포함|m2")
      && item.result.includes("변경 후"));
    if (plasterRepresentative) {
      const baseline = Number(plasterRepresentative.representative_baseline_quantity ?? plasterRepresentative.baseline_quantity);
      const changed = Number(plasterRepresentative.representative_changed_quantity ?? plasterRepresentative.changed_quantity);
      const difference = Number.isFinite(baseline) && Number.isFinite(changed) ? changed - baseline : undefined;
      return {
        ...plasterRepresentative,
        baseline_quantity: plasterRepresentative.representative_baseline_quantity ?? plasterRepresentative.baseline_quantity,
        changed_quantity: plasterRepresentative.representative_changed_quantity ?? plasterRepresentative.changed_quantity,
        difference: difference === undefined ? plasterRepresentative.difference : String(Number(difference.toFixed(3))),
        difference_rate: Number.isFinite(baseline) && baseline !== 0 && difference !== undefined ? `${((difference / baseline) * 100).toFixed(2)}%` : plasterRepresentative.difference_rate,
        source_rows: plasterRepresentative.representative_source_rows?.length ? plasterRepresentative.representative_source_rows : plasterRepresentative.source_rows,
      };
    }
  }
  if (packages.includes("도장공사")) {
    // 도장공사는 같은 품명이 내벽·천정·걸레받이 등으로 반복되므로
    // 내벽 2회·준불연 규격을 대표로 고정해 부위별 수량을 섞지 않는다.
    const paintingRepresentative = comparisons.find(item => item.work_package === "도장공사"
      && item.item_key === "친환경수성페인트로울러칠"
      && item.comparison_key?.includes("|내벽2회1급gb면준불연이상|m2")
      && item.result.includes("변경 후"));
    if (paintingRepresentative) {
      const baseline = Number(paintingRepresentative.representative_baseline_quantity ?? paintingRepresentative.baseline_quantity);
      const changed = Number(paintingRepresentative.representative_changed_quantity ?? paintingRepresentative.changed_quantity);
      const difference = Number.isFinite(baseline) && Number.isFinite(changed) ? changed - baseline : undefined;
      return {
        ...paintingRepresentative,
        baseline_quantity: paintingRepresentative.representative_baseline_quantity ?? paintingRepresentative.baseline_quantity,
        changed_quantity: paintingRepresentative.representative_changed_quantity ?? paintingRepresentative.changed_quantity,
        difference: difference === undefined ? paintingRepresentative.difference : String(Number(difference.toFixed(3))),
        difference_rate: Number.isFinite(baseline) && baseline !== 0 && difference !== undefined ? `${((difference / baseline) * 100).toFixed(2)}%` : paintingRepresentative.difference_rate,
        source_rows: paintingRepresentative.representative_source_rows?.length ? paintingRepresentative.representative_source_rows : paintingRepresentative.source_rows,
      };
    }
  }
  if (packages.includes("수장공사")) {
    // 흡음텍스는 규격(300/600)별로 별도 항목이므로 대표 천정 규격만
    // 고정해 서로 다른 패널 물량을 합산하지 않는다.
    const interiorFinishRepresentative = comparisons.find(item => item.work_package === "수장공사"
      && item.item_key === "흡음텍스붙임"
      && item.comparison_key?.includes("|60060012t마이텍스|m2")
      && item.result.includes("변경 후"));
    if (interiorFinishRepresentative) {
      const baseline = Number(interiorFinishRepresentative.representative_baseline_quantity ?? interiorFinishRepresentative.baseline_quantity);
      const changed = Number(interiorFinishRepresentative.representative_changed_quantity ?? interiorFinishRepresentative.changed_quantity);
      const difference = Number.isFinite(baseline) && Number.isFinite(changed) ? changed - baseline : undefined;
      return {
        ...interiorFinishRepresentative,
        baseline_quantity: interiorFinishRepresentative.representative_baseline_quantity ?? interiorFinishRepresentative.baseline_quantity,
        changed_quantity: interiorFinishRepresentative.representative_changed_quantity ?? interiorFinishRepresentative.changed_quantity,
        difference: difference === undefined ? interiorFinishRepresentative.difference : String(Number(difference.toFixed(3))),
        difference_rate: Number.isFinite(baseline) && baseline !== 0 && difference !== undefined ? `${((difference / baseline) * 100).toFixed(2)}%` : interiorFinishRepresentative.difference_rate,
        source_rows: interiorFinishRepresentative.representative_source_rows?.length ? interiorFinishRepresentative.representative_source_rows : interiorFinishRepresentative.source_rows,
      };
    }
  }
  if (packages.includes("창호공사")) {
    // 창호공사는 개별 코드보다 사무동 문 본체 전체 수량이 검토 목적에
    // 더 적합하다. SD/AD/ASD 문 코드 중 사무동 표기가 있고, 치수 오인
    // 또는 부속품이 아닌 정상 EA 행만 합산한다.
    const doorRepresentative = officeDoorComparison(comparisons);
    if (doorRepresentative) return doorRepresentative;
  }
  if (packages.includes("유리공사")) {
    // 유리자재와 유리시공을 각각 대표 카드로 만들지 않고,
    // 실제 시공면적을 나타내는 유리끼우기 24mm 이하를 단일 기준으로
    // 사용한다. 자재 규격은 도면 후보 텍스트와 원본행 근거로만 보조한다.
    const glazingRepresentative = comparisons.find(item => item.work_package === "유리공사"
      && item.item_key === "유리끼우기복층유리"
      && item.comparison_key?.includes("|24mm이하|m2")
      && item.baseline_quantity != null
      && item.changed_quantity != null
      && item.result.includes("변경 후"));
    if (glazingRepresentative) return glazingRepresentative;
  }
  if (packages.includes("석공사")) {
    // 석공사는 자재명과 붙임 시공을 중복 카드로 만들지 않고,
    // 대표 면적 시공항목(수마 30mm 포천석) 하나만 비교한다.
    const stoneRepresentative = comparisons.find(item => item.work_package === "석공사"
      && item.item_key === "화강석붙임바닥"
      && item.comparison_key?.includes("|수마30mm포천석몰탈50|m2")
      && item.baseline_quantity != null
      && item.changed_quantity != null
      && item.result.includes("변경 후"));
    if (stoneRepresentative) return stoneRepresentative;
  }
  if (packages.includes("단열공사")) {
    // 단열재 자재·부속 선형 항목을 별도 카드로 나누지 않고,
    // 대표 바닥 단열 시공면적(90mm 1호) 하나만 비교한다.
    const insulationRepresentative = comparisons.find(item => item.work_package === "단열공사"
      && item.item_key === "압출발포폴리스티렌설치슬래브위깔기바닥"
      && item.comparison_key?.includes("|90mm1호|m2")
      && item.baseline_quantity != null
      && item.changed_quantity != null
      && item.result.includes("변경 후"));
    if (insulationRepresentative) return insulationRepresentative;
  }
  if (packages.includes("패널공사")) {
    const panelRepresentativeRow = panelRepresentative(comparisons);
    if (panelRepresentativeRow) return panelRepresentativeRow;
  }
  if (packages.includes("홈통공사")) {
    const gutterRepresentativeRow = gutterRepresentative(comparisons);
    if (gutterRepresentativeRow) return gutterRepresentativeRow;
  }
  if (packages.includes("승강기공사")) {
    const elevatorRepresentativeRow = elevatorRepresentative(comparisons);
    if (elevatorRepresentativeRow) return elevatorRepresentativeRow;
  }
  if (packages.includes("철근콘크리트공사")) {
    // 콘크리트는 같은 품명으로 강도·용도별 행이 반복되므로
    // 품명만 비교하지 않고 양호(S15)·m3 규격키까지 고정한다.
    const concreteRepresentative = comparisons.find(item => item.work_package === "철근콘크리트공사"
      && item.item_key === "철근콘크리트타설펌프카"
      && item.comparison_key?.includes("|양호s15|m3")
      && item.result.includes("변경 후"));
    if (concreteRepresentative) {
      const baseline = Number(concreteRepresentative.representative_baseline_quantity ?? concreteRepresentative.baseline_quantity);
      const changed = Number(concreteRepresentative.representative_changed_quantity ?? concreteRepresentative.changed_quantity);
      const difference = Number.isFinite(baseline) && Number.isFinite(changed) ? changed - baseline : undefined;
      return {
        ...concreteRepresentative,
        baseline_quantity: concreteRepresentative.representative_baseline_quantity ?? concreteRepresentative.baseline_quantity,
        changed_quantity: concreteRepresentative.representative_changed_quantity ?? concreteRepresentative.changed_quantity,
        difference: difference === undefined ? concreteRepresentative.difference : String(Number(difference.toFixed(3))),
        difference_rate: Number.isFinite(baseline) && baseline !== 0 && difference !== undefined ? `${((difference / baseline) * 100).toFixed(2)}%` : concreteRepresentative.difference_rate,
        source_rows: concreteRepresentative.representative_source_rows?.length ? concreteRepresentative.representative_source_rows : concreteRepresentative.source_rows,
      };
    }
  }
  if (packages.includes("토공사")) {
    const earthworkRepresentative = comparisons.find(item => item.work_package === "토공사"
      && item.item_key === "터파기백호우07m3"
      && item.comparison_key?.includes("|토사|m3")
      && item.result.includes("변경 후"));
    if (earthworkRepresentative) {
      const baseline = Number(earthworkRepresentative.representative_baseline_quantity ?? earthworkRepresentative.baseline_quantity);
      const changed = Number(earthworkRepresentative.representative_changed_quantity ?? earthworkRepresentative.changed_quantity);
      const difference = Number.isFinite(baseline) && Number.isFinite(changed) ? changed - baseline : undefined;
      return {
        ...earthworkRepresentative,
        baseline_quantity: earthworkRepresentative.representative_baseline_quantity ?? earthworkRepresentative.baseline_quantity,
        changed_quantity: earthworkRepresentative.representative_changed_quantity ?? earthworkRepresentative.changed_quantity,
        difference: difference === undefined ? earthworkRepresentative.difference : String(Number(difference.toFixed(3))),
        difference_rate: Number.isFinite(baseline) && baseline !== 0 && difference !== undefined ? `${((difference / baseline) * 100).toFixed(2)}%` : earthworkRepresentative.difference_rate,
        source_rows: earthworkRepresentative.representative_source_rows?.length ? earthworkRepresentative.representative_source_rows : earthworkRepresentative.source_rows,
      };
    }
  }
  if (packages.includes("타일공사")) {
    const tileRepresentative = comparisons.find(item => item.work_package === "타일공사" && item.item_text === "데코타일붙임" && item.result.includes("변경 후"));
    if (tileRepresentative) return tileRepresentative;
  }
  return comparisons
    .filter(item => packages.includes(item.work_package) && item.result.includes("변경 후"))
    .sort((left, right) => {
      const leftScore = textMatchScore(candidate.candidate_text, left.item_text);
      const rightScore = textMatchScore(candidate.candidate_text, right.item_text);
      if (leftScore !== rightScore) return rightScore - leftScore;
      const leftDifference = Math.abs(Number(left.difference || 0));
      const rightDifference = Math.abs(Number(right.difference || 0));
      return rightDifference - leftDifference;
    })[0];
}

function summaryPriority(workPackage?: string) {
  const value = workPackage || "";
  if (value.includes("조적")) return 0;
  if (value.includes("방수")) return 1;
  if (value.includes("철골")) return 2;
  if (value.includes("철근콘크리트")) return 3;
  if (value.includes("타일")) return 4;
  return 10;
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

function SourcePdfPreview({ url, pageNumber, changed, exactPage, highlightRegions = [] }: { url: string | null; pageNumber?: number; changed: boolean; exactPage?: boolean; highlightRegions?: HighlightRegion[] }) {
  if (!url) return <div className={`cad-pdf-loading ${changed ? "changed" : "baseline"}`}><b>등록된 PDF 원본을 찾지 못했습니다</b><small>합성 도면으로 대체하지 않습니다. 원본 자료 화면에서 파일 연결을 확인하세요.</small></div>;
  return <div className="cad-pdf-preview"><div className="cad-pdf-figure">{exactPage ? <div className="cad-pdf-canvas"><img src={url} alt={`${changed ? "변경" : "기준"} PDF 페이지 미리보기`} />{changed && highlightRegions.length > 0 && <div className="cad-pdf-highlights" aria-label="전처리 변경 구간 음영 표시">{highlightRegions.map(region => <span key={`${region.left}-${region.top}`} className="cad-pdf-highlight masonry" style={{ left: region.left, top: region.top, width: region.width, height: region.height }}>{region.label && <b>{region.label}</b>}</span>)}</div>}</div> : <iframe src={`${url}#page=${pageNumber || 1}&view=FitH`} title={changed ? "변경 원본 PDF" : "기준 원본 PDF"} />}{changed && exactPage && highlightRegions.length > 0 && <strong className="cad-pdf-highlight-legend masonry">파란 음영 · 대표 조적 변경 구간</strong>}</div><small>등록 원본 PDF · {exactPage ? "정확한 층별 시트 연결" : "페이지 자동 매칭 전 1페이지"}{changed && exactPage && highlightRegions.length > 0 ? " · 대표 변경 구간 표시" : ""}</small></div>;
}

function PdfLoadingPreview({ changed }: { changed: boolean }) {
  return <div className={`cad-pdf-loading ${changed ? "changed" : "baseline"}`}>
    <b>{changed ? "변경" : "기준"} PDF 원본을 불러오는 중입니다</b>
    <small>CAD 도식으로 대체하지 않고, 등록된 PDF 원본을 그대로 표시합니다.</small>
  </div>;
}

function DrawingFocusPreview({ candidate, changed }: { candidate: DrawingCandidate; changed: boolean }) {
  const sheet = candidate.drawing_number || candidate.sheet_number || "도면번호 확인 필요";
  return <div className={`drawing-focus-preview ${changed ? "changed" : "baseline"}`}>
    <div className="drawing-focus-sheet"><span>{sheet}</span><small>{changed ? candidate.changed_revision || "변경 Rev. 확인 필요" : candidate.baseline_revision || "기준 Rev. 확인 필요"}</small></div>
    <div className="drawing-focus-grid" aria-label={changed ? "변경 도면 표기 요약" : "기준 도면 표기 요약"}>
      <span className="drawing-focus-title">{changed ? "변경 표기" : "기준 도면"}</span>
      {changed ? <div className="drawing-focus-marker"><b>{candidate.change_type || "변경 후보"}</b><strong>{candidate.candidate_text || "변경 표기 확인 필요"}</strong><small>{candidate.location_ref || "DWG 좌표 근거 확인 필요"}</small></div> : <div className="drawing-focus-reference"><b>기준 시트 참조</b><span>동일 시트 PDF가 없어 실제 도면 대신 시트·Rev. 기준만 표시합니다.</span></div>}
    </div>
    <small className="drawing-focus-footer">{changed ? "DWG 텍스트·좌표 전처리 결과" : "DWG 기준 원본"}</small>
  </div>;
}

export default function DrawingsPage() {
  const router = useRouter();
  const [items, setItems] = useState<DrawingCandidate[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dataScope, setDataScope] = useState<DataScope>("전체");
  const [workPackage, setWorkPackage] = useState("전체");
  const [textRole, setTextRole] = useState("전체");
  const [locationStatus, setLocationStatus] = useState("전체");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [baselinePdfUrl, setBaselinePdfUrl] = useState<string | null>(null);
  const [changedPdfUrl, setChangedPdfUrl] = useState<string | null>(null);
  const [comparisons, setComparisons] = useState<BaselineChangedComparison[]>([]);
  const [comparisonLoading, setComparisonLoading] = useState(true);
  const [showCandidateList, setShowCandidateList] = useState(false);
  const [catalogHydrating, setCatalogHydrating] = useState(false);
  // 도면 검토의 기준은 CAD 렌더링이 아니라 등록된 PDF 원본이다.
  // 조적공사처럼 PDF로 검토했던 공종이 DWG 텍스트 요약으로 바뀌지 않도록
  // 모든 후보에서 PDF를 기본으로 연다.
  const [showPdf, setShowPdf] = useState(true);
  const [masonryFloor, setMasonryFloor] = useState<1 | 2>(1);

  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const requestedScope = query.get("dataScope");
    if (requestedScope && DATA_SCOPE_OPTIONS.includes(requestedScope as DataScope)) setDataScope(requestedScope as DataScope);
    const requestedWorkPackageRaw = query.get("workPackage");
    let requestedWorkPackage = requestedWorkPackageRaw || "";
    try { requestedWorkPackage = requestedWorkPackageRaw ? decodeURIComponent(requestedWorkPackageRaw) : ""; } catch { /* malformed query는 기본 전체로 유지 */ }
    if (requestedWorkPackage && (requestedWorkPackage === "전체" || CANONICAL_DRAWING_PACKAGES.includes(requestedWorkPackage as typeof CANONICAL_DRAWING_PACKAGES[number]))) setWorkPackage(requestedWorkPackage);
    let active = true;
    // Render a small representative slice first, then hydrate the full
    // catalogue in the background. Filters remain available immediately and
    // are replaced with the complete 1,500-row window when it arrives.
    setCatalogHydrating(true);
    fetchDrawings(PROJECT_ID, 300).then(initialItems => {
      if (!active) return;
      setItems(initialItems);
      setLoading(false);
      return fetchDrawings(PROJECT_ID, 1500).then(fullItems => {
        if (active) {
          setItems(fullItems);
          setCatalogHydrating(false);
        }
      });
    }).catch(() => {
      if (active) {
        setNotice("도면 변경 후보를 불러오지 못했습니다. API 연결과 권한을 확인하세요.");
        setCatalogHydrating(false);
      }
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    // The response always contains the full baseline/changed comparison
    // summary. Avoid passing a source-set filter here so this request shares
    // the warmed quantity-analysis cache with the quantities screen instead
    // of triggering a second full preprocessing pass.
    const params = new URLSearchParams({ limit: "1" });
    fetchQuantityAnalysis(PROJECT_ID, params.toString()).then(result => setComparisons(result.baseline_changed_comparison || [])).catch(() => setNotice(previous => previous || "공종별 물량 변화 요약을 불러오지 못했습니다. 수량·산식·내역 화면에서 원천값을 확인하세요.")).finally(() => setComparisonLoading(false));
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

  const scaffoldReview = scaffoldSummary(comparisons);
  const panelReview = panelRepresentative(comparisons);
  const gutterReview = gutterRepresentative(comparisons);
  const elevatorReview = elevatorRepresentative(comparisons);
  // 도면 후보가 없어도 내역 비교에 대표 규칙이 있으면 공종 필터를
  // 노출한다. 창호공사처럼 도면 원천은 비어 있지만 사무동 전체 문
  // 수량 요약이 가능한 공종을 필터에서 누락하지 않기 위한 조건이다.
  const workPackages = ["전체", ...CANONICAL_DRAWING_PACKAGES.filter(packageName => items.some(item => canonicalWorkPackages(item.work_package).includes(packageName)) || comparisons.some(item => item.work_package === packageName) || (packageName === "가설공사" && Boolean(scaffoldReview)) || (packageName === "패널공사" && Boolean(panelReview)) || (packageName === "홈통공사" && Boolean(gutterReview)) || (packageName === "승강기공사" && Boolean(elevatorReview))), "기타·원천 확인 필요"];
  const textRoleOptions = ["전체", ...Array.from(new Set(items.map(item => item.text_role || "부위 미확정").filter(Boolean))).sort()];
  const filteredItems = items.filter(item => {
    const packages = canonicalWorkPackages(item.work_package);
    const packageMatches = workPackage === "전체" || (workPackage === "기타·원천 확인 필요" ? packages.length === 0 : (packages as readonly string[]).includes(workPackage));
    return (dataScope === "전체" || originFor(item) === dataScope) && packageMatches && (textRole === "전체" || (item.text_role || "부위 미확정") === textRole) && (locationStatus === "전체" || locationBucketFor(item) === locationStatus);
  });
  const renderedItems = filteredItems.slice(0, 60);
  const primaryCandidate = [...filteredItems].filter(item => item.work_package && !item.work_package.includes("미분류")).sort((left, right) => {
    // 공종 필터가 지정되면 복합 공종 후보보다 해당 공종 단독 후보를
    // 우선한다. 그래야 방수 화면에 조적 대표 내역이 섞이지 않는다.
    if (workPackage !== "전체") {
      const leftExact = left.work_package?.trim() === workPackage ? 0 : 1;
      const rightExact = right.work_package?.trim() === workPackage ? 0 : 1;
      if (leftExact !== rightExact) return leftExact - rightExact;
    }
    if (workPackage === "유리공사") {
      const leftGlassPriority = glassDrawingPriority(left);
      const rightGlassPriority = glassDrawingPriority(right);
      if (leftGlassPriority !== rightGlassPriority) return leftGlassPriority - rightGlassPriority;
    }
    if (workPackage === "석공사") {
      const leftStonePriority = stoneDrawingPriority(left);
      const rightStonePriority = stoneDrawingPriority(right);
      if (leftStonePriority !== rightStonePriority) return leftStonePriority - rightStonePriority;
    }
    if (workPackage === "단열공사") {
      const leftInsulationPriority = insulationDrawingPriority(left);
      const rightInsulationPriority = insulationDrawingPriority(right);
      if (leftInsulationPriority !== rightInsulationPriority) return leftInsulationPriority - rightInsulationPriority;
    }
    const workPackagePriority = summaryPriority(left.work_package) - summaryPriority(right.work_package);
    if (workPackagePriority) return workPackagePriority;
    const leftComparison = representativeComparison(left, comparisons);
    const rightComparison = representativeComparison(right, comparisons);
    const leftRelated = textMatchScore(left.candidate_text, leftComparison?.item_text);
    const rightRelated = textMatchScore(right.candidate_text, rightComparison?.item_text);
    if (leftRelated !== rightRelated) return rightRelated - leftRelated;
    const leftPriority = left.text_role === "부위 표기" ? 0 : 1;
    const rightPriority = right.text_role === "부위 표기" ? 0 : 1;
    return leftPriority - rightPriority;
  })[0] || filteredItems[0];
  const selected = filteredItems.find(item => item.id === selectedId) || primaryCandidate;
  const doorSummary = workPackage === "창호공사" ? officeDoorComparison(comparisons) : undefined;
  const activeScaffoldSummary = workPackage === "가설공사" ? scaffoldReview : undefined;
  const activePanelSummary = workPackage === "패널공사" ? panelReview : undefined;
  const activeGutterSummary = workPackage === "홈통공사" ? gutterReview : undefined;
  const activeElevatorSummary = workPackage === "승강기공사" ? elevatorReview : undefined;
  let summaryCandidate = selected || (doorSummary ? {
    id: "SUMMARY-OFFICE-DOORS",
    project_id: PROJECT_ID,
    discipline: "건축",
    work_package: "창호공사",
    drawing_number: "사무동 전체",
    candidate_text: "사무동 전체 문 수량",
    change_type: "전체 수량 비교",
    status: "대표 수량 요약",
    confidence: "중간",
  } as DrawingCandidate : activeScaffoldSummary ? {
    id: "SUMMARY-SCAFFOLD-EXPANSION",
    project_id: PROJECT_ID,
    discipline: "건축",
    work_package: "가설공사",
    drawing_number: "4층→5층 증축",
    candidate_text: "현장정리·구조부 먹매김 병렬 비교",
    change_type: "증축 면적 요약",
    status: "대표 수량 요약",
    confidence: "중간",
  } as DrawingCandidate : activePanelSummary ? {
    id: "SUMMARY-PANEL-EXTERIOR-100T",
    project_id: PROJECT_ID,
    discipline: "건축",
    work_package: "패널공사",
    drawing_number: "외벽 100T 대표 물량",
    candidate_text: "메탈패널 설치 · 외벽 100T (재료비 행 교차 확인)",
    change_type: "대표 면적 비교",
    status: "대표 수량 요약",
    confidence: "중간",
  } as DrawingCandidate : activeGutterSummary ? {
    id: "SUMMARY-GUTTER-ROOF-DRAIN-D150",
    project_id: PROJECT_ID,
    discipline: "건축",
    work_package: "홈통공사",
    drawing_number: "루프드레인 L형 D150 대표 물량",
    candidate_text: "루프드레인 설치 · L형 D150 (코킹 포함)",
    change_type: "대표 EA 비교",
    status: "대표 수량 요약",
    confidence: "중간",
  } as DrawingCandidate : activeElevatorSummary ? {
    id: "SUMMARY-ELEVATOR-SPEC-4TO5STOP",
    project_id: PROJECT_ID,
    discipline: "건축",
    work_package: "승강기공사",
    drawing_number: "승강기 사양 변경",
    candidate_text: "승객용 엘리베이터 · 24인승 4STOP → 5STOP",
    change_type: "사양 전환",
    status: "대표 수량 요약",
    confidence: "중간",
  } as DrawingCandidate : undefined);
  const selectedComparison = selected ? representativeComparison(selected, comparisons) : (doorSummary || activeScaffoldSummary || activePanelSummary || activeGutterSummary || activeElevatorSummary);
  if (summaryCandidate && selectedComparison?.item_key === "승객용엘리베이터사양변경") {
    // 실제 PDF 후보가 있더라도 대표 카드는 삭제 후보가 아닌 사양 전환을
    // 우선 설명하도록 표시 문구를 대표 수량 기준으로 보정한다.
    summaryCandidate = { ...summaryCandidate, change_type: "사양 전환", candidate_text: "승객용 엘리베이터 · 24인승 4STOP → 5STOP" };
  }
  // 대표 1:1 수량은 공종 대표 변화 요약이다. 후보 텍스트의 "페인트"처럼
  // 일반 단어만 겹친 경우를 도면-내역 직접 연결로 오인하지 않는다.
  const selectedItemRelated = Boolean(selectedComparison && selected && !selectedComparison.representative_source_rows?.length && textMatchScore(selected.candidate_text, selectedComparison.item_text) >= 3);
  const masonryPlan = Boolean(selected?.discipline === "건축" && (workPackage === "전체" || workPackage === "조적공사") && selected?.work_package?.includes("조적"));
  const pdfBundle = masonryPlan ? "masonry-plan" : "main";
  const masonryFloorPages = masonryPlan && selected
    ? { baseline: selected.baseline_floor_pages?.[masonryFloor - 1], changed: selected.changed_floor_pages?.[masonryFloor - 1] }
    : { baseline: undefined, changed: undefined };
  const baselinePdfPage = masonryFloorPages.baseline || selected?.baseline_page_number || selected?.page_number;
  const changedPdfPage = masonryFloorPages.changed || selected?.changed_page_number || selected?.page_number;
  const baselinePreviewUrl = selected?.id && baselinePdfPage ? drawingPdfPreviewUrl(PROJECT_ID, selected.id, "baseline", baselinePdfPage, pdfBundle) : baselinePdfUrl;
  const changedPreviewUrl = selected?.id && changedPdfPage ? drawingPdfPreviewUrl(PROJECT_ID, selected.id, "changed", changedPdfPage, pdfBundle) : changedPdfUrl;
  const canComparePdfPages = Boolean((baselinePdfPage || showPdf) && baselinePreviewUrl && changedPreviewUrl);
  const pdfExactPage = Boolean(masonryPlan || selected?.page_number);
  // 음영 좌표는 화면에서 추정하지 않고 전처리 응답에 저장된 PDF 기준
  // 좌표만 사용한다. 층이 일치하지 않는 좌표는 버려서 다른 층의 위치가
  // 재사용되지 않도록 한다.
  const pdfHighlightRegions: HighlightRegion[] = masonryPlan
    ? (selected?.pdf_highlight_regions || [])
        .filter(region => region.floor == null || region.floor === masonryFloor)
        .map(region => ({
          left: region.left,
          top: region.top,
          width: region.width,
          height: region.height,
          label: region.label || "변경 구간",
        }))
    : [];
  const masonryLocationMessage = masonryFloor === 1
    ? "1층은 121·122실 주변 조적 변경 구간을 파란 음영으로 표시합니다."
    : "2층은 현재 확인된 대표 변경 구간이 없어 음영을 표시하지 않습니다.";
  const displayDrawingNumber = masonryPlan ? `DWG-${masonryFloor === 1 ? "201" : "202"} · ${masonryFloor}층 평면도` : (selected?.drawing_number || selected?.sheet_number || "도면번호 미지정");
  const pdfPageStatus = selected?.pdf_page_status
    ?.replace("감사 완료", "표시")
    ?.replace("페이지 근거 확인 필요", "PDF 원본 표시") || "PDF 원본 표시";

  useEffect(() => {
    let active = true;
    const urls: string[] = [];
    setBaselinePdfUrl(null);
    setChangedPdfUrl(null);
    async function loadPdf(side: "baseline" | "changed", setter: (url: string | null) => void) {
      // 후보의 좌표·텍스트는 보조 근거일 뿐, 화면의 기준은 PDF 원본이다.
      // 페이지 번호가 없는 기존 후보도 PDF 원본을 기본으로 열어 사용자가
      // CAD 도식이 아닌 실제 도면을 확인할 수 있게 한다.
      if (!selected?.id || selected.page_number || !showPdf) return;
      try {
        const url = URL.createObjectURL(await fetchDrawingPdf(PROJECT_ID, selected.id, side));
        urls.push(url);
        if (active) setter(url);
      } catch {
        // Existing DXF catalogue candidates retain their sheet/coordinate
        // evidence. They are never misrepresented as a PDF preview.
      }
    }
    void loadPdf("baseline", setBaselinePdfUrl);
    void loadPdf("changed", setChangedPdfUrl);
    return () => { active = false; urls.forEach(url => URL.revokeObjectURL(url)); };
  }, [selected?.id, selected?.page_number, showPdf]);

  useEffect(() => {
    setShowPdf(true);
    setMasonryFloor(1);
  }, [selected?.id]);

  return <AppShell eyebrow="DRAWING CHANGE REVIEW" title="도면 변경부위 검토">
    <div className="drawing-scope-bar"><span>프로젝트 <strong>광양5 사무동</strong></span><span>도면 후보 <strong>{loading ? "—" : `${filteredItems.length}건`}</strong></span><span>표시 기준 <strong>변경 구간·대표 물량·PDF 원본</strong></span><label>공사단위<select value={workPackage} onChange={event => { setWorkPackage(event.target.value); setSelectedId(null); }}>{workPackages.map(option => <option key={option}>{option}</option>)}</select></label><label>텍스트 역할<select value={textRole} onChange={event => { setTextRole(event.target.value); setSelectedId(null); }}>{textRoleOptions.map(option => <option key={option}>{option}</option>)}</select></label><label>위치 상태<select value={locationStatus} onChange={event => { setLocationStatus(event.target.value); setSelectedId(null); }}>{["전체", "자동 위치 후보 가능", "위치 후보", "부위 미확정"].map(option => <option key={option}>{option}</option>)}</select></label><label>자료 범위<select value={dataScope} onChange={event => handleDataScopeChange(event.target.value as DataScope)}>{DATA_SCOPE_OPTIONS.map(option => <option key={option}>{option}</option>)}</select></label><span className="cad-state">{catalogHydrating ? "전체 후보 동기화 중…" : "변경 정보 중심"}</span></div>
    <WorkflowStepper current="change" />
    <p className="lead">기준·변경 PDF를 나란히 보고, 전처리된 변경 표기와 대표 물량 변화를 함께 확인합니다. 이 화면은 승인 판정이 아니라 공종별 변경 내용을 빠르게 파악하기 위한 검토 지원 화면입니다.</p>
    <div className="cad-location-guide"><span><b>자동 위치 후보 가능</b> 좌표 정렬이 가능한 후보</span><span><b>위치 후보</b> 시트·좌표는 있으나 범위 차이로 추가 확인 필요</span><span><b>부위 미확정</b> 텍스트만 있고 위치를 확정하지 않음</span></div>
    {!loading && <section className="panel drawing-change-summary"><div className="panel-head"><div><p className="eyebrow">TRADE CHANGE SUMMARY</p><h2>{workPackage === "전체" ? "대표 변경 1건" : `${workPackage} 대표 변경`}</h2><small className="muted-line">공사단위를 선택하면 해당 공종의 대표 내역 1건만 표시합니다. 먼저 변경 구간과 기준·변경 물량을 확인하고, PDF는 해당 내용을 이해하기 위한 화면 자료로 활용합니다.</small></div><span className="review-only">검토 지원</span></div><div className="drawing-review-status"><span className="drawing-status-ok"><b>검토 정보</b> 대표 내역·변경 구간·기준/변경 수량</span><span className="drawing-status-pending"><b>참고</b> 도면 표기와 물량을 함께 보고 판단</span></div>{comparisonLoading ? <p className="muted-line">대표 물량 변화를 불러오는 중입니다…</p> : summaryCandidate && selectedComparison ? <div className="drawing-change-summary-single"><div><span className="drawing-change-card-trade">{displayWorkPackage(summaryCandidate.work_package)}</span><strong>{selectedComparison.item_text}</strong><span className="drawing-change-location">{drawingReferenceLabel(summaryCandidate, workPackage === "전체" ? displayWorkPackage(summaryCandidate.work_package) : workPackage)} · {summaryCandidate.change_type || "변경 후보"} · {candidateTextForTrade(summaryCandidate, workPackage === "전체" ? displayWorkPackage(summaryCandidate.work_package) : workPackage)}</span></div><div className="drawing-change-values"><span><small>기준 내역서</small><b>{quantityText(selectedComparison.baseline_quantity)}</b></span><span><small>변경 내역서</small><b>{quantityText(selectedComparison.changed_quantity)}</b></span><span><small>수량 차이</small><b className={Number(selectedComparison.difference || 0) < 0 ? "decrease" : "increase"}>{selectedComparison.difference !== undefined && selectedComparison.difference !== null && selectedComparison.difference !== "" ? `${Number(selectedComparison.difference) > 0 ? "+" : ""}${quantityText(selectedComparison.difference)}` : "—"}</b></span></div><em>{selectedComparison.result} · {selectedItemRelated ? "도면 표기와 연관" : "공종 대표 물량"}</em><button type="button" className="button-secondary" onClick={() => router.push(withDataScope(`/quantities?sourceSet=기준·변경 대조&workPackage=${encodeURIComponent(displayWorkPackage(summaryCandidate.work_package))}`))}>기준·변경 수량 대조</button></div> : <p className="muted-line">현재 필터 범위에서 공종 대표 물량을 찾지 못했습니다. 공사단위 필터를 선택하거나 내역·수량 화면에서 원천값을 확인하세요.</p>}</section>}
    {notice && <PageMessage tone="warning">{notice}</PageMessage>}
    {loading ? <section className="panel cad-loading">도면 변경 후보를 불러오는 중입니다…</section> : !selected ? <section className="panel empty">현재 범위에 도면 변경 후보가 없습니다.</section> : <section className="cad-workspace">
      <div className="cad-main panel">
         <div className="panel-head"><div><p className="eyebrow">PDF DRAWING REVIEW</p><h2>{displayDrawingNumber}</h2><small className="muted-line">{selected.discipline || "공종 미지정"} · {masonryPlan ? "조적 대표 내역은 별도 수량 근거 · 위치는 층별 평면도에서 확인" : (selected.location_ref || "위치 확인 필요")}</small><small className="muted-line">PDF 원본 우선 · {pdfPageStatus} · 텍스트·좌표는 변경 표기 탐색을 위한 보조 근거입니다.</small></div><CandidateBadge status={selected.status} confidence={selected.confidence} /></div>
        <div className="cad-revision-labels"><span><b>기준 도면</b>{selected.baseline_revision || "Rev. 확인 필요"}</span><span><b>변경 도면</b>{selected.changed_revision || "Rev. 확인 필요"}</span></div>
         {masonryPlan && selected.baseline_floor_pages?.length === 2 && selected.changed_floor_pages?.length === 2 && <div className="masonry-floor-tabs" role="tablist" aria-label="조적공사 PDF 층별 근거"><span>조적 PDF 근거</span>{([1, 2] as const).map(floor => <button key={floor} type="button" role="tab" aria-selected={masonryFloor === floor} className={masonryFloor === floor ? "active" : ""} onClick={() => setMasonryFloor(floor)}>{floor}층 평면도</button>)}<small>기준·변경의 <b>동일 층 평면도</b>를 비교합니다. {masonryLocationMessage}</small></div>}
         <div className="cad-viewports"><div className="cad-viewport"><div className="cad-viewport-header">기준 · {selected.baseline_revision || "UNKNOWN"}<span>{shortFileName(selected.baseline_file)}</span><small>{pdfPageRef(baselinePdfPage)}</small></div>{canComparePdfPages ? <SourcePdfPreview url={baselinePreviewUrl} pageNumber={baselinePdfPage} changed={false} exactPage={pdfExactPage} /> : <PdfLoadingPreview changed={false} />}</div><div className="cad-divider" aria-hidden="true" /><div className="cad-viewport changed"><div className="cad-viewport-header">변경 · {selected.changed_revision || "UNKNOWN"}<span>{shortFileName(selected.changed_file)}</span><small>{pdfPageRef(changedPdfPage)}</small></div>{canComparePdfPages ? <SourcePdfPreview url={changedPreviewUrl} pageNumber={changedPdfPage} changed exactPage={pdfExactPage} highlightRegions={pdfHighlightRegions} /> : <PdfLoadingPreview changed />}</div></div>
         <div className="cad-footer"><span>{canComparePdfPages ? (pdfExactPage ? `기준 ${pdfPageRef(baselinePdfPage)} · 변경 ${pdfPageRef(changedPdfPage)} 실제 PDF 페이지를 표시합니다.` : "기준·변경 PDF 원본을 표시합니다. 현재 후보에는 페이지 연결값이 없어 1페이지부터 열립니다.") : "등록된 기준·변경 PDF 원본을 불러오는 중입니다. PDF가 없을 때만 원본 자료 화면에서 확인합니다."}</span><div className="cad-footer-actions"><button type="button" className="button-secondary" onClick={() => router.push("/upload")}>원본 자료 화면 열기</button></div></div>
      </div>
      <aside className="cad-inspector panel"><div className="panel-head"><div><p className="eyebrow">CHANGE CANDIDATE</p><h2>변경 후보 상세</h2></div><span className="review-only">검토 지원</span></div><div className="cad-alert"><strong>{candidateTextForTrade(selected, workPackage === "전체" ? displayWorkPackage(selected.work_package) : workPackage)}</strong><p>도면 표기와 내역 연결은 참고용이며, 이 화면에서는 변경 구간과 물량 변화를 먼저 확인합니다.</p></div><dl className="cad-facts">{masonryPlan ? <><div><dt>공사단위</dt><dd>조적공사</dd></div><div><dt>비교 도면</dt><dd>DWG-{masonryFloor === 1 ? "201" : "202"} · {masonryFloor}층 평면도</dd></div><div><dt>대표 내역 근거</dt><dd>DWG-111 마감재료표 · 시멘트 벽돌</dd></div><div><dt>위치 상태</dt><dd>{masonryFloor === 1 ? "1층 대표 변경 구간 표시" : "2층 대표 변경 구간 없음"}</dd></div><div><dt>PDF 비교</dt><dd>기준 {pdfPageRef(baselinePdfPage)} ↔ 변경 {pdfPageRef(changedPdfPage)}</dd></div><div><dt>기준 Rev.</dt><dd>{selected.baseline_revision || "UNKNOWN"}</dd></div><div><dt>변경 Rev.</dt><dd>{selected.changed_revision || "UNKNOWN"}</dd></div><div><dt>원본 행</dt><dd>{selected.source_row_ref || "확인 필요"}</dd></div></> : <><div><dt>공사단위</dt><dd>{displayWorkPackage(selected.work_package)}</dd></div><div><dt>도면번호</dt><dd>{selected.drawing_number || "-"}</dd></div><div><dt>시트</dt><dd>{selected.sheet_number || "-"}</dd></div><div><dt>위치 근거</dt><dd>{selected.location_ref || "확인 필요"}</dd></div><div><dt>기준 Rev.</dt><dd>{selected.baseline_revision || "UNKNOWN"}</dd></div><div><dt>변경 Rev.</dt><dd>{selected.changed_revision || "UNKNOWN"}</dd></div><div><dt>원본 행</dt><dd>{selected.source_row_ref || "확인 필요"}</dd></div><div><dt>변경 유형</dt><dd>{selected.change_type || "-"}</dd></div></>}</dl><section className="cad-links"><h3>도면·내역 보조 정보</h3>{masonryPlan ? <><div>대표 내역 ↔ 위치 도면 <b>분리 표시</b></div><small>사용자가 확인한 대표 변경 구간을 층별로 표시합니다. DWG-111의 재료표 텍스트만으로 위치를 만들지 않습니다.</small></> : <><div>도면 표기 ↔ 변경 내역 <b>{selected.link_status || "연결 근거 없음"}</b></div><div>연결 후보 원천행 <b>{selected.linked_estimate_count ?? 0}건</b></div>{selected.linked_estimate_names?.length ? <small title={selected.linked_estimate_names.join(" · ")}>참고 내역 {selected.linked_estimate_names.join(" · ")}</small> : <small>같은 사무동 원천행이 없으면 공종 대표 물량으로 표시합니다.</small>}</>}<div>수량산출서 → 내역서 <b>별도 수량 검토</b></div></section><div className="cad-actions"><button type="button" onClick={() => router.push(withDataScope(`/quantities?sourceSet=변경자료${selected.work_package ? `&workPackage=${encodeURIComponent(displayWorkPackage(selected.work_package))}` : ""}`))}>변경 내역·수량 검토</button><button type="button" onClick={() => router.push("/approvals")}>근거 확인·승인 화면</button><button type="button" className="button-secondary" onClick={() => router.push("/approvals")}>추가자료 요청 화면</button></div></aside>
    </section>}
    {!loading && filteredItems.length > 1 && <section className="panel cad-candidate-list"><div className="panel-head"><div><p className="eyebrow">SOURCE CANDIDATES</p><h2>원천 후보 {filteredItems.length}건</h2></div><span className="muted-line">대표 변경 1건을 우선 확인하고, 필요한 경우에만 세부 후보를 펼칩니다.</span></div><p className="muted-line cad-candidate-note">반복되는 CAD 텍스트 행은 자동 확정 대상이 아닙니다. 공사단위·텍스트 역할·위치 상태 필터로 범위를 좁힌 뒤 세부 근거를 확인하세요.</p><button type="button" className="button-secondary cad-candidate-toggle" onClick={() => setShowCandidateList(value => !value)}>{showCandidateList ? "세부 후보 숨기기" : `세부 후보 펼치기 (최대 ${renderedItems.length}건)`}</button>{showCandidateList && <div className="candidate-list compact-list">{renderedItems.map(item => <button type="button" className={`cad-candidate-row ${item.id === selected?.id ? "selected" : ""}`} key={item.id} onClick={() => setSelectedId(item.id)}><span className={`severity ${item.status.includes("복수") || item.status.includes("없음") ? "중간" : "낮음"}`}>{item.status || "검토 대기"}</span><strong>{displayWorkPackage(item.work_package)} · {item.drawing_number || item.sheet_number || item.id}</strong><span>{item.location_ref || `${item.baseline_revision || "-"} → ${item.changed_revision || "-"}`}</span><small>{item.text_role || "부위 미확정"} · {item.candidate_text || "변경 설명 확인 필요"}</small></button>)}</div>}</section>}
  </AppShell>;
}
