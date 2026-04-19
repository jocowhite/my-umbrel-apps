import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, render_template, request

try:
    import docker
except Exception:  # pragma: no cover
    docker = None


APP_DATA_DIR = Path(os.environ.get("APP_DATA_DIR", "/data"))
CONFIG_DIR = APP_DATA_DIR / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
ENV_FILE = CONFIG_DIR / "worker.env"
WORKER_CONTAINER_NAME = os.environ.get(
    "WORKER_CONTAINER_NAME", "my-store-garmin-sync_worker_1"
)

DEFAULTS = {
    "garmin_email": "",
    "garmin_base64_password": "",
    "garmin_is_cn": False,
    "influx_host": "influxdb_influxdb_1",
    "influx_port": "8086",
    "influx_username": "admin",
    "influx_password": "",
    "influx_database": "GarminStats",
    "update_interval_seconds": "300",
    "user_timezone": "",
    "log_level": "INFO",
    "fetch_selection": "",
}

app = Flask(__name__)


def load_settings():
    settings = dict(DEFAULTS)
    if SETTINGS_FILE.exists():
        settings.update(json.loads(SETTINGS_FILE.read_text()))
    return settings


def write_worker_env(settings):
    lines = [
        f"GARMINCONNECT_EMAIL={settings['garmin_email']}",
        f"GARMINCONNECT_BASE64_PASSWORD={settings['garmin_base64_password']}",
        f"GARMINCONNECT_IS_CN={'True' if settings['garmin_is_cn'] else 'False'}",
        f"INFLUXDB_HOST={settings['influx_host']}",
        f"INFLUXDB_PORT={settings['influx_port']}",
        f"INFLUXDB_USERNAME={settings['influx_username']}",
        f"INFLUXDB_PASSWORD={settings['influx_password']}",
        f"INFLUXDB_DATABASE={settings['influx_database']}",
        f"UPDATE_INTERVAL_SECONDS={settings['update_interval_seconds']}",
        f"LOG_LEVEL={settings['log_level']}",
    ]
    if settings["user_timezone"]:
        lines.append(f"USER_TIMEZONE={settings['user_timezone']}")
    if settings["fetch_selection"]:
        lines.append(f"FETCH_SELECTION={settings['fetch_selection']}")
    ENV_FILE.write_text("\n".join(lines) + "\n")


def restart_worker():
    if docker is None:
        return False, "Docker SDK not available in web service."
    try:
        client = docker.from_env()
        container = client.containers.get(WORKER_CONTAINER_NAME)
        container.restart(timeout=20)
        return True, f"Worker {WORKER_CONTAINER_NAME} restarted successfully."
    except Exception as exc:  # pragma: no cover
        return False, f"Saved settings, but could not restart worker: {exc}"


def get_worker_state():
    if docker is None:
        return "unknown"
    try:
        client = docker.from_env()
        container = client.containers.get(WORKER_CONTAINER_NAME)
        return container.status
    except Exception:
        return "not-created"


@app.route("/", methods=["GET", "POST"])
def index():
    settings = load_settings()
    status_message = None
    status_kind = "info"

    if request.method == "POST":
        garmin_password = request.form.get("garmin_password", "").strip()
        influx_password = request.form.get("influx_password", "").strip()
        existing_base64 = settings.get("garmin_base64_password", "")
        existing_influx_password = settings.get("influx_password", "")

        settings.update(
            {
                "garmin_email": request.form.get("garmin_email", "").strip(),
                "garmin_is_cn": request.form.get("garmin_is_cn") == "on",
                "influx_host": request.form.get("influx_host", "").strip()
                or DEFAULTS["influx_host"],
                "influx_port": request.form.get("influx_port", "").strip()
                or DEFAULTS["influx_port"],
                "influx_username": request.form.get("influx_username", "").strip()
                or DEFAULTS["influx_username"],
                "influx_password": influx_password or existing_influx_password,
                "influx_database": request.form.get("influx_database", "").strip()
                or DEFAULTS["influx_database"],
                "update_interval_seconds": request.form.get(
                    "update_interval_seconds", ""
                ).strip()
                or DEFAULTS["update_interval_seconds"],
                "user_timezone": request.form.get("user_timezone", "").strip(),
                "log_level": request.form.get("log_level", "").strip()
                or DEFAULTS["log_level"],
                "fetch_selection": request.form.get("fetch_selection", "").strip(),
            }
        )

        if garmin_password:
            settings["garmin_base64_password"] = base64.b64encode(
                garmin_password.encode("utf-8")
            ).decode("ascii")
        else:
            settings["garmin_base64_password"] = existing_base64

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        settings["updated_at"] = datetime.now(timezone.utc).isoformat()
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2) + "\n")
        write_worker_env(settings)

        ok, status_message = restart_worker()
        status_kind = "success" if ok else "warning"
        return render_template(
            "index.html",
            settings=settings,
            worker_state=get_worker_state(),
            status_message=status_message,
            status_kind=status_kind,
            has_password=bool(settings.get("garmin_base64_password")),
        )

    return render_template(
        "index.html",
        settings=settings,
        worker_state=get_worker_state(),
        status_message=status_message,
        status_kind=status_kind,
        has_password=bool(settings.get("garmin_base64_password")),
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
