"""
Smart Space Pulse — DynamoDB Table Setup

Idempotently creates the two DynamoDB tables used by the cloud pipeline and
enables TTL on the telemetry table. Safe to re-run; existing tables are left
alone.

Usage:
    python -m cloud.setup_tables
    python -m cloud.setup_tables --region us-west-2
"""
import argparse
import logging
import os

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("setup_tables")

DEFAULT_REGION          = "us-east-1"
DEFAULT_TELEMETRY_TABLE = "ssp-telemetry"
DEFAULT_STATE_TABLE     = "ssp-state"
TTL_ATTRIBUTE           = "expire_at"


def _create(client, **kwargs) -> bool:
    """Create a table; return True if newly created, False if it already existed."""
    try:
        client.create_table(**kwargs)
        logger.info("Created table %s", kwargs["TableName"])
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            logger.info("Table %s already exists — skipping create", kwargs["TableName"])
            return False
        raise


def create_telemetry_table(client, name: str) -> bool:
    return _create(
        client,
        TableName=name,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "location_id", "AttributeType": "S"},
            {"AttributeName": "ts_utc",      "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "location_id", "KeyType": "HASH"},
            {"AttributeName": "ts_utc",      "KeyType": "RANGE"},
        ],
    )


def create_state_table(client, name: str) -> bool:
    return _create(
        client,
        TableName=name,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": "location_id", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "location_id", "KeyType": "HASH"}],
    )


def wait_active(client, name: str) -> None:
    client.get_waiter("table_exists").wait(TableName=name)


def enable_ttl(client, name: str, attribute: str = TTL_ATTRIBUTE) -> None:
    desc = client.describe_time_to_live(TableName=name)
    status = desc["TimeToLiveDescription"]["TimeToLiveStatus"]
    if status in ("ENABLED", "ENABLING"):
        logger.info("TTL already %s on %s", status.lower(), name)
        return
    client.update_time_to_live(
        TableName=name,
        TimeToLiveSpecification={"Enabled": True, "AttributeName": attribute},
    )
    logger.info("Enabled TTL on %s (attribute=%s)", name, attribute)


def main():
    parser = argparse.ArgumentParser(description="Create DynamoDB tables for Smart Space Pulse")
    parser.add_argument("--region",
                        default=os.getenv("AWS_REGION", DEFAULT_REGION))
    parser.add_argument("--telemetry-table",
                        default=os.getenv("DYNAMO_TELEMETRY_TABLE", DEFAULT_TELEMETRY_TABLE))
    parser.add_argument("--state-table",
                        default=os.getenv("DYNAMO_STATE_TABLE", DEFAULT_STATE_TABLE))
    args = parser.parse_args()

    client = boto3.client("dynamodb", region_name=args.region)

    create_telemetry_table(client, args.telemetry_table)
    create_state_table(client, args.state_table)

    wait_active(client, args.telemetry_table)
    wait_active(client, args.state_table)

    enable_ttl(client, args.telemetry_table)

    logger.info("All tables ready in region=%s", args.region)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.000Z [%(levelname)-5s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    main()
