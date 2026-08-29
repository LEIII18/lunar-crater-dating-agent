from __future__ import annotations

from pathlib import Path

import pytest

from crater_dating_agent.models import DatingError
from crater_dating_agent.result_parser import parse_age_csv


FIXTURE = Path(__file__).parent / "fixtures" / "craterstats_minimal.csv"
DUPLICATE_HEADER_FIXTURE = (
    Path(__file__).parent / "fixtures" / "craterstats_duplicate_headers.csv"
)


def test_parse_age_csv_reads_fit_by_header_names() -> None:
    result = parse_age_csv(FIXTURE)

    assert result.crater_count == 63
    assert result.age_ga == pytest.approx(0.376)
    assert result.age_lower_ga == pytest.approx(0.331)
    assert result.age_upper_ga == pytest.approx(0.425)
    assert result.age_minus_ga == pytest.approx(0.045)
    assert result.age_plus_ga == pytest.approx(0.049)


def test_parse_age_csv_uses_first_numeric_age_when_formatted_columns_repeat_names() -> None:
    result = parse_age_csv(DUPLICATE_HEADER_FIXTURE)

    assert result.age_ga == pytest.approx(0.376)
    assert result.age_lower_ga == pytest.approx(0.331)
    assert result.age_upper_ga == pytest.approx(0.425)


def write_csv(path: Path, header: str, row: str) -> None:
    path.write_text(f"preamble\n{header}\n{row}\n", encoding="utf-8")


def test_parse_age_csv_rejects_missing_required_column(tmp_path: Path) -> None:
    path = tmp_path / "missing.csv"
    write_csv(path, "Name,Method,N_event,Age,Age-", "X,b-poisson,3,1.0,0.9")

    with pytest.raises(DatingError, match=r"Age\+"):
        parse_age_csv(path)


def test_parse_age_csv_rejects_csv_without_b_poisson_fit(tmp_path: Path) -> None:
    path = tmp_path / "no_fit.csv"
    write_csv(
        path,
        "Name,Method,N_event,Age,Age-,Age+",
        "X,data,3,1.0,0.9,1.1",
    )

    with pytest.raises(DatingError, match="b-poisson"):
        parse_age_csv(path)


def test_parse_age_csv_rejects_nonnumeric_age(tmp_path: Path) -> None:
    path = tmp_path / "bad_age.csv"
    write_csv(
        path,
        "Name,Method,N_event,Age,Age-,Age+",
        "X,b-poisson,3,not-a-number,0.9,1.1",
    )

    with pytest.raises(DatingError, match="Age"):
        parse_age_csv(path)


@pytest.mark.parametrize(
    ("count", "age", "lower", "upper", "message"),
    [
        ("3", "nan", "0.9", "1.1", "有限"),
        ("3", "1.0", "nan", "1.1", "有限"),
        ("3", "1.0", "0.9", "inf", "有限"),
        ("-1", "1.0", "0.9", "1.1", "撞击坑数量"),
        ("3.5", "1.0", "0.9", "1.1", "撞击坑数量"),
        ("3", "1.0", "1.01", "1.1", "置信区间"),
        ("3", "1.0", "0.9", "0.99", "置信区间"),
    ],
)
def test_parse_age_csv_rejects_scientifically_invalid_values(
    tmp_path: Path,
    count: str,
    age: str,
    lower: str,
    upper: str,
    message: str,
) -> None:
    path = tmp_path / "invalid_science.csv"
    write_csv(
        path,
        "Name,Method,N_event,Age,Age-,Age+",
        f"X,b-poisson,{count},{age},{lower},{upper}",
    )

    with pytest.raises(DatingError, match=message):
        parse_age_csv(path)
