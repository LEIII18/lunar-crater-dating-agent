from __future__ import annotations

from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import rasterio
import shapefile
from PIL import Image, ImageDraw
from pyproj import CRS, Transformer
from rasterio.enums import Resampling
from rasterio.windows import Window, bounds as window_bounds, from_bounds

from .models import DatingError
from .workflow_models import OverlayPreview


def _read_crs(shp_path: Path) -> CRS:
    try:
        return CRS.from_wkt(shp_path.with_suffix(".prj").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DatingError(f"无法读取预览矢量坐标系：{shp_path}") from exc


def _rings(shp_path: Path, target_crs: CRS) -> list[list[tuple[float, float]]]:
    source_crs = _read_crs(shp_path)
    transformer = (
        None
        if source_crs.equals(target_crs)
        else Transformer.from_crs(source_crs, target_crs, always_xy=True)
    )
    rings: list[list[tuple[float, float]]] = []
    try:
        reader = shapefile.Reader(str(shp_path))
        try:
            for shape in reader.iterShapes():
                boundaries = list(shape.parts) + [len(shape.points)]
                for start, end in zip(boundaries, boundaries[1:]):
                    points = [
                        (float(point[0]), float(point[1]))
                        for point in shape.points[start:end]
                    ]
                    if transformer is not None and points:
                        xs, ys = transformer.transform(
                            [point[0] for point in points],
                            [point[1] for point in points],
                        )
                        points = list(zip(map(float, xs), map(float, ys)))
                    if points:
                        rings.append(points)
        finally:
            reader.close()
    except (OSError, ValueError, shapefile.ShapefileException) as exc:
        raise DatingError(f"无法读取叠加预览矢量：{shp_path}（{exc}）") from exc
    return rings


def _intersection_window(dataset, area_rings: list[list[tuple[float, float]]]) -> Window:
    if not area_rings:
        raise DatingError("AREA 没有可用于预览的几何")
    xs = [x for ring in area_rings for x, _ in ring]
    ys = [y for ring in area_rings for _, y in ring]
    left = max(min(xs), dataset.bounds.left)
    right = min(max(xs), dataset.bounds.right)
    bottom = max(min(ys), dataset.bounds.bottom)
    top = min(max(ys), dataset.bounds.top)
    if right <= left or top <= bottom:
        raise DatingError("AREA 不在 TIFF 影像范围内")
    try:
        window = from_bounds(left, bottom, right, top, dataset.transform)
        window = window.round_offsets().round_lengths()
        return window.intersection(Window(0, 0, dataset.width, dataset.height))
    except Exception as exc:
        raise DatingError(f"无法计算 AREA 与 TIFF 的预览范围：{exc}") from exc


def _normalize(array: np.ma.MaskedArray) -> np.ndarray:
    data = np.asarray(array.filled(0), dtype=np.float32)
    valid = np.asarray(array.compressed(), dtype=np.float32)
    if valid.size == 0:
        return np.zeros(data.shape, dtype=np.uint8)
    low, high = np.percentile(valid, (2, 98))
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        low = float(valid.min())
        high = float(valid.max())
    if high <= low:
        return np.zeros(data.shape, dtype=np.uint8)
    scaled = np.clip((data - low) / (high - low), 0, 1) * 255
    return scaled.astype(np.uint8)


def _read_preview(dataset, window: Window, max_dimension: int) -> np.ndarray:
    if max_dimension < 32:
        raise DatingError("预览最大边长不能小于 32 像素")
    scale = min(1.0, max_dimension / max(float(window.width), float(window.height)))
    width = max(1, int(round(float(window.width) * scale)))
    height = max(1, int(round(float(window.height) * scale)))
    indexes = tuple(range(1, min(dataset.count, 3) + 1))
    if not indexes:
        raise DatingError("TIFF 没有可用于预览的波段")
    data = dataset.read(
        indexes,
        window=window,
        out_shape=(len(indexes), height, width),
        resampling=Resampling.bilinear,
        masked=True,
    )
    channels = [_normalize(data[index]) for index in range(len(indexes))]
    if len(channels) == 1:
        channels *= 3
    elif len(channels) == 2:
        channels.append(channels[1])
    return np.dstack(channels[:3])


def _draw_overlay(
    rgb: np.ndarray,
    area_rings: list[list[tuple[float, float]]],
    crater_rings: list[list[tuple[float, float]]],
    extent: tuple[float, float, float, float],
    output_path: Path,
) -> None:
    left, bottom, right, top = extent
    height, width = rgb.shape[:2]

    def pixels(ring: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return [
            (
                (x - left) / (right - left) * (width - 1),
                (top - y) / (top - bottom) * (height - 1),
            )
            for x, y in ring
        ]

    image = Image.fromarray(rgb, mode="RGB")
    draw = ImageDraw.Draw(image)
    for ring in area_rings:
        draw.line(pixels(ring), fill=(70, 220, 255), width=3, joint="curve")
    for ring in crater_rings:
        draw.line(pixels(ring), fill=(255, 60, 60), width=2, joint="curve")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")


def _trace_coordinates(
    rings: list[list[tuple[float, float]]],
) -> tuple[list[float | None], list[float | None]]:
    xs: list[float | None] = []
    ys: list[float | None] = []
    for ring in rings:
        xs.extend(point[0] for point in ring)
        ys.extend(point[1] for point in ring)
        xs.append(None)
        ys.append(None)
    return xs, ys


def _figure(
    rgb: np.ndarray,
    area_rings: list[list[tuple[float, float]]],
    crater_rings: list[list[tuple[float, float]]],
    extent: tuple[float, float, float, float],
    case_id: str,
) -> go.Figure:
    left, bottom, right, top = extent
    area_x, area_y = _trace_coordinates(area_rings)
    crater_x, crater_y = _trace_coordinates(crater_rings)
    figure = go.Figure()
    figure.add_layout_image(
        source=Image.fromarray(rgb, mode="RGB"),
        xref="x",
        yref="y",
        x=left,
        y=top,
        sizex=right - left,
        sizey=top - bottom,
        sizing="stretch",
        layer="below",
    )
    figure.add_trace(
        go.Scatter(
            x=area_x,
            y=area_y,
            mode="lines",
            name=f"AREA_{case_id} 定年区域",
            line={"color": "#46dcff", "width": 3, "dash": "dash"},
            hoverinfo="skip",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=crater_x,
            y=crater_y,
            mode="lines",
            name=f"CRATER_{case_id} 撞击坑轮廓",
            line={"color": "#ff3c3c", "width": 2},
            hoverinfo="skip",
        )
    )
    figure.update_layout(
        dragmode="pan",
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.01},
        xaxis={"range": [left, right], "showgrid": False, "zeroline": False},
        yaxis={
            "range": [bottom, top],
            "showgrid": False,
            "zeroline": False,
            "scaleanchor": "x",
            "scaleratio": 1,
        },
    )
    return figure


def render_overlay_preview(
    image_tif: Path,
    area_shp: Path,
    crater_shp: Path,
    output_path: Path,
    case_id: str,
    *,
    max_dimension: int = 1600,
) -> OverlayPreview:
    image_tif = Path(image_tif).resolve()
    output_path = Path(output_path).resolve()
    try:
        with rasterio.open(image_tif) as dataset:
            if dataset.crs is None:
                raise DatingError(f"TIFF 缺少坐标系：{image_tif}")
            target_crs = CRS.from_wkt(dataset.crs.to_wkt())
            area_rings = _rings(Path(area_shp).resolve(), target_crs)
            crater_rings = _rings(Path(crater_shp).resolve(), target_crs)
            window = _intersection_window(dataset, area_rings)
            rgb = _read_preview(dataset, window, max_dimension)
            extent = tuple(map(float, window_bounds(window, dataset.transform)))
    except DatingError:
        raise
    except (OSError, ValueError, rasterio.errors.RasterioError) as exc:
        raise DatingError(f"无法生成 TIFF 叠加预览：{exc}") from exc
    _draw_overlay(rgb, area_rings, crater_rings, extent, output_path)
    figure = _figure(rgb, area_rings, crater_rings, extent, case_id)
    height, width = rgb.shape[:2]
    return OverlayPreview(output_path, figure, width, height)
