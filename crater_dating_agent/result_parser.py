from __future__ import annotations

import csv
from math import isfinite
from pathlib import Path

from .models import AgeEstimate, DatingError


REQUIRED_COLUMNS = ("Name", "Method", "Age", "Age-", "Age+")


def _to_float(row: dict[str, str], field: str) -> float:
    try:
        return float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise DatingError(f"Craterstats CSV 的 {field} 不是有效数值") from exc


def parse_age_csv(csv_path: Path) -> AgeEstimate:
    csv_path = Path(csv_path)
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.reader(stream))
    except OSError as exc:
        raise DatingError(f"无法读取 Craterstats CSV：{csv_path}（{exc}）") from exc

    header_index = next(
        (index for index, row in enumerate(rows) if row and row[0].strip() == "Name"),
        None,
    )
    if header_index is None:
        raise DatingError("Craterstats CSV 未找到 Name 表头")
    header = rows[header_index]
    missing = [name for name in REQUIRED_COLUMNS if name not in header]
    if missing:
        raise DatingError(f"Craterstats CSV 缺少字段：{', '.join(missing)}")

    dictionaries = []
    for values in rows[header_index + 1 :]:
        if not values:
            continue
        record: dict[str, str] = {}
        for name, value in zip(header, values):
            if name not in record:
                record[name] = value
        dictionaries.append(record)
    fits = [row for row in dictionaries if row.get("Method", "").strip() == "b-poisson"]
    if len(fits) != 1:
        raise DatingError(f"Craterstats CSV 需要且只能有一条 b-poisson 结果，实际为 {len(fits)} 条")
    row = fits[0]

    count_field = "N_event" if row.get("N_event", "").strip() else "N"
    try:
        count_value = float(row[count_field])
    except (KeyError, TypeError, ValueError) as exc:
        raise DatingError("Craterstats CSV 的撞击坑数量不是有效数值") from exc
    if not isfinite(count_value) or count_value < 0 or not count_value.is_integer():
        raise DatingError("Craterstats CSV 的撞击坑数量必须是非负整数")
    crater_count = int(count_value)

    age = _to_float(row, "Age")
    lower = _to_float(row, "Age-")
    upper = _to_float(row, "Age+")
    if not all(isfinite(value) for value in (age, lower, upper)):
        raise DatingError("Craterstats CSV 的年龄和置信边界必须是有限数值")
    if not lower <= age <= upper:
        raise DatingError("Craterstats CSV 的年龄置信区间顺序无效")
    return AgeEstimate(
        crater_count=crater_count,
        age_ga=age,
        age_lower_ga=lower,
        age_upper_ga=upper,
        age_minus_ga=age - lower,
        age_plus_ga=upper - age,
    )
