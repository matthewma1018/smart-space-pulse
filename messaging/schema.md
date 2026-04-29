# Smart Space Pulse — MQTT Schema

## Topic Hierarchy

```
ssp/                              # Smart Space Pulse root
  {location_id}/                  # e.g. "library-1f", "lounge-jfk-b"
    telemetry                     # 1 Hz sensor summaries  (QoS 1, retain=false)
    heartbeat                     # device liveness ping    (QoS 0, retain=false)
```

State transitions are not published as MQTT messages in the final version;
they are written directly to DynamoDB by the inference Lambda and to SQLite
by `processing/windower.py`. The dashboard reads state from those stores.

## Telemetry Payload (`ssp/{location_id}/telemetry`)

Published every 1 second. QoS 1, retain=false.

```json
{
  "device_id":   "Core2Kit",
  "location_id": "library-1f",
  "ts_utc":      "2026-04-17T14:23:01.000Z",
  "spl_db":      61.4,
  "seq":         4201
}
```

| Field | Type | Constraints |
|-------|------|-------------|
| device_id | string | Format: `Core2Kit` followed by optional alphanumeric suffix |
| location_id | string | Non-empty |
| ts_utc | string | ISO 8601 UTC with `Z` suffix |
| spl_db | float | Non-null, ≥ 0 |
| seq | integer | Non-null, monotonic per device |

## Heartbeat Payload (`ssp/{location_id}/heartbeat`)

Published every 30 seconds. QoS 0, retain=false.

```json
{
  "device_id":   "Core2Kit",
  "location_id": "library-1f",
  "ts_utc":      "2026-04-17T14:25:00.000Z",
  "uptime_sec":  3600,
  "rssi_dbm":    -58
}
```

| Field | Type | Constraints |
|-------|------|-------------|
| uptime_sec | integer | Seconds since device boot, ≥ 0 |
| rssi_dbm | integer | WiFi RSSI in dBm; typical range -30 (excellent) to -90 (marginal). `0` if unavailable. |
