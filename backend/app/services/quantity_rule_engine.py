"""내역서 기준 수량 검토의 공통 규칙 엔진.

이 모듈은 DB나 파일을 읽지 않는 순수 규칙만 소유한다. 기준자료·변경자료,
기존 전처리 결과·신규 업로드가 같은 판정 기준을 사용하도록 하기 위한 경계다.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QuantityComparison:
    issue_type: str
    judgement: str
    severity: str
    required_action: str
    difference: float | None
    difference_rate: float | None
    tolerance: float | None


@dataclass(frozen=True)
class RelationComparison:
    """Result of comparing two semantically related quantity totals."""

    result: str
    difference: float | None
    tolerance: float | None
    difference_rate: float | None


@dataclass(frozen=True)
class VersionComparison:
    """Baseline↔changed quantity delta for one estimate-key group."""

    result: str
    difference: float | None
    difference_rate: float | None
    tolerance: float | None


def clean_text(value: object) -> str:
    """Normalize harmless whitespace/case differences for field comparison."""
    return " ".join(str(value or "").strip().lower().split())


def spec_compatible(left: object, right: object) -> bool:
    """Compare specifications independent of punctuation and token ordering."""
    left_text, right_text = clean_text(left), clean_text(right)
    if not left_text or not right_text or left_text == right_text:
        return True
    token = lambda value: set(re.findall(r"[0-9a-z가-힣φø]+", value))
    left_tokens, right_tokens = token(left_text), token(right_text)
    return bool(left_tokens and right_tokens and (left_tokens <= right_tokens or right_tokens <= left_tokens))


def canonical_unit(value: object) -> str:
    """Keep harmless unit spellings from splitting one quantity group."""
    unit = clean_text(value).replace(" ", "")
    aliases = {
        "㎡": "m2", "m²": "m2", "m2": "m2",
        "㎥": "m3", "m³": "m3", "m3": "m3",
        "㎜": "mm", "mm": "mm",
        "ton": "ton", "톤": "ton", "t": "ton",
        "ea": "ea", "개소": "ea", "개": "ea",
    }
    return aliases.get(unit, unit)


def canonical_key(value: object) -> str:
    """Normalize a comparison key without replacing the displayed original."""
    return re.sub(r"[^0-9a-z가-힣φø]", "", clean_text(value))


def simple_formula_value(value: object) -> float | None:
    """Evaluate only literal arithmetic retained from a quantity sheet."""
    text = str(value or "").strip().replace("×", "*").replace("÷", "/")
    if text.startswith("="):
        text = text[1:]
    if not text or not re.fullmatch(r"[0-9.()+\-*/\s]+", text):
        return None
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        return None

    def evaluate(node) -> float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return evaluate(node.operand) if isinstance(node.op, ast.UAdd) else -evaluate(node.operand)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            return left / right
        raise ValueError("unsupported expression")

    try:
        result = evaluate(tree)
        return result if result == result and abs(result) != float("inf") else None
    except (ArithmeticError, ValueError):
        return None


def warning_threshold(total_amount: object) -> float:
    """PRD 금액 구간별 일반 수량 경고 기준."""
    try:
        amount = abs(float(total_amount))
    except (TypeError, ValueError):
        amount = 0
    if amount >= 100_000_000:
        return 0.01
    if amount >= 10_000_000:
        return 0.02
    return 0.03


def exact_tolerance(original: float) -> float:
    """원본 수량의 기술적 필드 일치 허용오차(0.01%)."""
    return max(0.0005, abs(original) * 0.0001)


def formula_rounding_tolerance(quantity: float) -> float:
    """수량산출서 소수 셋째 자리 표기 절사/반올림 허용오차."""
    return max(0.001, abs(quantity) * 0.0001)


def compare_related_totals(
    material_total: object,
    construction_total: object,
    tolerance_rate: float = 0.001,
) -> RelationComparison:
    """Compare material and construction totals only when both are present.

    This is intentionally separate from an item-level ``일치`` judgement:
    steel material and installation rows can have different names, but their
    total tonnage may be compared when the source explicitly labels both
    roles. Missing role totals remain a review state, never an inferred zero.
    """
    try:
        material = float(material_total) if material_total is not None else None
        construction = float(construction_total) if construction_total is not None else None
    except (TypeError, ValueError):
        material = construction = None
    if material is None or construction is None:
        if material is None and construction is None:
            result = "자재·시공 TON 연결 근거 없음"
        elif material is None:
            result = "자재 TON 연결 근거 없음"
        else:
            result = "시공 TON 연결 근거 없음"
        return RelationComparison(result, None, None, None)
    difference = construction - material
    tolerance = max(0.01, abs(material) * tolerance_rate)
    difference_rate = abs(difference / material) if material else None
    result = "총량 일치권" if abs(difference) <= tolerance else "총량 차이 확인 필요"
    return RelationComparison(result, difference, tolerance, difference_rate)


def classify_material_relation(*values: object) -> tuple[str, str] | None:
    """Return an explicit relation family and role, or ``None``.

    A role is emitted only when the source text contains a recognizable family
    and either an installation verb or a material marker. This prevents a
    generic item name from being treated as a confirmed material↔construction
    link.
    """
    text = clean_text(" ".join(str(value or "") for value in values))
    families = (
        ("앵커볼트", ("앵커볼트", "anchor bolt")),
        ("철골", ("철골", "h형강", "h형강", "강재", "steel")),
        ("방수", ("방수재", "우레탄", "도막방수", "방수")),
        ("타일", ("타일",)),
    )
    family = next((name for name, tokens in families if any(token in text for token in tokens)), None)
    if not family:
        return None
    construction_tokens = ("설치", "시공", "가공", "조립", "세우기", "용접", "붙임", "부착")
    material_tokens = ("자재", "재료", "제품", "물량", "수량")
    if any(token in text for token in construction_tokens):
        return family, "시공"
    if any(token in text for token in material_tokens):
        return family, "재료"
    return None


def compare_version_quantities(baseline: object, changed: object) -> VersionComparison:
    """Compare baseline and changed estimate quantities without approving them."""
    try:
        base = float(baseline) if baseline is not None else None
        after = float(changed) if changed is not None else None
    except (TypeError, ValueError):
        base = after = None
    if base is None or after is None:
        return VersionComparison("대조 근거 없음", None, None, None)
    difference = after - base
    tolerance = exact_tolerance(base)
    rate = abs(difference / base) if base else None
    if abs(difference) <= tolerance:
        result = "변경 없음(허용오차)"
    elif difference > 0:
        result = "변경 후 증가"
    else:
        result = "변경 후 감소"
    return VersionComparison(result, difference, rate, tolerance)


def compare_quantity(
    original: object,
    derived: object,
    mismatch_fields: list[str] | None = None,
    total_amount: object = None,
) -> QuantityComparison:
    """Compare one 내역서 row with its 산출서 group sum.

    ``일치``는 자동 승인이나 확정이 아니다. 단순 필드 일치와 금액 구간
    허용오차 내 근사 일치를 같은 결과 범주로 두되, judgement에 구분을 남긴다.
    """
    fields = list(dict.fromkeys(mismatch_fields or []))
    try:
        original_value = float(original) if original is not None else None
        derived_value = float(derived) if derived is not None else None
    except (TypeError, ValueError):
        original_value = derived_value = None
    if original_value is None or derived_value is None:
        return QuantityComparison(
            "불일치", "수량 확인 필요", "높음",
            "내역서 수량이 비어 있어 산출서 합계와 비교할 수 없습니다. 원본을 확인하세요.",
            None, None, None,
        )
    difference = derived_value - original_value
    rate = abs(difference / original_value) if original_value else None
    tolerance = exact_tolerance(original_value)
    if fields:
        fields.append("수량") if abs(difference) > tolerance else None
        return QuantityComparison(
            "불일치", "필드·수량 불일치", "높음",
            f"{', '.join(dict.fromkeys(fields))} 값이 다릅니다. 내역서 행과 산출근거를 확인하세요.",
            difference, rate, tolerance,
        )
    if abs(difference) <= tolerance:
        return QuantityComparison("일치", "표준화 필드·수량 일치", "낮음", "공사부서 1차 승인 대기", difference, rate, tolerance)
    threshold = warning_threshold(total_amount)
    if rate is not None and rate <= threshold:
        return QuantityComparison(
            "일치", "허용오차 내 근사 일치", "낮음",
            f"수량 차이 {rate * 100:.2f}%는 경고 기준 {threshold * 100:g}% 이내입니다. 공사부서 1차 승인 대기",
            difference, rate, threshold,
        )
    return QuantityComparison(
        "불일치", "필드·수량 불일치", "높음",
        "수량 값이 다릅니다. 내역서 행과 산출근거를 확인하세요.",
        difference, rate, threshold,
    )
