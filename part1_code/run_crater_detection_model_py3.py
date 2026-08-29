# -*- coding: utf-8 -*-
"""
Python 3 helper for running crater_detect_model crater detection.

Do not run this with ArcMap Python 2.7. The ArcPy main script calls this helper
with a Python 3 interpreter because crater_detect_model uses Python 3 syntax.
"""

from __future__ import print_function

import argparse
import os
import shutil
import sys


LUNAR_MODEL_CONFIG = {
    "planet": "Moon",
    "radius": 1737400.0,
    "iou_threshold": 0.3,
    "model_path": os.path.join("model_data", "moon", "weights", "moon.onnx"),
    "conf_threshold": 0.286,
}

SHAPEFILE_SUFFIXES = [".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".qix", ".xml", ".txt", ".log"]


def parse_args():
    parser = argparse.ArgumentParser(description="Run crater_detect_model Moon crater detector.")
    parser.add_argument("--version-check", action="store_true", help="Only check this is Python 3.")
    parser.add_argument("--dependency-check", action="store_true", help="Check crater_detect_model imports in this Python 3.")
    parser.add_argument("--model-dir", default=None, help="crater_detect_model folder.")
    parser.add_argument("--image-tif", default=None, help="Input tif.")
    parser.add_argument("--output-dir", default=None, help="Output folder for detected shapefile.")
    parser.add_argument("--overwrite", action="store_true", help="Delete existing detector output first.")
    return parser.parse_args()


def require_path(path, label):
    if not path or not os.path.exists(path):
        raise RuntimeError("%s not found: %s" % (label, path))


def ensure_dir(path):
    if not os.path.isdir(path):
        os.makedirs(path)


def output_shp_path(image_tif, output_dir):
    stem = os.path.splitext(os.path.basename(image_tif))[0]
    return os.path.join(output_dir, stem + ".shp")


def remove_existing_output(image_tif, output_dir):
    shp_path = output_shp_path(image_tif, output_dir)
    base, _ = os.path.splitext(shp_path)
    for suffix in SHAPEFILE_SUFFIXES:
        candidate = base + suffix
        if os.path.exists(candidate):
            os.remove(candidate)


def copy_prj_from_image_sidecar_if_needed(image_tif, out_shp):
    # The main ArcPy script will Define Projection from the raster. This sidecar
    # copy is only a convenience when the helper is run by hand.
    image_prj = os.path.splitext(image_tif)[0] + ".prj"
    out_prj = os.path.splitext(out_shp)[0] + ".prj"
    if os.path.exists(image_prj) and not os.path.exists(out_prj):
        shutil.copy2(image_prj, out_prj)


def run_model(model_dir, image_tif, output_dir, overwrite):
    require_path(model_dir, "Model folder")
    require_path(os.path.join(model_dir, "predict_onnx.py"), "predict_onnx.py")
    require_path(os.path.join(model_dir, LUNAR_MODEL_CONFIG["model_path"]), "Moon ONNX model")
    require_path(image_tif, "Input tif")
    ensure_dir(output_dir)

    out_shp = output_shp_path(image_tif, output_dir)
    if os.path.exists(out_shp):
        if overwrite:
            remove_existing_output(image_tif, output_dir)
        else:
            print("Using existing model output: %s" % out_shp)
            return out_shp

    if model_dir not in sys.path:
        sys.path.insert(0, model_dir)

    old_cwd = os.getcwd()
    os.chdir(model_dir)
    try:
        from predict_onnx import predict_singletif
        from yolo import YOLO

        config = LUNAR_MODEL_CONFIG
        model_path = os.path.join(model_dir, config["model_path"])
        print("Loading Moon model: %s" % model_path)
        model = YOLO(model_path, config["conf_threshold"], config["iou_threshold"])
        print("Detecting craters in: %s" % image_tif)
        predict_singletif(
            "",
            model,
            image_tif,
            output_dir + os.sep,
            True,
            config["radius"],
            config["planet"],
        )
    finally:
        os.chdir(old_cwd)

    if not os.path.exists(out_shp):
        log_path = os.path.splitext(out_shp)[0] + ".log"
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                print(f.read())
        raise RuntimeError("Model did not create expected shapefile: %s" % out_shp)

    copy_prj_from_image_sidecar_if_needed(image_tif, out_shp)
    print("Wrote detected shapefile: %s" % out_shp)
    return out_shp


def dependency_check(model_dir):
    require_path(model_dir, "Model folder")
    require_path(os.path.join(model_dir, "predict_onnx.py"), "predict_onnx.py")
    require_path(os.path.join(model_dir, LUNAR_MODEL_CONFIG["model_path"]), "Moon ONNX model")

    if model_dir not in sys.path:
        sys.path.insert(0, model_dir)
    old_cwd = os.getcwd()
    os.chdir(model_dir)
    try:
        from predict_onnx import predict_singletif  # noqa: F401
        from yolo import YOLO  # noqa: F401
    finally:
        os.chdir(old_cwd)
    print("Model dependency check OK in: %s" % sys.executable)


def main():
    args = parse_args()
    if args.version_check:
        if sys.version_info[0] < 3:
            print("This helper must run with Python 3. Current: %s" % sys.version)
            return 2
        print("Python 3 helper OK: %s" % sys.executable)
        print("Python version: %s" % sys.version.replace("\n", " "))
        return 0

    if sys.version_info[0] < 3:
        print("This helper must run with Python 3. Current: %s" % sys.version)
        return 2

    if args.dependency_check:
        dependency_check(args.model_dir)
        return 0

    run_model(args.model_dir, args.image_tif, args.output_dir, args.overwrite)
    return 0


if __name__ == "__main__":
    sys.exit(main())