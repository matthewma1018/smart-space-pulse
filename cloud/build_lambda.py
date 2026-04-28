"""
Smart Space Pulse — Lambda Deployment Package Builder

Builds a self-contained zip for the cloud-inference Lambda:

  - cloud/lambda_handler.py    (entry point)
  - logistic_model.joblib      (trained model, bundled at the package root)
  - sklearn / scipy / numpy / joblib / threadpoolctl  (Linux x86_64 wheels)

boto3 is intentionally NOT bundled because the Lambda Python runtime ships
with it. We pin to manylinux wheels so the build runs on Windows / macOS but
produces Linux-compatible binaries.

Output: cloud/build/lambda.zip

Usage:
    python -m cloud.build_lambda
    python -m cloud.build_lambda --python-version 3.12
"""
import argparse
import logging
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

logger = logging.getLogger("build_lambda")

ROOT       = Path(__file__).resolve().parent.parent
BUILD_DIR  = ROOT / "cloud" / "build"
STAGE_DIR  = BUILD_DIR / "stage"
ZIP_PATH   = BUILD_DIR / "lambda.zip"
HANDLER    = ROOT / "cloud" / "lambda_handler.py"
MODEL_FILE = ROOT / "processing" / "model" / "logistic_model.joblib"

DEPS = [
    "scikit-learn",
    "scipy",
    "numpy",
    "joblib",
    "threadpoolctl",
]


def _clean():
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    STAGE_DIR.mkdir(parents=True)


def _pip_install(python_version: str):
    cmd = [
        sys.executable, "-m", "pip", "install",
        "--target", str(STAGE_DIR),
        "--platform", "manylinux2014_x86_64",
        "--python-version", python_version,
        "--implementation", "cp",
        "--only-binary", ":all:",
        "--upgrade",
        *DEPS,
    ]
    logger.info("Installing deps for Linux/python%s into %s", python_version, STAGE_DIR)
    subprocess.run(cmd, check=True)


def _copy_handler_and_model():
    shutil.copy2(HANDLER, STAGE_DIR / "lambda_handler.py")
    if MODEL_FILE.exists():
        shutil.copy2(MODEL_FILE, STAGE_DIR / "logistic_model.joblib")
        logger.info("Bundled logistic model (%d KB)", MODEL_FILE.stat().st_size // 1024)
    else:
        logger.warning("No logistic model at %s — handler will fall back to rule-based",
                        MODEL_FILE)


def _zip_stage():
    logger.info("Zipping %s -> %s", STAGE_DIR, ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        for path in STAGE_DIR.rglob("*"):
            if path.is_file():
                z.write(path, arcname=path.relative_to(STAGE_DIR))
    logger.info("Lambda zip ready: %s (%.1f MB)", ZIP_PATH, ZIP_PATH.stat().st_size / 1e6)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--python-version", default="3.12",
                   help="Lambda runtime Python version (must match the function's runtime)")
    args = p.parse_args()

    _clean()
    _pip_install(args.python_version)
    _copy_handler_and_model()
    _zip_stage()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.000Z [%(levelname)-5s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    main()
