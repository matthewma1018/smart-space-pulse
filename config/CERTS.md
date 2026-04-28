# Certificates & Credentials — Operational Guide

This doc covers **rotation, expiry, and incident response** for the AWS
credentials used by Smart Space Pulse. Initial cert/Thing setup is covered in
class — only file paths and project-specific concerns appear here.

## What lives where

`config/certs/` (gitignored — never commit):

| File | Role |
|------|------|
| `AmazonRootCA1.pem` | Verifies the AWS IoT broker's server cert |
| `certificate.pem.crt` | Client certificate the bridge presents |
| `private.pem.key` | Client private key |

`.env` wires them up:

```
MQTT_HOST=<endpoint>-ats.iot.us-east-1.amazonaws.com
MQTT_PORT=8883
MQTT_USE_TLS=true
MQTT_CA_CERT=config/certs/AmazonRootCA1.pem
MQTT_CLIENT_CERT=config/certs/certificate.pem.crt
MQTT_CLIENT_KEY=config/certs/private.pem.key
```

The IoT policy attached to the cert must wildcard `Core2Kit*` so both the
on-device client (`Core2Kit`) and the bridge (`Core2Kit-bridge`) authenticate
with the same cert. Sample policy: `config/iam_policy_sample.json`.

## Rotating a certificate

Rotation is a swap, not an in-place update:

1. Create a new cert for the same Thing in the AWS console; mark Active;
   attach to the Thing; attach the policy.
2. Replace `config/certs/certificate.pem.crt` and `private.pem.key` with the
   new files. The Root CA does not change.
3. Restart the bridge. Confirm `[INFO ] Connected to AWS IoT Core …`.
4. Revoke the old cert: IoT Core → Security → Certificates → old cert →
   Deactivate → Revoke. Detach from the Thing.

Rotate at least annually, or immediately on suspected leak.

## AWS Academy session-token expiry

The Lambda deploy scripts and the dashboard's DynamoDB probe use boto3, which
authenticates with **temporary session credentials that expire every few
hours** in AWS Academy. The IoT cert path is independent — it stays valid
across token refreshes.

| Symptom | Cause |
|---------|-------|
| Dashboard shows yellow `☁️ Cloud unreachable` banner | DynamoDB scan returned `ExpiredTokenException` |
| `python -m cloud.deploy_lambda` fails with `ExpiredToken` | boto3 can't reach Lambda/S3 |
| `live_bridge.py` still connects to AWS IoT Core normally | IoT certs are signed once; not affected by IAM session creds |

To refresh:

1. AWS Academy → Modules → Learner Lab → "AWS Details" → "AWS CLI" → Show.
2. Copy `aws_access_key_id`, `aws_secret_access_key`, `aws_session_token` into
   `~/.aws/credentials` under `[default]`, replacing whatever's there.
3. No restart needed — boto3 re-reads on every call. The dashboard banner
   clears on the next refresh tick.

## Troubleshooting

**`SSLCertVerificationError` on bridge connect**
Wrong Root CA or wrong endpoint. AWS IoT endpoints look like
`xxxxxxxx-ats.iot.<region>.amazonaws.com` — confirm the `-ats` suffix.

**`Connection refused (rc=5)` from paho**
Cert is active but the policy doesn't allow `iot:Connect` for this client ID.
The policy must wildcard `Core2Kit*`.

**`AccessDenied` from Lambda invoke**
The lab role doesn't have `lambda:InvokeFunction`. Confirm with your instructor
which actions are scoped to your Academy role.

**`The security token included in the request is expired`**
Session creds expired — refresh from the Learner Lab (see above).
