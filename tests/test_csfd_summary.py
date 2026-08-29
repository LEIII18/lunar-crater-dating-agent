from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from crater_dating_agent.models import DatingError, ResolvedInputs
from crater_dating_agent.overview import extract_csfd_summary


def inputs(tmp_path: Path) -> ResolvedInputs:
    return ResolvedInputs(
        "SID9",
        (tmp_path / "CRATER_SID9.shp").resolve(),
        (tmp_path / "AREA_SID9.shp").resolve(),
        (tmp_path / "image.tif").resolve(),
        63,
    )


class FakeCratercount:
    area = 10.0
    perimeter = 4.0
    binned = {
        "d_min": np.array([0.060, 0.064, 0.070]),
        "d_max": np.array([0.064, 0.070, 0.080]),
        "d_mean": np.array([0.062, 0.067, 0.075]),
        "bin_width": np.array([0.004, 0.006, 0.010]),
        "n": np.array([21.0, 0.0, 42.0]),
        "n_event": np.array([21, 0, 42]),
        "ncum": np.array([63.0, 42.0, 42.0]),
    }

    def apply_binning(self, binning: str) -> None:
        assert binning == "pseudo-log"


def test_summary_uses_literal_craterstats_bins_and_omits_empty_bins(tmp_path: Path) -> None:
    summary = extract_csfd_summary(
        inputs(tmp_path), cratercount_factory=lambda crater, area: FakeCratercount()
    )

    assert len(summary.bins) == 2
    assert summary.bins[0].d_min_km == pytest.approx(0.060)
    assert summary.bins[0].event_count == 21
    assert summary.bins[0].differential_density == pytest.approx(525.0)
    assert summary.bins[0].uncertainty == pytest.approx(525.0 / np.sqrt(21))
    assert summary.total_event_count == 63
    assert summary.area_km2 == pytest.approx(10.0)
    assert summary.perimeter_km == pytest.approx(4.0)
    assert summary.diameter_min_km == pytest.approx(0.060)
    assert summary.diameter_max_km == pytest.approx(0.080)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("area", 0.0, "面积"),
        ("area", float("nan"), "有限"),
        ("n", np.array([21.0, float("inf"), 42.0]), "有限"),
        ("empty", np.array([0, 0, 0]), "非空"),
    ],
)
def test_summary_rejects_invalid_scientific_values(
    tmp_path: Path, field: str, value, message: str
) -> None:
    class Invalid(FakeCratercount):
        pass

    invalid = Invalid()
    if field == "area":
        invalid.area = value
    elif field == "empty":
        invalid.binned = dict(
            FakeCratercount.binned,
            n=np.array([0.0, 0.0, 0.0]),
            n_event=value,
        )
    else:
        invalid.binned = dict(FakeCratercount.binned, **{field: value})

    with pytest.raises(DatingError, match=message):
        extract_csfd_summary(inputs(tmp_path), cratercount_factory=lambda c, a: invalid)


def test_summary_rejects_mismatched_bin_arrays(tmp_path: Path) -> None:
    invalid = FakeCratercount()
    invalid.binned = dict(FakeCratercount.binned, d_max=np.array([0.064]))

    with pytest.raises(DatingError, match="长度"):
        extract_csfd_summary(inputs(tmp_path), cratercount_factory=lambda c, a: invalid)
