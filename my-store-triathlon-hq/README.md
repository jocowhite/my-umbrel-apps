# Health Dashboard

Personal Umbrel health dashboard for Garmin metrics from InfluxDB.

## What it shows

- Vita-style glass dashboard UI
- readiness score from Garmin sleep, HRV, resting HR, stress, body battery, and weekly training load
- sleep score, duration, and sleep stages
- HRV trend, resting heart rate, steps, active minutes, and recovery factors
- Garmin Index Scale body composition: weight, BMI, body fat, body water, muscle mass, and bone mass
- `/api/summary` JSON endpoint for automation or future OpenClaw integrations

## InfluxDB

The app reads Garmin data from the existing Umbrel InfluxDB container over `umbrel_main_network`.
Defaults can be overridden in `docker-compose.yml`:

- `INFLUXDB_URL`
- `INFLUXDB_DATABASE`
- `INFLUXDB_USERNAME`
- `INFLUXDB_PASSWORD`

No public internet API is required at runtime.
