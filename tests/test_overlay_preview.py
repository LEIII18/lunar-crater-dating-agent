from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import shapefile
from pyproj import CRS, Transformer

from crater_dating_agent.models import DatingError
from crater_dating_agent.overlay_preview import render_overlay_preview


def _write_tif(path: Path, *, width: int = 240, height: int = 160) -> Path:
    import rasterio
    from rasterio.transform import from_origin

    values = np.linspace(0, 255, width * height, dtype=np.uint8).reshape(
        height, width
    )
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="uint8",
        crs="EPSG:3857",
        transform=from_origin(0, 160, 1, 1),
    ) as dataset:
        dataset.write(values, 1)
    return path


def _write_polygon_shp(
    path: Path,
    *,
    kind: str,
    polygons: list[list[list[float]]],
    crs: CRS,
) -> Path:
    with shapefile.Writer(str(path), shapeType=shapefile.POLYGON) as writer:
        if kind == "area":
            writer.field("Area", "F", size=19, decimal=11)
            writer.field("Area_Name", "C", size=30)
            for polygon in polygons:
                writer.poly([polygon])
                writer.record(1.0, path.stem)
        else:
            writer.field("Diam_km", "F", size=19, decimal=11)
            writer.field("x_coord", "F", size=19, decimal=11)
            writer.field("y_coord", "F", size=19, decimal=11)
            writer.field("tag", "C", size=8)
            for index, polygon in enumerate(polygons):
                writer.poly([polygon])
                writer.record(0.5 + index, polygon[0][0], polygon[0][1], "standard")
    path.with_suffix(".prj").write_text(crs.to_wkt(), encoding="utf-8")
    return path


def _projected_fixture(tmp_path: Path):
    image = _write_tif(tmp_path / "image.tif")
    area = _write_polygon_shp(
        tmp_path / "AREA_Saussure_D.shp",
        kind="area",
        polygons=[[[20, 20], [180, 20], [180, 140], [20, 140], [20, 20]]],
        crs=CRS.from_epsg(3857),
    )
    crater = _write_polygon_shp(
        tmp_path / "CRATER_Saussure_D.shp",
        kind="crater",
        polygons=[
            [[50, 60], [70, 60], [70, 80], [50, 80], [50, 60]],
            [[120, 90], [150, 90], [150, 120], [120, 120], [120, 90]],
        ],
        crs=CRS.from_epsg(3857),
    )
    return image, area, crater


def test_overlay_is_downsampled_and_uses_dynamic_layer_names(tmp_path: Path) -> None:
    image, area, crater = _projected_fixture(tmp_path)

    preview = render_overlay_preview(
        image,
        area,
        crater,
        tmp_path / "automatic_overlay.png",
        "Saussure_D",
        max_dimension=96,
    )

    assert preview.png_path.is_file() and preview.png_path.stat().st_size > 0
    assert max(preview.width, preview.height) <= 96
    assert [trace.name for trace in preview.figure.data] == [
        "AREA_Saussure_D 定年区域",
        "CRATER_Saussure_D 撞击坑轮廓",
    ]
    assert preview.figure.layout.dragmode == "pan"


def test_overlay_transforms_vector_coordinates_to_raster_crs(tmp_path: Path) -> None:
    image = _write_tif(tmp_path / "image.tif")
    to_lonlat = Transformer.from_crs(3857, 4326, always_xy=True)

    def lonlat(x: float, y: float) -> list[float]:
        lon, lat = to_lonlat.transform(x, y)
        return [lon, lat]

    area_ring = [lonlat(20, 20), lonlat(180, 20), lonlat(180, 140), lonlat(20, 140), lonlat(20, 20)]
    crater_ring = [lonlat(60, 60), lonlat(80, 60), lonlat(80, 80), lonlat(60, 80), lonlat(60, 60)]
    area = _write_polygon_shp(
        tmp_path / "AREA_X.shp",
        kind="area",
        polygons=[area_ring],
        crs=CRS.from_epsg(4326),
    )
    crater = _write_polygon_shp(
        tmp_path / "CRATER_X.shp",
        kind="crater",
        polygons=[crater_ring],
        crs=CRS.from_epsg(4326),
    )

    preview = render_overlay_preview(
        image, area, crater, tmp_path / "overlay.png", "X", max_dimension=120
    )

    crater_x = [value for value in preview.figure.data[1].x if value is not None]
    assert min(crater_x) == pytest.approx(60, abs=0.1)
    assert max(crater_x) == pytest.approx(80, abs=0.1)


def test_overlay_rejects_area_outside_raster(tmp_path: Path) -> None:
    image = _write_tif(tmp_path / "image.tif")
    area = _write_polygon_shp(
        tmp_path / "AREA_X.shp",
        kind="area",
        polygons=[[[500, 500], [600, 500], [600, 600], [500, 600], [500, 500]]],
        crs=CRS.from_epsg(3857),
    )
    crater = _write_polygon_shp(
        tmp_path / "CRATER_X.shp",
        kind="crater",
        polygons=[[[520, 520], [530, 520], [530, 530], [520, 520]]],
        crs=CRS.from_epsg(3857),
    )

    with pytest.raises(DatingError, match="影像范围"):
        render_overlay_preview(
            image, area, crater, tmp_path / "overlay.png", "X"
        )
