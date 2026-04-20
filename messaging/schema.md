# Smart Space Pulse — MQTT Schema

## Topic Hierarchy

```
ssp/                              # Smart Space Pulse root
  {location_id}/                  # e.g. "library-1f", "lounge-jfk-b"
    telemetry                     # 1 Hz sensor summaries  (QoS 1, retain=false)
    state                         # occupancy state changes (QoS 1, retain=true)
    alert                         # threshold breach alerts (QoS 1, retain=false)
    heartbeat                     # device liveness ping    (QoS 0, retain=false)
```

## Telemetry Payload (`ssp/{location_id}/telemetry`)

Published every 1 second. QoS 1, retain=false.

```json
{
  "device_id":   "core2-a1b2",
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

## State-Change Payload (`ssp/{location_id}/state`)

Published on state transitions only. QoS 1, retain=true.

```json
{
  "device_id":   "core2-a1b2",
  "location_id": "library-1f",
  "ts_utc":      "2026-04-17T14:23:30.000Z",
  "score":       67,
  "state":       "suitable",
  "prev_state":  "not_suitable",
  "window_sec":  30
}
```

| Field | Type | Constraints |
|-------|------|-------------|
| state | string | One of: `suitable`, `not_suitable`, `transitioning` |
| score | float | 0–100 |
| prev_state | string | One of: `suitable`, `not_suitable`, `transitioning` |
| window_sec | integer | Window size in seconds |

## Alert Payload (`ssp/{location_id}/alert`)

Published on threshold breaches. QoS 1, retain=false.

```json
{
  "device_id":    "core2-a1b2",
  "location_id":  "library-1f",
  "ts_utc":       "2026-04-17T14:25:00.000Z",
  "alert_type":   "noise_spike",
  "spl_db":       88.2,
  "threshold_db": 75.0
}
```

## Heartbeat Payload (`ssp/{location_id}/heartbeat`)

Published every 30 seconds. QoS 0, retain=false.

```json
{
  "device_id":   "core2-a1b2",
  "location_id": "library-1f",
  "ts_utc":      "2026-04-17T14:25:00.000Z",
  "uptime_sec":  3600
}
```
