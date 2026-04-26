"""
Smart Space Pulse — IoT Rule Setup

Wires an AWS IoT Core Topic Rule to the cloud-inference Lambda:

  Rule SQL: SELECT *, topic() AS mqtt_topic FROM 'ssp/+/telemetry'
  Action:   invoke `ssp-inference` Lambda

Also grants the rule permission to invoke the Lambda. Both the rule and the
permission are written idempotently — re-running replaces the rule and tolerates
a pre-existing permission statement.

Usage:
    python -m cloud.setup_iot_rule
    python -m cloud.setup_iot_rule --rule-name ssp_telemetry_to_lambda
"""
import argparse
import logging
import os

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("setup_iot_rule")

DEFAULT_RULE_NAME     = "ssp_telemetry_to_lambda"
DEFAULT_FUNCTION_NAME = "ssp-inference"
DEFAULT_TOPIC_FILTER  = "ssp/+/telemetry"
DEFAULT_SQL_VERSION   = "2016-03-23"
PERMISSION_SID        = "ssp-iot-rule-invoke"


def build_sql(topic_filter: str) -> str:
    return f"SELECT *, topic() AS mqtt_topic FROM '{topic_filter}'"


def upsert_rule(iot_client, rule_name: str, sql: str, lambda_arn: str) -> None:
    """Create the rule, or replace it in place if a rule by that name exists."""
    payload = {
        "sql": sql,
        "description": "Smart Space Pulse — telemetry → cloud-inference Lambda",
        "ruleDisabled": False,
        "awsIotSqlVersion": DEFAULT_SQL_VERSION,
        "actions": [{"lambda": {"functionArn": lambda_arn}}],
    }
    try:
        iot_client.create_topic_rule(ruleName=rule_name, topicRulePayload=payload)
        logger.info("Created rule %s", rule_name)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceAlreadyExistsException":
            raise
        logger.info("Rule %s exists — replacing in place", rule_name)
        iot_client.replace_topic_rule(ruleName=rule_name, topicRulePayload=payload)


def grant_invoke_permission(lam, function_name: str, rule_arn: str) -> None:
    try:
        lam.add_permission(
            FunctionName=function_name,
            StatementId=PERMISSION_SID,
            Action="lambda:InvokeFunction",
            Principal="iot.amazonaws.com",
            SourceArn=rule_arn,
        )
        logger.info("Granted iot.amazonaws.com -> %s invoke permission", function_name)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceConflictException":
            logger.info("Permission %s already present — skipping", PERMISSION_SID)
            return
        raise


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--region",        default=os.getenv("AWS_REGION", "us-east-1"))
    p.add_argument("--rule-name",     default=DEFAULT_RULE_NAME)
    p.add_argument("--function-name", default=DEFAULT_FUNCTION_NAME)
    p.add_argument("--topic-filter",  default=DEFAULT_TOPIC_FILTER)
    args = p.parse_args()

    sts     = boto3.client("sts", region_name=args.region)
    account = sts.get_caller_identity()["Account"]

    lam = boto3.client("lambda", region_name=args.region)
    lambda_arn = lam.get_function(FunctionName=args.function_name)["Configuration"]["FunctionArn"]

    iot = boto3.client("iot", region_name=args.region)
    rule_arn = f"arn:aws:iot:{args.region}:{account}:rule/{args.rule_name}"

    sql = build_sql(args.topic_filter)
    logger.info("Rule SQL: %s", sql)

    upsert_rule(iot, args.rule_name, sql, lambda_arn)
    grant_invoke_permission(lam, args.function_name, rule_arn)

    logger.info("IoT rule %s wired to %s", rule_arn, lambda_arn)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.000Z [%(levelname)-5s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    main()
