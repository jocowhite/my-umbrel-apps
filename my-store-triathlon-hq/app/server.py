#!/usr/bin/env python3
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode, urlparse
import html
import json
import os
import statistics
import time
import urllib.error
import urllib.request

RACE_NAME = os.getenv("RACE_NAME", "Challenge Kaiserwinkl-Walchsee")
RACE_DATE = os.getenv("RACE_DATE", "2026-06-28")
RACE_DISTANCE = os.getenv("RACE_DISTANCE", "1.9 km swim · 90 km bike · 21.1 km run")
BIKE_ELEVATION = os.getenv("BIKE_ELEVATION", "1100 m climbing")
INFLUX_URL = os.getenv("INFLUXDB_URL", "http://influxdb_influxdb_1:8086")
INFLUX_DB = os.getenv("INFLUXDB_DATABASE", "GarminStats")
INFLUX_USER = os.getenv("INFLUXDB_USERNAME", "openclaw")
INFLUX_PASSWORD = os.getenv("INFLUXDB_PASSWORD", "openclaw")
CACHE_SECONDS = int(os.getenv("CACHE_SECONDS", "180"))

CACHE = {"ts": 0.0, "data": None}

SPORTS = {
    "swim": {"label": "Swim", "types": {"lap_swimming", "open_water_swimming", "swimming"}, "target_sessions": 2, "target_hours": 1.5},
    "bike": {"label": "Bike", "types": {"cycling", "road_biking", "mountain_biking", "gravel_cycling"}, "target_sessions": 3, "target_hours": 5.0},
    "run": {"label": "Run", "types": {"running", "trail_running", "treadmill_running"}, "target_sessions": 3, "target_hours": 2.5},
}


def influx_query(query: str, timeout: float = 6.0) -> dict:
    params = {"db": INFLUX_DB, "q": query}
    if INFLUX_USER:
        params["u"] = INFLUX_USER
    if INFLUX_PASSWORD:
        params["p"] = INFLUX_PASSWORD
    url = f"{INFLUX_URL.rstrip('/')}/query?{urlencode(params)}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def first_series(data: dict) -> tuple[list[str], list[list]]:
    try:
        series = data["results"][0].get("series", [])[0]
        return series.get("columns", []), series.get("values", [])
    except Exception:
        return [], []


def rows(query: str) -> list[dict]:
    cols, vals = first_series(influx_query(query))
    return [dict(zip(cols, row)) for row in vals]


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def sport_key(activity_type: str | None) -> str | None:
    value = (activity_type or "").lower()
    for key, spec in SPORTS.items():
        if value in spec["types"]:
            return key
    return None


def km(meters: float | int | None) -> float:
    return round((meters or 0) / 1000, 1)


def hours(seconds: float | int | None) -> float:
    return round((seconds or 0) / 3600, 1)


def pace_for_run(distance_m: float, moving_s: float) -> str:
    if not distance_m or not moving_s:
        return "—"
    minutes_per_km = moving_s / 60 / (distance_m / 1000)
    m = int(minutes_per_km)
    s = int(round((minutes_per_km - m) * 60))
    return f"{m}:{s:02d}/km"


def speed_kmh(distance_m: float, moving_s: float) -> str:
    if not distance_m or not moving_s:
        return "—"
    return f"{distance_m / 1000 / (moving_s / 3600):.1f} km/h"


def kg(value: float | int | None) -> float | None:
    if value is None:
        return None
    value = float(value)
    return round(value / 1000, 1) if value > 300 else round(value, 1)


def hm(seconds: float | int | None) -> str:
    if not seconds:
        return "—"
    minutes = int(round(float(seconds) / 60))
    return f"{minutes // 60}h {minutes % 60:02d}m"


def de_date(dt: datetime | None) -> str:
    if not dt:
        return "Heute"
    days = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
    months = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
    return f"{days[dt.weekday()]}, {dt.day}. {months[dt.month - 1]}"


def race_days_left() -> int | None:
    try:
        return (date.fromisoformat(RACE_DATE) - date.today()).days
    except Exception:
        return None


def readiness_score(latest_daily: dict | None, latest_sleep: dict | None, week_hours: float) -> tuple[int, str, list[str]]:
    score = 72
    reasons: list[str] = []
    if latest_sleep:
        sleep_score = latest_sleep.get("sleepScore")
        hrv = latest_sleep.get("avgOvernightHrv")
        rhr = latest_sleep.get("restingHeartRate")
        if sleep_score is not None:
            if sleep_score >= 80:
                score += 8; reasons.append("good sleep score")
            elif sleep_score < 65:
                score -= 12; reasons.append("sleep was weak")
        if hrv is not None:
            if hrv >= 70:
                score += 7; reasons.append("HRV looks strong")
            elif hrv < 45:
                score -= 10; reasons.append("HRV is low")
        if rhr is not None:
            if rhr <= 44:
                score += 4; reasons.append("resting HR is calm")
            elif rhr >= 52:
                score -= 8; reasons.append("resting HR is elevated")
    if latest_daily:
        stress = latest_daily.get("stressPercentage")
        body_battery_low = latest_daily.get("bodyBatteryLowestValue")
        if stress is not None and stress > 28:
            score -= 6; reasons.append("stress was high yesterday")
        if body_battery_low is not None and body_battery_low < 25:
            score -= 5; reasons.append("body battery dipped low")
    if week_hours > 10:
        score -= 5; reasons.append("big training week already")
    elif week_hours < 3:
        score += 3; reasons.append("fresh enough for quality")
    score = max(0, min(100, score))
    if score >= 82:
        label = "Green light"
    elif score >= 65:
        label = "Train, but stay honest"
    elif score >= 50:
        label = "Easy day recommended"
    else:
        label = "Recovery first"
    return score, label, reasons[:4]


def build_summary() -> dict:
    since_14d = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    activity_rows = rows(
        'SELECT activityType, activityName, distance, movingDuration, elapsedDuration, averageHR, maxHR, '
        'elevationGain, calories FROM ActivitySummary '
        f"WHERE time >= '{since_14d}' AND activityType != 'No Activity' ORDER BY time DESC LIMIT 120"
    )
    latest_daily = (rows("SELECT * FROM DailyStats ORDER BY time DESC LIMIT 1") or [None])[0]
    latest_sleep = (rows("SELECT * FROM SleepSummary ORDER BY time DESC LIMIT 1") or [None])[0]
    daily_rows = rows("SELECT totalSteps, activeSeconds, restingHeartRate, stressPercentage, bodyBatteryAtWakeTime FROM DailyStats ORDER BY time DESC LIMIT 8")
    sleep_rows = rows(
        "SELECT sleepScore, sleepTimeSeconds, deepSleepSeconds, remSleepSeconds, lightSleepSeconds, "
        "awakeSleepSeconds, avgOvernightHrv, restingHeartRate FROM SleepSummary ORDER BY time DESC LIMIT 14"
    )
    body_rows = rows("SELECT weight, bmi, bodyFat, bodyWater, muscleMass, boneMass FROM BodyComposition ORDER BY time DESC LIMIT 2")
    vo2_rows = rows("SELECT * FROM VO2_Max ORDER BY time DESC LIMIT 20")

    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)
    last7 = []
    by_sport = {key: {"sessions": 0, "distance_km": 0.0, "hours": 0.0, "elevation_m": 0.0} for key in SPORTS}
    recent = []
    for r in activity_rows:
        t = parse_time(r.get("time"))
        key = sport_key(r.get("activityType"))
        if not key or not t:
            continue
        distance = float(r.get("distance") or 0)
        moving = float(r.get("movingDuration") or r.get("elapsedDuration") or 0)
        elev = float(r.get("elevationGain") or 0)
        item = {
            "time": t.strftime("%d %b %H:%M"),
            "sport": SPORTS[key]["label"],
            "name": r.get("activityName") or SPORTS[key]["label"],
            "distance_km": km(distance),
            "hours": hours(moving),
            "avg_hr": r.get("averageHR"),
            "pace_or_speed": pace_for_run(distance, moving) if key == "run" else speed_kmh(distance, moving),
        }
        if len(recent) < 7:
            recent.append(item)
        if t >= week_start:
            last7.append(r)
            by_sport[key]["sessions"] += 1
            by_sport[key]["distance_km"] += distance / 1000
            by_sport[key]["hours"] += moving / 3600
            by_sport[key]["elevation_m"] += elev

    for key in by_sport:
        for metric in ("distance_km", "hours", "elevation_m"):
            by_sport[key][metric] = round(by_sport[key][metric], 1)

    week_hours = round(sum(v["hours"] for v in by_sport.values()), 1)
    readiness, readiness_label, readiness_reasons = readiness_score(latest_daily, latest_sleep, week_hours)

    run_vo2 = next((r.get("VO2_max_value") for r in vo2_rows if r.get("VO2_max_value") is not None), None)
    bike_vo2 = next((r.get("VO2_max_value_cycling") for r in vo2_rows if r.get("VO2_max_value_cycling") is not None), None)
    latest_body = body_rows[0] if body_rows else {}
    previous_body = body_rows[1] if len(body_rows) > 1 else {}
    latest_daily_time = parse_time(latest_daily.get("time")) if latest_daily else None
    latest_sleep_time = parse_time(latest_sleep.get("time")) if latest_sleep else None
    latest_body_time = parse_time(latest_body.get("time")) if latest_body else None

    active_minutes = [round((r.get("activeSeconds") or 0) / 60) for r in reversed(daily_rows[:7])]
    hrv_values = [r.get("avgOvernightHrv") for r in reversed(sleep_rows) if r.get("avgOvernightHrv") is not None]
    steps = latest_daily.get("totalSteps") if latest_daily else None
    step_goal = 10000
    active_week = sum(active_minutes)
    weight = kg(latest_body.get("weight"))
    previous_weight = kg(previous_body.get("weight"))
    weight_delta = None if weight is None or previous_weight is None else round(weight - previous_weight, 1)

    gaps = []
    if by_sport["swim"]["sessions"] < SPORTS["swim"]["target_sessions"]:
        gaps.append("Swim frequency is the main opportunity this week.")
    if by_sport["bike"]["hours"] < 3.5:
        gaps.append("Add bike volume/climbing if recovery is good.")
    if by_sport["run"]["sessions"] == 0:
        gaps.append("Add an easy run or brick run to keep rhythm.")
    if not gaps:
        gaps.append("Nice balance this week — protect recovery and execute calmly.")

    days_left = race_days_left()
    if days_left is None:
        phase = "Configure race date"
    elif days_left <= 0:
        phase = "Post-race review"
    elif days_left <= 14:
        phase = "Taper"
    elif days_left <= 42:
        phase = "Race-specific build"
    else:
        phase = "Build consistency"

    return {
        "ok": True,
        "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "race": {"name": RACE_NAME, "date": RACE_DATE, "distance": RACE_DISTANCE, "bike_elevation": BIKE_ELEVATION, "days_left": days_left, "phase": phase},
        "readiness": {"score": readiness, "label": readiness_label, "reasons": readiness_reasons},
        "week": {"hours": week_hours, "sports": by_sport, "gaps": gaps},
        "health": {
            "date_label": de_date(latest_daily_time or now),
            "steps": steps,
            "step_goal": step_goal,
            "step_pct": pct(steps or 0, step_goal),
            "active_minutes_week": active_week,
            "active_minutes_days": active_minutes,
            "sleep_score": None if not latest_sleep else latest_sleep.get("sleepScore"),
            "sleep_hours": None if not latest_sleep else round((latest_sleep.get("sleepTimeSeconds") or 0) / 3600, 1),
            "sleep_duration": None if not latest_sleep else hm(latest_sleep.get("sleepTimeSeconds")),
            "deep_sleep": None if not latest_sleep else hm(latest_sleep.get("deepSleepSeconds")),
            "rem_sleep": None if not latest_sleep else hm(latest_sleep.get("remSleepSeconds")),
            "light_sleep": None if not latest_sleep else hm(latest_sleep.get("lightSleepSeconds")),
            "awake_sleep": None if not latest_sleep else hm(latest_sleep.get("awakeSleepSeconds")),
            "sleep_time": latest_sleep_time.strftime("%d.%m. %H:%M") if latest_sleep_time else None,
            "hrv": None if not latest_sleep else latest_sleep.get("avgOvernightHrv"),
            "hrv_values": hrv_values,
            "resting_hr": None if not latest_sleep else latest_sleep.get("restingHeartRate"),
            "body_battery_wake": None if not latest_daily else latest_daily.get("bodyBatteryAtWakeTime"),
            "stress": None if not latest_daily else latest_daily.get("stressPercentage"),
            "weight": weight,
            "weight_delta": weight_delta,
            "bmi": None if not latest_body else latest_body.get("bmi"),
            "body_fat": None if not latest_body else latest_body.get("bodyFat"),
            "body_water": None if not latest_body else latest_body.get("bodyWater"),
            "muscle_mass": kg(latest_body.get("muscleMass")),
            "bone_mass": kg(latest_body.get("boneMass")),
            "body_time": latest_body_time.strftime("%d.%m. %H:%M") if latest_body_time else None,
            "vo2_run": run_vo2,
            "vo2_bike": bike_vo2,
        },
        "recent": recent,
        "influx": {"url": INFLUX_URL, "database": INFLUX_DB},
    }


def get_summary() -> dict:
    now = time.time()
    if CACHE["data"] and now - CACHE["ts"] < CACHE_SECONDS:
        return CACHE["data"]
    try:
        data = build_summary()
    except Exception as exc:
        data = {"ok": False, "error": str(exc), "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "influx": {"url": INFLUX_URL, "database": INFLUX_DB}}
    CACHE["ts"] = now
    CACHE["data"] = data
    return data


def fmt(value, suffix="", empty="—"):
    if value is None:
        return empty
    return f"{value}{suffix}"


def pct(value: float, target: float) -> int:
    if target <= 0:
        return 0
    return max(0, min(100, int(round(value / target * 100))))


def page(data: dict) -> bytes:
    if not data.get("ok"):
        return error_page(data)
    health = data["health"]
    readiness = data["readiness"]
    steps = health.get("steps") or 0
    step_pct = health.get("step_pct") or 0
    sleep_score = health.get("sleep_score") or 0
    recovery_score = readiness.get("score") or 0
    hrv_values = health.get("hrv_values") or []
    active_days = health.get("active_minutes_days") or []

    def de_num(value, digits=0, empty="—"):
        if value is None:
            return empty
        if digits:
            return f"{float(value):.{digits}f}".replace(".", ",")
        return f"{int(round(float(value))):,}".replace(",", ".")

    def signed(value, suffix=""):
        if value is None:
            return "neu"
        sign = "+" if value > 0 else ""
        return f"{sign}{str(value).replace('.', ',')}{suffix}"

    def ring_style(score):
        return f"--score:{max(0, min(100, int(round(score or 0))))}"

    def stage_width(seconds_label):
        if not seconds_label or seconds_label == "—":
            return 0
        hours_part, minutes_part = seconds_label.split("h ")
        minutes = int(hours_part) * 60 + int(minutes_part.rstrip("m"))
        return max(6, min(100, round(minutes / 300 * 100)))

    def sparkline(values):
        if len(values) < 2:
            values = [60, 62, 61, 65, health.get("hrv") or 66]
        low, high = min(values), max(values)
        span = high - low or 1
        points = []
        for idx, value in enumerate(values):
            x = idx * 100 / (len(values) - 1)
            y = 48 - ((value - low) / span * 34)
            points.append(f"{x:.2f},{y:.2f}")
        polygon = "0,54 " + " ".join(points) + " 100,54"
        return polygon, " ".join(points), points[-1]

    polygon, line_points, last_point = sparkline(hrv_values)
    activity_bars = "".join(
        f"<div><i style='height:{max(12, min(96, int(v / 75 * 100)))}%'></i><span>{label}</span></div>"
        for label, v in zip(["M", "D", "M", "D", "F", "S", "S"], active_days[-7:])
    )
    if not activity_bars:
        activity_bars = "".join(f"<div><i style='height:{h}%'></i><span>{d}</span></div>" for d, h in zip(["M", "D", "M", "D", "F", "S", "S"], [42, 68, 54, 82, 48, 72, 35]))

    html_doc = f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Health Dashboard</title>
<style>
:root {{ --ink:#24486f; --muted:#6f8aa6; --line:#719cbe1f; --blue:#27b9e6; --cyan:#2bc4e8; --green:#24b38a; --surface:#eaf3fa; --shadow:13px 13px 30px #89a4ba47,-12px -12px 28px #ffffffeb; --shadow-small:7px 7px 16px #87a3ba3d,-7px -7px 16px #fffffff0; }}
* {{ box-sizing:border-box }}
body {{ color:var(--ink); background:#eaf3fa; min-height:100vh; margin:0; font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif }}
button,a {{ color:inherit; font:inherit }} button {{ border:0 }}
.app-shell {{ max-width:1520px; margin:0 auto; padding:0 54px 30px }}
.topbar {{ height:92px; display:flex; align-items:center; justify-content:space-between }}
.brand {{ display:flex; align-items:center; gap:11px; text-decoration:none; letter-spacing:0; font-size:22px; font-weight:750 }}
.brand-mark,.avatar {{ color:#fff; border-radius:50%; display:grid; place-items:center; box-shadow:var(--shadow-small); background:linear-gradient(145deg,#4dcbed,#27aede) }}
.brand-mark {{ width:40px; height:40px; font-weight:800 }} .avatar {{ width:42px; height:42px; font-size:12px; font-weight:700 }}
.tabs {{ display:flex; gap:6px; padding:6px; border-radius:21px; background:var(--surface); box-shadow:inset 4px 4px 9px #8ba5bb33,inset -5px -5px 11px #ffffffe6 }}
.tabs::-webkit-scrollbar {{ display:none }}
.tabs {{ scrollbar-width:none }}
.tabs button {{ cursor:pointer; color:#7f8a9e; border-radius:12px; padding:10px 19px; background:transparent }}
.tabs button.active {{ color:#2577a9; box-shadow:var(--shadow-small); background:linear-gradient(145deg,#f7fbfe,#e2edf5); font-weight:650 }}
.profile {{ display:flex; align-items:center; gap:15px }} .icon-button,.more {{ background:var(--surface); cursor:pointer; box-shadow:var(--shadow-small) }}
.icon-button {{ width:40px; height:40px; border-radius:14px; font-size:22px; position:relative }} .notification {{ background:#ff6b75; border:2px solid #fff; border-radius:50%; width:7px; height:7px; position:absolute; top:8px; right:8px }}
.welcome {{ display:flex; align-items:center; justify-content:space-between; padding:37px 6px 27px }}
.eyebrow {{ color:#8994a9; letter-spacing:1.8px; margin:0 0 9px; font-size:10px; font-weight:800; text-transform:uppercase }}
.welcome h1 {{ margin:0; letter-spacing:0; font-size:clamp(30px,3vw,43px); font-weight:630 }} .welcome p:last-child {{ color:#7e899e; margin:9px 0 0; font-size:14px }}
.readiness {{ display:flex; align-items:center; gap:13px }} .readiness-orb,.sleep-ring,.recovery-ring {{ border-radius:50%; display:flex; flex-direction:column; align-items:center; justify-content:center; position:relative; box-shadow:var(--shadow) }}
.readiness-orb {{ width:88px; height:88px; background:conic-gradient(var(--cyan) 0 calc(var(--score)*1%),#cfdde8cc 0) }} .readiness-orb:before,.sleep-ring:before,.recovery-ring:before {{ content:""; background:var(--surface); border-radius:50%; position:absolute; inset:7px; box-shadow:inset 3px 3px 8px #89a3b933,inset -3px -3px 8px #fff }}
.readiness-orb strong,.readiness-orb span,.sleep-ring div,.recovery-ring strong,.recovery-ring span {{ position:relative }} .readiness-orb strong {{ font-size:23px; line-height:1 }} .readiness-orb span {{ color:#8791a5; margin-top:4px; font-size:8px }}
.trend-up {{ color:var(--green); font-size:12px; font-weight:700 }} .readiness small {{ color:#9da6b6; display:block; margin-top:3px; font-size:9px }}
.metric-row {{ display:grid; grid-template-columns:repeat(4,1fr); gap:15px; margin-bottom:16px }}
.glass-card,.metric-card {{ box-shadow:var(--shadow); background:linear-gradient(145deg,#eef6fc,#e5eff7); border:1px solid #ffffff7a }}
.metric-card {{ min-height:116px; border-radius:25px; display:grid; grid-template-columns:auto 1fr auto; align-items:center; gap:13px; padding:18px 19px; position:relative; overflow:hidden }}
.metric-icon,.section-icon {{ display:grid; place-items:center; box-shadow:inset 3px 3px 8px #8ba5bb33,inset -4px -4px 9px #fff; color:#2aaed8; background:var(--surface) }}
.metric-icon {{ width:38px; height:38px; border-radius:13px; font-size:19px }} .section-icon {{ width:35px; height:35px; border-radius:12px; font-size:18px }}
.metric-card>div:nth-child(2) {{ display:flex; flex-direction:column }} .metric-card span:not(.metric-icon,.status-dot,.tiny-graph,.pulse-line) {{ color:#8a95a9; font-size:10px }}
.metric-card strong {{ margin:6px 0 4px; font-size:23px; letter-spacing:0 }} .metric-card strong em {{ color:#7f8a9d; font-size:11px; font-style:normal; font-weight:550 }} .metric-card small {{ color:#9aa4b5; font-size:8px }} .metric-card small b {{ color:var(--green) }}
.mini-progress {{ background:#e4eef5; border-radius:6px; height:7px; position:absolute; bottom:11px; left:19px; right:19px; box-shadow:inset 2px 2px 5px #7b99b147,inset -2px -2px 5px #fff }} .mini-progress i {{ border-radius:inherit; background:linear-gradient(90deg,#28aee0,#38d1e5); height:100%; display:block; box-shadow:0 2px 8px #1db7dd59 }}
.tiny-graph,.pulse-line {{ color:#b17ce1; font-size:26px; transform:rotate(-9deg) }} .pulse-line {{ color:#ec7c88 }} .status-dot {{ color:#3aa886; background:#eaf9f4; border-radius:7px; padding:5px 7px; font-size:8px }}
.dashboard-grid {{ display:grid; grid-template-columns:1.2fr 1fr .86fr; align-items:stretch; gap:20px }}
.glass-card {{ border-radius:28px; min-width:0; padding:23px }} .sleep-card,.hrv-card,.recovery-card {{ min-height:350px }} .checkin-card {{ grid-column:1/3; min-height:220px }} .recovery-card {{ grid-area:1/3 }} .activity-card {{ grid-area:2/3; min-height:220px }}
.card-heading {{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:21px }} .card-heading>div {{ display:flex; align-items:center; gap:11px }} .card-heading h2 {{ margin:0 0 4px; font-size:14px; letter-spacing:0 }} .card-heading p {{ color:#929caf; margin:0; font-size:9px }} .more {{ min-width:30px; height:30px; border-radius:10px; color:#8b96a9 }}
.balanced {{ color:#27a47f; background:#e8f8f2; border-radius:8px; padding:6px 8px; font-size:8px; font-weight:650 }}
.sleep-main {{ display:flex; align-items:center; gap:28px; padding:1px 4px 22px; border-bottom:1px solid var(--line) }} .sleep-ring {{ width:118px; height:118px; flex:none; background:conic-gradient(var(--cyan) 0 calc(var(--score)*1%),#dceaf3 0); box-shadow:var(--shadow-small) }} .sleep-ring:before {{ inset:8px }} .sleep-ring div {{ display:flex; flex-direction:column; align-items:center }} .sleep-ring strong {{ font-size:28px }} .sleep-ring span {{ color:#6477d9; font-size:9px; font-weight:650 }}
.sleep-time {{ display:flex; flex-direction:column }} .sleep-time>span {{ color:#8c97aa; font-size:9px }} .sleep-time strong {{ margin:5px 0; font-size:26px; letter-spacing:0 }} .sleep-time em {{ color:#8490a5; font-size:11px; font-style:normal }} .sleep-time small {{ color:#9aa4b5; font-size:9px }}
.sleep-stages {{ display:grid; grid-template-columns:1fr 1fr; gap:15px 23px; padding-top:19px }} .sleep-stages div {{ color:#7d889d; display:grid; grid-template-columns:1fr auto; gap:7px; font-size:8px }} .sleep-stages b {{ color:#556177 }} .sleep-stages i {{ border-radius:4px; grid-column:1/3; height:4px }} .deep {{ background:#22a9dc }} .rem {{ background:#31c2e4 }} .light {{ background:#74d8e8 }} .awake {{ background:#b7dfe8 }}
.hrv-value {{ display:flex; align-items:flex-end; margin-top:27px }} .hrv-value>strong {{ font-size:38px; line-height:.8; letter-spacing:0 }} .hrv-value>span {{ color:#667188; margin-left:7px; font-size:9px }} .hrv-value>div {{ text-align:right; display:flex; flex-direction:column; margin-left:auto }} .hrv-value b {{ color:var(--green); font-size:9px }} .hrv-value small {{ color:#9da6b7; font-size:7px }}
.sparkline {{ width:100%; height:70px; margin-top:11px; overflow:visible }} .chart-labels {{ color:#a0a8b8; display:flex; justify-content:space-between; margin-top:-4px; font-size:7px }} .insight {{ background:var(--surface); border-radius:13px; display:flex; align-items:center; gap:10px; margin-top:15px; padding:10px 12px; box-shadow:inset 3px 3px 7px #89a3b92e,inset -3px -3px 8px #fff }} .insight p {{ color:#8490a4; margin:0; font-size:8px; line-height:1.5 }} .insight b {{ color:#4b5973 }}
.habit-grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:11px }} .habit {{ min-height:74px; background:var(--surface); box-shadow:var(--shadow-small); cursor:pointer; border-radius:17px; display:flex; flex-direction:column; justify-content:center; align-items:flex-start; padding:11px 12px; position:relative }} .habit.selected {{ color:#147da4; background:linear-gradient(145deg,#38c8e8,#27aedc); box-shadow:inset 3px 3px 7px #0f81a840,inset -3px -3px 7px #7ae8fa8c }} .habit.selected span:nth-child(2) {{ color:#fff }} .habit-icon {{ margin-bottom:7px; font-size:16px }} .habit span:nth-child(2) {{ color:#68758b; font-size:9px; font-weight:600 }} .habit i {{ background:var(--green); color:#fff; border-radius:50%; display:grid; place-items:center; width:16px; height:16px; font-size:8px; font-style:normal; position:absolute; top:9px; right:9px }}
.save-button {{ color:#fff; box-shadow:var(--shadow-small); cursor:pointer; background:linear-gradient(145deg,#39cae9,#22a8d8); border-radius:13px; margin:17px 0 0 auto; padding:11px 20px; font-size:9px; font-weight:650; display:block }}
.recovery-score {{ display:flex; align-items:center; gap:18px }} .recovery-score p {{ color:#728ba2; margin:0; font-size:9px; line-height:1.65 }} .recovery-score p b {{ color:#315c80 }} .recovery-ring {{ width:104px; height:104px; flex:none; background:conic-gradient(var(--cyan) 0 calc(var(--score)*1%),#d9e7f0 0); box-shadow:var(--shadow-small) }} .recovery-ring:before {{ inset:8px }} .recovery-ring strong {{ font-size:25px; line-height:1 }} .recovery-ring span {{ color:#7a94ab; margin-top:4px; font-size:7px }}
.recovery-factors {{ display:grid; gap:12px; margin-top:23px }} .recovery-factors div {{ color:#728ba2; display:grid; grid-template-columns:1fr auto; gap:6px; font-size:8px }} .recovery-factors b {{ color:#397ba0 }} .recovery-factors i {{ background:#e1edf5; border-radius:6px; grid-column:1/3; height:7px; box-shadow:inset 2px 2px 5px #7b99b140,inset -2px -2px 5px #fff }} .recovery-factors em {{ border-radius:inherit; background:linear-gradient(90deg,#27addd,#36cee5); height:100%; display:block }}
.detail-button {{ background:var(--surface); color:#2b84af; width:100%; box-shadow:var(--shadow-small); cursor:pointer; border-radius:13px; display:flex; justify-content:space-between; margin-top:20px; padding:10px 14px; font-size:9px }}
.activity-total {{ color:#248eb8; font-size:9px; font-weight:700 }} .activity-bars {{ display:flex; justify-content:space-between; align-items:flex-end; gap:8px; height:120px; padding:4px 7px 0 }} .activity-bars div {{ flex:1; height:100%; display:flex; flex-direction:column; justify-content:flex-end; align-items:center; gap:8px }} .activity-bars i {{ background:linear-gradient(#38cee7,#25aadb); border-radius:10px; width:100%; max-width:22px; min-height:15px; box-shadow:5px 5px 10px #7d9db540,-3px -3px 8px #fff }} .activity-bars span {{ color:#708ca4; font-size:8px }}
footer {{ color:#9aa4b5; display:flex; justify-content:flex-end; align-items:center; gap:16px; padding:20px 5px 0; font-size:8px }} footer button {{ color:#6577d8; cursor:pointer; background:transparent; font-size:8px }}
@media(width<=1100px) {{ .app-shell {{ padding:0 28px 28px }} .metric-row,.dashboard-grid {{ grid-template-columns:1fr 1fr }} .recovery-card {{ grid-area:2/2 }} .activity-card {{ grid-area:3/1 }} .checkin-card {{ grid-column:1/3 }} .tabs button {{ padding:9px 12px }} }}
@media(width<=760px) {{ .app-shell {{ padding:0 16px 22px }} .topbar {{ flex-wrap:wrap; gap:16px; height:auto; padding:18px 0 }} .tabs {{ order:3; width:100%; overflow:auto }} .tabs button {{ white-space:nowrap; flex:1 }} .welcome {{ align-items:flex-start }} .readiness {{ transform-origin:100% 0; transform:scale(.85) }} .metric-row,.dashboard-grid {{ grid-template-columns:1fr }} .metric-card {{ min-height:105px }} .checkin-card,.recovery-card,.activity-card {{ grid-area:auto/1 }} .habit-grid {{ grid-template-columns:1fr 1fr }} }}
</style>
</head>
<body><main class="app-shell">
<header class="topbar"><a class="brand" href="#" aria-label="Vita Startseite"><span class="brand-mark">V</span><span>Vita</span></a><nav class="tabs" aria-label="Dashboard Bereiche"><button class="active">Übersicht</button><button>Schlaf</button><button>Erholung</button><button>Aktivität</button><button>Trends</button></nav><div class="profile"><button class="icon-button" aria-label="Benachrichtigungen">⌁<span class="notification"></span></button><div class="avatar">JW</div></div></header>
<section class="welcome"><div><p class="eyebrow">{html.escape(health.get('date_label') or 'Heute')}</p><h1>Guten Morgen, Joel.</h1><p>Deine Erholung sieht gut aus. Heute ist ein starker Tag für Bewegung.</p></div><div class="readiness"><div class="readiness-orb" style="{ring_style(recovery_score)}"><strong>{recovery_score}</strong><span>Bereitschaft</span></div><div><span class="trend-up">↗ {max(0, recovery_score - 76)}</span><small>seit Basis</small></div></div></section>
<section class="metric-row" aria-label="Wichtigste Gesundheitswerte">
  <article class="metric-card"><span class="metric-icon steps">⌁</span><div><span>Schritte gestern</span><strong>{de_num(steps)}</strong><small><b>{step_pct}%</b> vom Tagesziel</small></div><div class="mini-progress"><i style="width:{step_pct}%"></i></div></article>
  <article class="metric-card"><span class="metric-icon weight">◇</span><div><span>Gewicht</span><strong>{de_num(health.get('weight'),1)} <em>kg</em></strong><small><b>{signed(health.get('weight_delta'), ' kg')}</b> seit letzter Messung</small></div><span class="tiny-graph">⌁</span></article>
  <article class="metric-card"><span class="metric-icon fat">◌</span><div><span>Körperfett</span><strong>{de_num(health.get('body_fat'),1)} <em>%</em></strong><small>BMI {de_num(health.get('bmi'),1)} · Wasser {de_num(health.get('body_water'),1)}%</small></div><span class="status-dot">Aktuell</span></article>
  <article class="metric-card"><span class="metric-icon pulse">♡</span><div><span>Ruhepuls</span><strong>{fmt(health.get('resting_hr'), ' <em>bpm</em>')}</strong><small><b>HRV {fmt(health.get('hrv'), ' ms')}</b> Nachtwert</small></div><span class="pulse-line">⌁</span></article>
</section>
<section class="dashboard-grid">
  <article class="glass-card sleep-card"><div class="card-heading"><div><span class="section-icon moon">☾</span><div><h2>Dein Schlaf</h2><p>Letzte Nacht</p></div></div><button class="more" aria-label="Mehr Optionen">•••</button></div><div class="sleep-main"><div class="sleep-ring" style="{ring_style(sleep_score)}" aria-label="Schlafscore {sleep_score} von 100"><div><strong>{fmt(sleep_score)}</strong><span>Sehr gut</span></div></div><div class="sleep-time"><span>Schlafdauer</span><strong>{html.escape(health.get('sleep_duration') or '—')}</strong><small>{html.escape(health.get('sleep_time') or 'Garmin Sync')}</small></div></div><div class="sleep-stages"><div><span>Tiefschlaf</span><b>{html.escape(health.get('deep_sleep') or '—')}</b><i class="deep" style="width:{stage_width(health.get('deep_sleep'))}%"></i></div><div><span>REM</span><b>{html.escape(health.get('rem_sleep') or '—')}</b><i class="rem" style="width:{stage_width(health.get('rem_sleep'))}%"></i></div><div><span>Leicht</span><b>{html.escape(health.get('light_sleep') or '—')}</b><i class="light" style="width:{stage_width(health.get('light_sleep'))}%"></i></div><div><span>Wach</span><b>{html.escape(health.get('awake_sleep') or '—')}</b><i class="awake" style="width:{stage_width(health.get('awake_sleep'))}%"></i></div></div></article>
  <article class="glass-card hrv-card"><div class="card-heading"><div><span class="section-icon hrv-icon">⌁</span><div><h2>HRV-Status</h2><p>14-Tage-Trend</p></div></div><span class="balanced">Ausgeglichen</span></div><div class="hrv-value"><strong>{fmt(health.get('hrv'))}</strong><span>ms<br><small>Nachtwert</small></span><div><b>↗ stabil</b><small>über Basis</small></div></div><svg class="sparkline" viewBox="0 0 100 54" preserveAspectRatio="none" aria-label="HRV-Verlauf"><defs><linearGradient id="hrvFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#27b9e6" stop-opacity=".3"></stop><stop offset="100%" stop-color="#27b9e6" stop-opacity="0"></stop></linearGradient></defs><polygon points="{polygon}" fill="url(#hrvFill)"></polygon><polyline points="{line_points}" fill="none" stroke="#27b9e6" stroke-width="2.3" vector-effect="non-scaling-stroke"></polyline><circle cx="{last_point.split(',')[0]}" cy="{last_point.split(',')[1]}" r="2.4" fill="#27b9e6"></circle></svg><div class="chart-labels"><span>14 Tage</span><span>Heute</span></div><div class="insight"><span>✦</span><p><b>Positive Entwicklung</b><br>Schlafscore, HRV und Ruhepuls sprechen für gute Erholung.</p></div></article>
  <article class="glass-card checkin-card"><div class="card-heading"><div><span class="section-icon check">✓</span><div><h2>Tages-Check-in</h2><p>Was trifft heute zu?</p></div></div></div><div class="habit-grid"><button class="habit selected" aria-pressed="true"><span class="habit-icon">✓</span><span>Gesund ernährt</span><i>✓</i></button><button class="habit selected" aria-pressed="true"><span class="habit-icon">↗</span><span>Bewegung</span><i>✓</i></button><button class="habit" aria-pressed="false"><span class="habit-icon">◇</span><span>Alkohol</span><i></i></button><button class="habit" aria-pressed="false"><span class="habit-icon">○</span><span>Sehr fettig</span><i></i></button></div><button class="save-button">Check-in speichern</button></article>
  <article class="glass-card recovery-card"><div class="card-heading"><div><span class="section-icon recovery-icon">✦</span><div><h2>Erholung</h2><p>Heutige Empfehlung</p></div></div><button class="more" aria-label="Mehr Optionen">•••</button></div><div class="recovery-score"><div class="recovery-ring" style="{ring_style(recovery_score)}"><strong>{recovery_score}</strong><span>von 100</span></div><p><b>{html.escape(readiness.get('label') or 'Du bist bereit.')}</b><br>Dein Körper zeigt eine gute Balance aus Belastung und Erholung.</p></div><div class="recovery-factors"><div><span>Schlaf</span><b>Sehr gut</b><i><em style="width:{sleep_score}%"></em></i></div><div><span>HRV</span><b>Optimal</b><i><em style="width:{pct(health.get('hrv') or 0, 90)}%"></em></i></div><div><span>Stress</span><b>{de_num(health.get('stress'),0)}%</b><i><em style="width:{100 - min(100, int(health.get('stress') or 0))}%"></em></i></div></div><button class="detail-button">Details ansehen <span>→</span></button></article>
  <article class="glass-card activity-card"><div class="card-heading"><div><span class="section-icon activity-icon">↗</span><div><h2>Aktive Minuten</h2><p>Diese Woche</p></div></div><span class="activity-total">{de_num(health.get('active_minutes_week'))} min</span></div><div class="activity-bars" aria-label="Aktive Minuten pro Wochentag">{activity_bars}</div></article>
</section>
<footer><span>Daten zuletzt synchronisiert: {html.escape(data['generated_at'])} · Waage: {html.escape(health.get('body_time') or '—')}</span><button>↻ Jetzt synchronisieren</button></footer>
</main></body></html>"""
    return html_doc.encode("utf-8")


def error_page(data: dict) -> bytes:
    msg = html.escape(data.get("error", "unknown error"))
    doc = f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Triathlon HQ</title><style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#050b15;color:#f8fafc;font-family:system-ui}}main{{max-width:760px;padding:32px;background:#111f33;border:1px solid #243247;border-radius:28px}}code{{background:#020617;padding:.2rem .4rem;border-radius:.4rem}}</style></head><body><main><h1>Triathlon HQ</h1><p>I could not reach Garmin/InfluxDB yet.</p><p><code>{msg}</code></p><p>Expected InfluxDB: <code>{html.escape(INFLUX_URL)}</code> database <code>{html.escape(INFLUX_DB)}</code>.</p></main></body></html>"""
    return doc.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        data = get_summary()
        if parsed.path == "/healthz":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body); return
        if parsed.path == "/api/summary":
            body = json.dumps(data, indent=2, default=str).encode("utf-8")
            self.send_response(200 if data.get("ok") else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body); return
        body = page(data)
        self.send_response(200 if data.get("ok") else 503)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
