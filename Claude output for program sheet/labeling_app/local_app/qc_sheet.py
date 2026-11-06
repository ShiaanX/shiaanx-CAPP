from __future__ import annotations

from io import BytesIO
import re
from typing import Any, Iterator

_DESCRIPTION = re.compile(r"^\s*(\D*?)\s*(\d+(?:\.\d+)?)\s*$")
_READING_SPLIT = re.compile(r"[\s/,;|]+")

# A reading inside tolerance is flagged "near limit" when it sits within this share of the tolerance band from a limit.
NEAR_LIMIT_SHARE = 0.15
_EPS = 1e-6


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_description(value: Any) -> tuple[str, float | None]:
    """Return (dim_type, nominal) from a QC description cell such as 78, 'Ø9', 'R3', 'M6'."""
    number = _number(value)
    if number is not None:
        return "linear", number
    match = _DESCRIPTION.match(str(value or ""))
    if not match:
        return "other", None
    prefix, digits = match.group(1).strip(), float(match.group(2))
    if prefix.upper() == "R":
        return "radius", digits
    if prefix.upper().startswith("M"):
        return "thread", digits
    # The diameter symbol usually arrives as a mangled character (e.g. U+FFFD) from the Excel export.
    return "diameter", digits


def _open_workbook(data: bytes):
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("openpyxl is not installed; run: pip install openpyxl") from exc
    return load_workbook(BytesIO(data), data_only=True, read_only=True)


def _header_column(header: tuple[Any, ...], prefix: str, default: int) -> int:
    for index, cell in enumerate(header):
        if isinstance(cell, str) and cell.strip().lower().startswith(prefix):
            return index
    return default


def _table_rows(data: bytes) -> Iterator[tuple[int, tuple[Any, ...], int, int]]:
    """Yield (balloon, cells, observation_col, remark_col) for each numbered row; first occurrence of a balloon wins."""
    seen: set[int] = set()
    for sheet in _open_workbook(data).worksheets:
        in_table = False
        observation_col, remark_col = 5, 9
        for cells in sheet.iter_rows(values_only=True):
            first = cells[0] if cells else None
            if isinstance(first, str) and first.strip().lower().startswith("sl"):
                in_table = True
                observation_col = _header_column(cells, "observ", 5)
                remark_col = _header_column(cells, "remark", 9)
                continue
            if not in_table:
                continue
            number = _number(first)
            if number is None or number != int(number) or number < 1:
                if isinstance(first, str) and first.strip():
                    in_table = False
                continue
            balloon = int(number)
            if balloon in seen:
                continue
            seen.add(balloon)
            yield balloon, cells, observation_col, remark_col


def _cell(cells: tuple[Any, ...], index: int) -> Any:
    return cells[index] if len(cells) > index else None


def parse_qc_sheet(data: bytes) -> list[dict[str, Any]]:
    """Read balloon rows (SL No., description, TOL+, TOL-) from a final-inspection .xlsx."""
    rows = []
    for balloon, cells, _, _ in _table_rows(data):
        description = _cell(cells, 1)
        dim_type, nominal = parse_description(description)
        rows.append({
            "balloon": balloon,
            "dim_type": dim_type,
            "description_raw": "" if description is None else str(description),
            "nominal": nominal,
            "tol_plus": _number(_cell(cells, 2)),
            "tol_minus": _number(_cell(cells, 3)),
        })
    return sorted(rows, key=lambda row: row["balloon"])


def _readings(cells: tuple[Any, ...], start: int, stop: int) -> list[float]:
    values: list[float] = []
    for cell in cells[start:stop]:
        if cell is None:
            continue
        for part in _READING_SPLIT.split(str(cell).strip()):
            number = _number(part)
            if number is not None:
                values.append(number)
    return values


def parse_qc_results(data: bytes) -> list[dict[str, Any]]:
    """Read measured values and the inspector's remark for each balloon from a final-inspection .xlsx."""
    rows = []
    for balloon, cells, observation_col, remark_col in _table_rows(data):
        remark = _cell(cells, remark_col)
        rows.append({
            "balloon": balloon,
            "readings": _readings(cells, observation_col, remark_col),
            "sheet_remark": "" if remark is None else str(remark).strip(),
            "instrument": "" if _cell(cells, 4) is None else str(_cell(cells, 4)).strip(),
            "tol_plus": _number(_cell(cells, 2)),
            "tol_minus": _number(_cell(cells, 3)),
            "nominal": parse_description(_cell(cells, 1))[1],
        })
    return sorted(rows, key=lambda row: row["balloon"])


def evaluate_dimension(
    nominal: float | None,
    tol_plus: float | None,
    tol_minus: float | None,
    readings: list[float],
) -> dict[str, Any]:
    """Verdict for one balloon: pass, near_limit, fail, pending (no readings) or unknown (no tolerance)."""
    if not readings:
        return {"verdict": "pending", "lower": None, "upper": None, "worst_reading": None, "margin_pct": None}
    if nominal is None or (tol_plus is None and tol_minus is None):
        return {"verdict": "unknown", "lower": None, "upper": None, "worst_reading": None, "margin_pct": None}
    lower = round(nominal - abs(tol_minus or 0.0), 6)
    upper = round(nominal + abs(tol_plus or 0.0), 6)
    band = upper - lower

    outside = [r for r in readings if r < lower - _EPS or r > upper + _EPS]
    if outside:
        worst = max(outside, key=lambda r: max(lower - r, r - upper))
        return {"verdict": "fail", "lower": lower, "upper": upper, "worst_reading": worst, "margin_pct": None}

    worst = min(readings, key=lambda r: min(r - lower, upper - r))
    margin = min(worst - lower, upper - worst)
    share = margin / band if band > _EPS else 0.0
    near = band > _EPS and share < NEAR_LIMIT_SHARE - _EPS
    return {
        "verdict": "near_limit" if near else "pass",
        "lower": lower,
        "upper": upper,
        "worst_reading": worst,
        "margin_pct": round(share * 100, 1),
    }
