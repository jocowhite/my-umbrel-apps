#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="/data/config/worker.env"
TOKEN_DIR="/data/garminconnect"

mkdir -p "${TOKEN_DIR}"

load_config() {
  if [ -f "${ENV_FILE}" ]; then
    set -a
    # shellcheck disable=SC1090
    . "${ENV_FILE}"
    set +a
  fi
}

is_ready() {
  [ -n "${GARMINCONNECT_EMAIL:-}" ] \
    && [ -n "${GARMINCONNECT_BASE64_PASSWORD:-}" ] \
    && [ -n "${INFLUXDB_PASSWORD:-}" ]
}

while true; do
  load_config
  if is_ready; then
    break
  fi
  echo "Garmin worker waiting for saved settings in ${ENV_FILE}"
  sleep 20
done

export GARMINCONNECT_IS_CN="${GARMINCONNECT_IS_CN:-False}"
export INFLUXDB_HOST="${INFLUXDB_HOST:-influxdb_influxdb_1}"
export INFLUXDB_PORT="${INFLUXDB_PORT:-8086}"
export INFLUXDB_USERNAME="${INFLUXDB_USERNAME:-admin}"
export INFLUXDB_DATABASE="${INFLUXDB_DATABASE:-GarminStats}"
export UPDATE_INTERVAL_SECONDS="${UPDATE_INTERVAL_SECONDS:-300}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"

cd /app
exec python garmin_grafana/garmin_fetch.py
