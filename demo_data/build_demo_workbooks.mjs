import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = path.resolve("demo_data");
const font = "Arial";

const baselineEstimate = [
  ["품목코드", "품명", "규격", "단위", "수량", "단가", "금액", "동", "공종", "도면번호", "시트"],
  ["", "0301. 방수공사", "", "", null, null, null, "사무동", "방수공사", "", ""],
  ["EST-001", "콘크리트파일박기", "PHC 400", "m", 120, 45000, 5400000, "사무동", "토공사", "S-101", "구조"],
  ["EST-002", "무기질탄성도막방수(내부)", "2회 도포", "m²", 480, 18000, 8640000, "사무동", "방수공사", "A-201", "실내방수"],
  ["EST-003", "타일벽코너가드/아웃", "PVC 50x50", "개", 24, 12000, 288000, "사무동", "타일공사", "A-301", "타일"],
  ["EST-004", "철골보", "H-400x200", "TON", 12.5, 2200000, 27500000, "사무동", "철골공사", "S-201", "철골"],
  ["REF-001", "무기질탄성도막방수(내부)", "2회 도포", "m²", 60, 18000, 1080000, "보안동", "방수공사", "A-901", "참고"],
];

const baselineQuantity = [
  ["품명", "규격", "단위", "수량", "산식", "동", "공종", "층", "공간", "도면번호", "자재구분", "부재구분"],
  ["콘크리트파일박기", "PHC 400", "m", 120, "10*12", "사무동", "토공사", "기초", "기초구간", "S-101", "재료", "파일"],
  ["무기질탄성도막방수(내부)", "2회 도포", "m²", 480, "120*4", "사무동", "방수공사", "1F", "화장실", "A-201", "재료", "방수"],
  ["타일벽코너가드/아웃", "PVC 50x50", "개", 24, "12*2", "사무동", "타일공사", "1F", "복도", "A-301", "재료", "마감"],
  ["철골보", "H-400x200", "TON", 12.5, "5.0+7.5", "사무동", "철골공사", "2F", "대회의실", "S-201", "재료", "보"],
  ["보안동 방수 참고행", "2회 도포", "m²", 60, "6*10", "보안동", "방수공사", "1F", "창고", "A-901", "재료", "방수"],
  ["산식만 있고 원본수량 없음", "보강", "m", null, "3*4", "사무동", "방수공사", "1F", "기계실", "A-202", "시공", "보강"],
];

const changedEstimate = [
  ["품목코드", "품명", "규격", "단위", "수량", "단가", "금액", "동", "공종", "도면번호", "시트"],
  ["", "0301. 방수공사", "", "", null, null, null, "사무동", "방수공사", "", ""],
  ["EST-001", "콘크리트파일박기", "PHC 400", "m", 120, 45000, 5400000, "사무동", "토공사", "S-101", "구조"],
  ["EST-002", "무기질탄성도막방수(내부)", "2회 도포", "m²", 520, 18000, 9360000, "사무동", "방수공사", "A-201", "실내방수"],
  ["EST-003", "타일벽코너가드/아웃", "PVC 50x50", "개", 24, 12000, 288000, "사무동", "타일공사", "A-301", "타일"],
  ["EST-004", "철골보", "H-400x200", "TON", 7.0, 2200000, 15400000, "사무동", "철골공사", "S-201", "철골"],
  ["EST-004-B", "철골보", "H-400x200", "TON", 5.6, 2200000, 12320000, "사무동", "철골공사", "S-201", "철골"],
  ["EST-005", "흡음패널", "PET 25T", "m²", 45, 0, 0, "사무동", "인테리어공사", "A-401", "신규마감"],
  ["EST-006", "기존 보온재 철거", "배관 보온", "m", 0, 0, 0, "사무동", "철거공사", "M-101", "삭제후보"],
  ["REF-002", "무기질탄성도막방수(내부)", "2회 도포", "m²", 77, 18000, 1386000, "보안동", "방수공사", "A-901", "참고"],
];

const changedQuantity = [
  ["품명", "규격", "단위", "수량", "산식", "동", "공종", "층", "공간", "도면번호", "자재구분", "부재구분"],
  ["콘크리트파일박기", "PHC 400", "m", 120, "10*12", "사무동", "토공사", "기초", "기초구간", "S-101", "재료", "파일"],
  ["무기질탄성도막방수(내부)", "2회 도포", "m²", 500, "125*4", "사무동", "방수공사", "1F", "화장실", "A-201", "재료", "방수"],
  ["타일벽코너가드/아웃", "PVC 50x50", "개", 24, "12*2", "사무동", "타일공사", "1F", "복도", "A-301", "재료", "마감"],
  ["철골보", "H-400x200", "TON", 7.1, "3.0+4.1", "사무동", "철골공사", "2F", "대회의실", "S-201", "재료", "보"],
  ["철골보", "H-400x200", "TON", 5.5, "2.5+3.0", "사무동", "철골공사", "2F", "대회의실", "S-201", "재료", "보"],
  ["흡음패널", "PET 25T", "m²", 45, "9*5", "사무동", "인테리어공사", "1F", "회의실", "A-401", "재료", "신규마감"],
  ["기존 보온재 철거", "배관 보온", "m", 0, "0", "사무동", "철거공사", "1F", "기계실", "M-101", "시공", "삭제후보"],
  ["산식만 있고 원본수량 없음", "보강", "m", null, "3*4", "사무동", "방수공사", "1F", "기계실", "A-202", "시공", "보강"],
];

function styleSheet(sheet, rowCount, colCount) {
  sheet.showGridLines = false;
  const endCol = String.fromCharCode(64 + colCount);
  const used = sheet.getRange(`A1:${endCol}${rowCount}`);
  used.format.font = { name: font, size: 10, color: "#172B4D" };
  used.format.verticalAlignment = "center";
  sheet.getRange(`A1:${endCol}1`).format = {
    fill: "#12304A",
    font: { name: font, size: 10, bold: true, color: "#FFFFFF" },
    verticalAlignment: "center",
  };
  used.format.borders = { preset: "insideHorizontal", style: "thin", color: "#D8E1EA" };
  sheet.getRange(`A1:${endCol}${rowCount}`).format.autofitColumns();
  sheet.getRange(`A1:${endCol}${rowCount}`).format.autofitRows();
  sheet.getRange(`A1:${endCol}1`).format.rowHeight = 24;
  sheet.freezePanes.freezeRows(1);
  const notes = sheet.getRange(`A${rowCount + 2}`);
  notes.values = [["데모 자료 · 광양5 사무동 전처리 테스트용 · 승인 전 후보값" ]];
  notes.format.font = { name: font, size: 9, italic: true, color: "#637083" };
}

async function writeWorkbook(filename, sheetName, rows) {
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add(sheetName);
  sheet.getRangeByIndexes(0, 0, rows.length, rows[0].length).values = rows;
  styleSheet(sheet, rows.length, rows[0].length);
  workbook.recalculate();
  const inspection = await workbook.inspect({ kind: "table", sheetId: sheetName, range: `A1:${String.fromCharCode(64 + rows[0].length)}${Math.min(rows.length, 8)}`, include: "values", tableMaxRows: 8, tableMaxCols: rows[0].length, maxChars: 5000 });
  if (!inspection?.ndjson) throw new Error(`검사 실패: ${filename}`);
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(path.join(outputDir, filename));
}

await fs.mkdir(outputDir, { recursive: true });
await writeWorkbook("demo_office_baseline_estimate.xlsx", "내역서_기준", baselineEstimate);
await writeWorkbook("demo_office_baseline_quantity.xlsx", "수량산출서_기준", baselineQuantity);
await writeWorkbook("demo_office_changed_estimate.xlsx", "내역서_변경", changedEstimate);
await writeWorkbook("demo_office_changed_quantity.xlsx", "수량산출서_변경", changedQuantity);
console.log("demo workbooks created");
