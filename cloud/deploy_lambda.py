"""
Smart Space Pulse — Lambda Deployer

Idempotently deploys the cloud-inference Lambda from the build artifact at
cloud/build/lambda.zip. Stages the zip in S3 (because it exceeds the 50 MB
direct-upload limit), then creates or updates the function in place.

Defaults are tuned for AWS Academy / Learner Lab:
  - role-arn: arn:aws:iam::<account>:role/LabRole
  - bucket:   ssp-lambda-<account>

Usage:
    python -m cloud.deploy_lambda
    python -m cloud.deploy_lambda --region us-west-2 --function-name ssp-inference
"""
import argparse
import logging
import os
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("deploy_lambda")

ROOT     = Path(__file__).resolve().parent.parent
ZIP_PATH = ROOT / "cloud" / "build" / "lambda.zip"

DEFAULT_FUNCTION_NAME = "ssp-inference"
DEFAULT_RUNTIME       = "python3.12"
DEFAULT_HANDLER       = "lambda_handler.lambda_handler"
DEFAULT_TIMEOUT       = 15
DEFAULT_MEMORY        = 512
CODE_KEY              = "lambda.zip"


def ensure_bucket(s3, bucket: str, region: str) -> None:
    try:
        s3.head_bucket(Bucket=bucket)
        logger.info("Using existing bucket %s", bucket)
        return
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code not in ("404", "NoSuchBucket", "NotFound"):
            raise
    logger.info("Creating bucket %s in %s", bucket, region)
    kwargs = {"Bucket": bucket}
    if region != "us-east-1":
        kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
    s3.create_bucket(**kwargs)


def upload_zip(s3, bucket: str, key: str, zip_path: Path) -> None:
    logger.info("Uploading %s (%.1f MB) -> s3://%s/%s",
                zip_path, zip_path.stat().st_size / 1e6, bucket, key)
    s3.upload_file(str(zip_path), bucket, key)


def deploy_function(lam, *, name, role_arn, bucket, key, runtime, handler,
                    timeout, memory, env):
    try:
        lam.get_function(FunctionName=name)
        logger.info("Function %s exists — updating", name)
        lam.update_function_code(
            FunctionName=name, S3Bucket=bucket, S3Key=key, Publish=True,
        )
        lam.get_waiter("function_updated").wait(FunctionName=name)
        lam.update_function_configuration(
            FunctionName=name,
            Runtime=runtime,
            Role=role_arn,
            Handler=handler,
            Timeout=timeout,
            MemorySize=memory,
            Environment={"Variables": env},
        )
        lam.get_waiter("function_updated").wait(FunctionName=name)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        logger.info("Creating new function %s", name)
        lam.create_function(
            FunctionName=name,
            Runtime=runtime,
            Role=role_arn,
            Handler=handler,
            Code={"S3Bucket": bucket, "S3Key": key},
            Timeout=timeout,
            MemorySize=memory,
            Environment={"Variables": env},
            Publish=True,
        )
        lam.get_waiter("function_active").wait(FunctionName=name)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--region",          default=os.getenv("AWS_REGION", "us-east-1"))
    p.add_argument("--function-name",   default=DEFAULT_FUNCTION_NAME)
    p.add_argument("--role-arn",        default=None,
                   help="IAM role ARN (default: arn:aws:iam::<account>:role/LabRole)")
    p.add_argument("--bucket",          default=None,
                   help="S3 staging bucket (default: ssp-lambda-<account>)")
    p.add_argument("--telemetry-table", default=os.getenv("DYNAMO_TELEMETRY_TABLE", "ssp-telemetry"))
    p.add_argument("--state-table",     default=os.getenv("DYNAMO_STATE_TABLE", "ssp-state"))
    args = p.parse_args()

    if not ZIP_PATH.exists():
        raise SystemExit(
            f"Build artifact not found: {ZIP_PATH}\n"
            "Run `python -m cloud.build_lambda` first."
        )

    sts     = boto3.client("sts", region_name=args.region)
    account = sts.get_caller_identity()["Account"]
    role_arn = args.role_arn or f"arn:aws:iam::{account}:role/LabRole"
    bucket   = args.bucket   or f"ssp-lambda-{account}"

    logger.info("Account=%s region=%s function=%s role=%s",
                account, args.region, args.function_name, role_arn)

    s3 = boto3.client("s3", region_name=args.region)
    ensure_bucket(s3, bucket, args.region)
    upload_zip(s3, bucket, CODE_KEY, ZIP_PATH)

    lam = boto3.client("lambda", region_name=args.region)
    deploy_function(
        lam,
        name=args.function_name,
        role_arn=role_arn,
        bucket=bucket,
        key=CODE_KEY,
        runtime=DEFAULT_RUNTIME,
        handler=DEFAULT_HANDLER,
        timeout=DEFAULT_TIMEOUT,
        memory=DEFAULT_MEMORY,
        env={
            "DYNAMO_TELEMETRY_TABLE": args.telemetry_table,
            "DYNAMO_STATE_TABLE":     args.state_table,
            "LOGISTIC_MODEL_PATH":    "/var/task/logistic_model.joblib",
        },
    )

    fn_arn = lam.get_function(FunctionName=args.function_name)["Configuration"]["FunctionArn"]
    logger.info("Lambda deployed: %s", fn_arn)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.000Z [%(levelname)-5s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    main()
