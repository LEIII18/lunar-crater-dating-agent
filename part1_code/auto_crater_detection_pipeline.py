# -*- coding: utf-8 -*-
"""
ArcGIS 10.8 / Python 2.7 compatible automation for the crater workflow.

This main script is intended to run with:
    C:\\Python27\\ArcGIS10.8\\python.exe

Because the neural-network model was written for Python 3, this script calls
tools/run_wangyiran_model_py3.py in a separate Python 3 process for detection.
ArcPy stays in Python 2.7 and handles clipping, projection definition, and
appending the detected craters into the target CRATER shapefile.
"""

from __future__ import print_function

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import time

import arcpy

try:
    unicode
except NameError:
    unicode = str

if sys.version_info[0] < 3:
    reload(sys)  # noqa: F821  (Python 2 only builtin)
    sys.setdefaultencoding("mbcs")


DEFAULT_AREA_SHP = u"G:\\地化所\\2026\\文章\\撞击坑分类\\4. 几个数据集年代标签对比\\定年\\data\\crater_classify_paper\\date\\35\\date\\AREA_Saussure_D.shp"
DEFAULT_IMAGE_TIF = u"G:\\地化所\\2026\\文章\\撞击坑分类\\4. 几个数据集年代标签对比\\定年\\data\\crater_classify_paper\\date\\35\\8mdom\\0_15E47_01S.tif"
DEFAULT_TARGET_SHP = u"G:\\地化所\\2026\\文章\\撞击坑分类\\4. 几个数据集年代标签对比\\定年\\data\\crater_classify_paper\\date\\35\\date\\CRATER_Saussure_D.shp"
DEFAULT_MODEL_DIR = u"E:\\DiHuaSuo\\2026\\paper\\csfd_agent\\agent_build\\wangyiranCode"

SHAPEFILE_SUFFIXES = [".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".qix", ".xml"]


def here():
    return os.path.dirname(os.path.abspath(__file__))

# 换电脑这个环境要换
def default_model_python():
    return os.environ.get(
        "CRATER_MODEL_PYTHON",
        r"C:\ProgramData\Anaconda3\envs\crater_model_py39\python.exe"
    )


def parse_args():
    parser = argparse.ArgumentParser(description="Clip tif, run model by Python 3, then append craters by ArcPy.")
    parser.add_argument("--area-shp", default=DEFAULT_AREA_SHP, help="AREA crater mask shapefile.")
    parser.add_argument("--image-tif", default=DEFAULT_IMAGE_TIF, help="Input remote sensing GeoTIFF.")
    parser.add_argument("--target-shp", default=DEFAULT_TARGET_SHP, help="Target CRATER shapefile to append into.")
    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR, help="wangyiranCode folder.")
    parser.add_argument(
        "--model-python",
        default=default_model_python(),
        help="Python 3 executable used to run the model. Can also set CRATER_MODEL_PYTHON.",
    )
    parser.add_argument(
        "--work-dir",
        default=None,
        help="Output folder. Default: <sample folder>\\data_auto inferred from --image-tif.",
    )
    parser.add_argument("--tag", default="standard", help="Value written into target field tag.")
    parser.add_argument("--replace-tag", action="store_true", help="Delete existing rows whose tag equals --tag first.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite clipped tif and model output if they exist.")
    parser.add_argument("--no-backup", action="store_true", help="Do not back up target shapefile before appending.")
    parser.add_argument("--check-only", action="store_true", help="Only check environment and input paths; do not write data.")
    return parser.parse_args()


def as_text(value):
    if isinstance(value, unicode):  # noqa: F821  (Python 2 only name)
        return value
    try:
        return value.decode(sys.getfilesystemencoding() or "mbcs")
    except Exception:
        return value


def subprocess_arg(value):
    if sys.version_info[0] >= 3:
        return value
    if isinstance(value, unicode):
        return value.encode("mbcs")
    return value


def subprocess_call(cmd):
    return subprocess.call([subprocess_arg(item) for item in cmd])


def require_path(path, label):
    if not os.path.exists(path):
        raise RuntimeError("%s not found: %s" % (label, path))


def ensure_dir(path):
    if not os.path.isdir(path):
        os.makedirs(path)


def infer_sample_root(image_tif):
    return os.path.dirname(os.path.dirname(os.path.abspath(image_tif)))


def parse_tile_origin_lonlat(image_tif):
    name = os.path.splitext(os.path.basename(image_tif))[0]
    match = re.search(r"(\d+(?:_\d+)?)([EW])(\d+(?:_\d+)?)([NS])", name, re.IGNORECASE)
    if not match:
        raise RuntimeError(
            "Cannot parse tile origin lon/lat from tif name '%s'. Expected like 97_37W3_63S.tif" % name
        )
    lon = float(match.group(1).replace("_", "."))
    lat = float(match.group(3).replace("_", "."))
    if match.group(2).upper() == "W":
        lon = -lon
    if match.group(4).upper() == "S":
        lat = -lat
    return lon, lat


def shapefile_components(shp_path):
    base, _ = os.path.splitext(shp_path)
    return [base + suffix for suffix in SHAPEFILE_SUFFIXES]


def delete_dataset(path):
    if arcpy.Exists(path):
        arcpy.management.Delete(path)


def feature_spatial_reference(feature_path, layer_name):
    desc = arcpy.Describe(feature_path)
    if hasattr(desc, "spatialReference"):
        return desc.spatialReference

    if arcpy.Exists(layer_name):
        arcpy.Delete_management(layer_name)
    arcpy.MakeFeatureLayer_management(feature_path, layer_name)
    try:
        layer_desc = arcpy.Describe(layer_name)
        if hasattr(layer_desc, "spatialReference"):
            return layer_desc.spatialReference
    finally:
        try:
            arcpy.Delete_management(layer_name)
        except Exception:
            pass
    raise RuntimeError("Cannot read spatial reference from: %s" % feature_path)


def copy_shapefile(src_shp, dst_shp):
    ensure_dir(os.path.dirname(dst_shp))
    dst_base, _ = os.path.splitext(dst_shp)
    for src in shapefile_components(src_shp):
        if os.path.exists(src):
            _, suffix = os.path.splitext(src)
            shutil.copy2(src, dst_base + suffix)


def backup_target_shapefile(target_shp, work_dir):
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    target_name = os.path.splitext(os.path.basename(target_shp))[0]
    backup_shp = os.path.join(work_dir, "backup", "%s_%s.shp" % (target_name, timestamp))
    copy_shapefile(target_shp, backup_shp)
    return backup_shp


def clip_raster_by_mask(input_raster, area_shp, out_dir, overwrite):
    require_path(input_raster, "Input raster")
    require_path(area_shp, "AREA shapefile")
    ensure_dir(out_dir)

    frame_name = os.path.splitext(os.path.basename(area_shp))[0]
    out_raster = os.path.join(out_dir, frame_name + "_clip.tif")
    if os.path.exists(out_raster) and not overwrite:
        print("Using existing clipped raster: %s" % out_raster)
        return out_raster
    if os.path.exists(out_raster):
        delete_dataset(out_raster)

    old_output_coordinate_system = arcpy.env.outputCoordinateSystem
    old_snap_raster = arcpy.env.snapRaster
    old_overwrite = arcpy.env.overwriteOutput
    try:
        arcpy.CheckOutExtension("Spatial")
        arcpy.env.outputCoordinateSystem = feature_spatial_reference(area_shp, "area_sr_layer")
        arcpy.env.snapRaster = input_raster
        arcpy.env.overwriteOutput = True

        print("Clipping raster by AREA shapefile...")
        print("  raster: %s" % input_raster)
        print("  area:   %s" % area_shp)
        print("  out:    %s" % out_raster)
        arcpy.gp.ExtractByMask_sa(input_raster, area_shp, out_raster)
    finally:
        arcpy.env.outputCoordinateSystem = old_output_coordinate_system
        arcpy.env.snapRaster = old_snap_raster
        arcpy.env.overwriteOutput = old_overwrite
        try:
            arcpy.CheckInExtension("Spatial")
        except Exception:
            pass

    return out_raster


def run_model_python3(model_python, model_dir, clipped_tif, output_dir, overwrite):
    helper = os.path.join(here(), "run_wangyiran_model_py3.py")
    require_path(helper, "Python 3 model helper")
    require_path(model_dir, "Model folder")
    ensure_dir(output_dir)

    cmd = [
        model_python,
        helper,
        "--model-dir",
        model_dir,
        "--image-tif",
        clipped_tif,
        "--output-dir",
        output_dir,
    ]
    if overwrite:
        cmd.append("--overwrite")

    print("Running crater model in Python 3...")
    print("  python: %s" % model_python)
    print("  helper: %s" % helper)
    ret = subprocess_call(cmd)
    if ret != 0:
        raise RuntimeError("Python 3 model process failed with exit code %s" % ret)

    out_shp = os.path.join(output_dir, os.path.splitext(os.path.basename(clipped_tif))[0] + ".shp")
    if not os.path.exists(out_shp):
        raise RuntimeError("Model did not create expected shapefile: %s" % out_shp)
    return out_shp


def define_projection_from_raster(shp_path, raster_path):
    raster_sr = arcpy.Describe(raster_path).spatialReference
    if not raster_sr or raster_sr.name == "Unknown":
        raise RuntimeError("Input raster has unknown spatial reference: %s" % raster_path)
    try:
        current_sr = feature_spatial_reference(shp_path, "detected_sr_layer")
        if current_sr and current_sr.name == raster_sr.name:
            print("Detected shp projection is already: %s" % raster_sr.name)
            return raster_sr
    except Exception:
        pass

    print("Define Projection for detected shp from input tif:")
    print("  shp: %s" % shp_path)
    print("  sr:  %s" % raster_sr.name)
    try:
        arcpy.management.DefineProjection(shp_path, raster_sr)
    except Exception:
        current_sr = feature_spatial_reference(shp_path, "detected_sr_layer")
        if current_sr and current_sr.name == raster_sr.name:
            print("Define Projection skipped because dataset is in use, but projection is already correct.")
        else:
            raise
    return raster_sr


def spatial_reference_from_prj(prj_path):
    require_path(prj_path, "PRJ file")
    sr = arcpy.SpatialReference()
    with open(prj_path, "r") as f:
        sr.loadFromString(f.read())
    return sr


def prepare_detected_for_target(detected_shp, model_dir, target_sr, out_dir, overwrite):
    ensure_dir(out_dir)
    detected_name = os.path.splitext(os.path.basename(detected_shp))[0]
    mercator_copy = os.path.join(out_dir, detected_name + "_mercator.shp")
    projected = os.path.join(out_dir, detected_name + "_projected.shp")
    moon_mercator_prj = os.path.join(model_dir, "prj_data", "Moon_Mercator.prj")
    moon_mercator_sr = spatial_reference_from_prj(moon_mercator_prj)

    if arcpy.Exists(projected) and not overwrite:
        print("Using existing projected detector output: %s" % projected)
        return projected

    if arcpy.Exists(mercator_copy):
        arcpy.Delete_management(mercator_copy)
    if arcpy.Exists(projected):
        arcpy.Delete_management(projected)

    print("Preparing detector output for target CRS...")
    print("  source Mercator copy: %s" % mercator_copy)
    print("  projected output:     %s" % projected)
    arcpy.CopyFeatures_management(detected_shp, mercator_copy)
    arcpy.management.DefineProjection(mercator_copy, moon_mercator_sr)
    arcpy.Project_management(mercator_copy, projected, target_sr)
    return projected


def get_geographic_sr(spatial_reference):
    if spatial_reference.type == "Geographic":
        return spatial_reference
    try:
        gcs = spatial_reference.GCS
        if gcs and gcs.name != "Unknown":
            return gcs
    except Exception:
        pass
    raise RuntimeError("Cannot get geographic coordinate system from: %s" % spatial_reference.name)


def field_names(dataset):
    names = {}
    for field in arcpy.ListFields(dataset):
        names[field.name.lower()] = field.name
    return names


def require_field(dataset, lower_name):
    names = field_names(dataset)
    key = lower_name.lower()
    if key not in names:
        raise RuntimeError("Field '%s' not found in %s" % (lower_name, dataset))
    return names[key]


def sql_string(value):
    return str(value).replace("'", "''")


def delete_existing_tagged_rows(target_shp, tag_field, tag_value):
    where = "%s = '%s'" % (arcpy.AddFieldDelimiters(target_shp, tag_field), sql_string(tag_value))
    deleted = 0
    with arcpy.da.UpdateCursor(target_shp, [tag_field], where_clause=where) as cursor:
        for _ in cursor:
            cursor.deleteRow()
            deleted += 1
    print("Deleted %s existing rows with %s='%s'." % (deleted, tag_field, tag_value))


def is_empty_geometry(geom):
    if geom is None:
        return True
    if hasattr(geom, "isEmpty"):
        return geom.isEmpty
    return getattr(geom, "pointCount", 0) == 0


def absolute_lonlat(rel_or_abs_lon, rel_or_abs_lat, tile_origin):
    origin_lon, origin_lat = tile_origin
    lon = float(rel_or_abs_lon)
    lat = float(rel_or_abs_lat)
    # Older GUI examples sometimes show local offsets (for example 0.295).
    # Current model output can also be absolute lon/lat (for example -97.075).
    if abs(lon - origin_lon) <= 20.0 and abs(lat - origin_lat) <= 20.0:
        return lon, lat
    return origin_lon + lon, origin_lat + lat


def append_detected_to_target(detected_shp, target_shp, tile_origin, tag_value, replace_tag, summary_csv):
    require_path(detected_shp, "Detected shapefile")
    require_path(target_shp, "Target CRATER shapefile")

    detected_fields = field_names(detected_shp)
    if "dia" not in detected_fields:
        raise RuntimeError("Detected shapefile must contain field Dia: %s" % detected_shp)
    if "lon" not in detected_fields or "lat" not in detected_fields:
        raise RuntimeError("Detected shapefile must contain fields Lon and Lat: %s" % detected_shp)

    diam_field = require_field(target_shp, "diam_km")
    x_field = require_field(target_shp, "x_coord")
    y_field = require_field(target_shp, "y_coord")
    tag_field = require_field(target_shp, "tag")

    if replace_tag:
        delete_existing_tagged_rows(target_shp, tag_field, tag_value)

    origin_lon, origin_lat = tile_origin

    rows_for_csv = []
    insert_fields = ["SHAPE@", diam_field, x_field, y_field, tag_field]
    search_fields = ["OID@", "SHAPE@", detected_fields["lon"], detected_fields["lat"], detected_fields["dia"]]
    if "score" in detected_fields:
        search_fields.append(detected_fields["score"])

    inserted = 0
    with arcpy.da.SearchCursor(detected_shp, search_fields) as search_cursor:
        with arcpy.da.InsertCursor(target_shp, insert_fields) as insert_cursor:
            for row in search_cursor:
                oid = row[0]
                geom = row[1]
                rel_lon = row[2]
                rel_lat = row[3]
                dia_m = row[4]
                score = row[5] if len(row) > 5 else None
                if is_empty_geometry(geom) or rel_lon is None or rel_lat is None or dia_m is None:
                    continue

                geom_for_target = geom
                lon, lat = absolute_lonlat(rel_lon, rel_lat, (origin_lon, origin_lat))
                dia_km = float(dia_m) / 1000.0

                insert_cursor.insertRow([geom_for_target, dia_km, lon, lat, tag_value])
                inserted += 1
                rows_for_csv.append([oid, dia_km, lon, lat, tag_value, score])

    ensure_dir(os.path.dirname(summary_csv))
    with open(summary_csv, "wb") as f:
        writer = csv.writer(f)
        writer.writerow(["detected_oid", "diam_km", "x_coord", "y_coord", "tag", "score"])
        writer.writerows(rows_for_csv)

    print("Inserted %s detected crater rows into: %s" % (inserted, target_shp))
    return inserted


def check_model_python(model_python, model_dir):
    helper = os.path.join(here(), "run_wangyiran_model_py3.py")
    cmd = [model_python, helper, "--version-check"]
    ret = subprocess_call(cmd)
    if ret != 0:
        raise RuntimeError("Python 3 model helper check failed. Set --model-python to the model Python 3 executable.")
    cmd = [model_python, helper, "--dependency-check", "--model-dir", model_dir]
    ret = subprocess_call(cmd)
    if ret != 0:
        raise RuntimeError("Python 3 cannot import wangyiranCode dependencies. Use the Python 3 environment that runs the model.")


def run_check(args, work_dir):
    print("Checking ArcPy environment...")
    print("  Python executable: %s" % sys.executable)
    print("  ArcPy version: %s" % arcpy.GetInstallInfo().get("Version"))
    require_path(args.area_shp, "AREA shapefile")
    require_path(args.image_tif, "Input raster")
    require_path(args.target_shp, "Target CRATER shapefile")
    require_path(args.model_dir, "Model folder")
    require_path(os.path.join(args.model_dir, "predict_onnx.py"), "predict_onnx.py")
    require_path(os.path.join(args.model_dir, "model_data", "moon", "weights", "moon.onnx"), "Moon ONNX model")
    require_field(args.target_shp, "diam_km")
    require_field(args.target_shp, "x_coord")
    require_field(args.target_shp, "y_coord")
    require_field(args.target_shp, "tag")
    print("Checking Python 3 model helper...")
    check_model_python(args.model_python, args.model_dir)
    print("Check passed.")
    print("  work dir will be: %s" % work_dir)


def main():
    args = parse_args()
    args.area_shp = as_text(args.area_shp)
    args.image_tif = as_text(args.image_tif)
    args.target_shp = as_text(args.target_shp)
    args.model_dir = as_text(args.model_dir)
    args.model_python = as_text(args.model_python)

    work_dir = as_text(args.work_dir) if args.work_dir else os.path.join(infer_sample_root(args.image_tif), "data_auto")
    clip_dir = os.path.join(work_dir, "clip")
    model_out_dir = os.path.join(work_dir, "model_output")
    summary_csv = os.path.join(work_dir, "appended_craters.csv")

    if args.check_only:
        run_check(args, work_dir)
        return

    require_path(args.area_shp, "AREA shapefile")
    require_path(args.image_tif, "Input raster")
    require_path(args.target_shp, "Target CRATER shapefile")
    ensure_dir(work_dir)

    if not args.no_backup:
        backup_path = backup_target_shapefile(args.target_shp, work_dir)
        print("Backed up target shapefile to: %s" % backup_path)

    clipped_tif = clip_raster_by_mask(args.image_tif, args.area_shp, clip_dir, args.overwrite)
    detected_shp = run_model_python3(args.model_python, args.model_dir, clipped_tif, model_out_dir, args.overwrite)
    raster_sr = arcpy.Describe(args.image_tif).spatialReference
    projected_detected_shp = prepare_detected_for_target(
        detected_shp,
        args.model_dir,
        raster_sr,
        model_out_dir,
        args.overwrite,
    )
    tile_origin = parse_tile_origin_lonlat(args.image_tif)
    inserted = append_detected_to_target(
        projected_detected_shp,
        args.target_shp,
        tile_origin,
        args.tag,
        args.replace_tag,
        summary_csv,
    )

    print("Done.")
    print("  clipped raster: %s" % clipped_tif)
    print("  detected shp:   %s" % detected_shp)
    print("  projected shp:  %s" % projected_detected_shp)
    print("  summary csv:    %s" % summary_csv)
    print("  inserted rows:  %s" % inserted)


if __name__ == "__main__":
    main()
