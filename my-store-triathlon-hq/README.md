# Triathlon HQ

Personal Umbrel dashboard for Challenge Kaiserwinkl-Walchsee preparation.

## What it shows

- race countdown and current training phase
- readiness score from Garmin sleep, HRV, resting HR, stress, body battery, and weekly training load
- last-7-day swim / bike / run totals
- coach focus/gap detection
- latest health signals
- recent activities table
- `/api/summary` JSON endpoint for automation or future OpenClaw integrations

## InfluxDB

The app reads Garmin data from the existing Umbrel InfluxDB container over `umbrel_main_network`.
Defaults can be overridden in `docker-compose.yml`:

- `INFLUXDB_URL`
- `INFLUXDB_DATABASE`
- `INFLUXDB_USERNAME`
- `INFLUXDB_PASSWORD`

No public internet API is required at runtime.
