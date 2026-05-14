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
            "sleep_score": None if not latest_sleep else latest_sleep.get("sleepScore"),
            "sleep_hours": None if not latest_sleep else round((latest_sleep.get("sleepTimeSeconds") or 0) / 3600, 1),
            "hrv": None if not latest_sleep else latest_sleep.get("avgOvernightHrv"),
            "resting_hr": None if not latest_sleep else latest_sleep.get("restingHeartRate"),
            "body_battery_wake": None if not latest_daily else latest_daily.get("bodyBatteryAtWakeTime"),
            "stress": None if not latest_daily else latest_daily.get("stressPercentage"),
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
    race = data["race"]
    week = data["week"]
    health = data["health"]
    readiness = data["readiness"]
    sports = week["sports"]
    rows_html = "".join(
        f"<tr><td>{html.escape(a['time'])}</td><td>{html.escape(a['sport'])}</td><td>{html.escape(a['name'])}</td><td>{a['distance_km']} km</td><td>{a['hours']} h</td><td>{html.escape(str(a['pace_or_speed']))}</td><td>{fmt(a['avg_hr'], ' bpm')}</td></tr>"
        for a in data["recent"]
    ) or "<tr><td colspan='7'>No recent swim/bike/run activities found yet.</td></tr>"
    gaps = "".join(f"<li>{html.escape(g)}</li>" for g in week["gaps"])
    reasons = "".join(f"<li>{html.escape(r)}</li>" for r in readiness["reasons"]) or "<li>Waiting for more recovery data.</li>"

    def sport_card(key: str, emoji: str) -> str:
        spec = SPORTS[key]
        s = sports[key]
        h_pct = pct(s["hours"], spec["target_hours"])
        session_text = f"{s['sessions']} / {spec['target_sessions']} sessions"
        extra = f" · {int(s['elevation_m'])} m climb" if key == "bike" else ""
        return f"""
        <article class="card sport {key}">
          <div class="sport-head"><span>{emoji}</span><strong>{spec['label']}</strong></div>
          <div class="big">{s['distance_km']} km</div>
          <p>{s['hours']} h · {session_text}{extra}</p>
          <div class="bar"><i style="width:{h_pct}%"></i></div>
        </article>"""

    days = race.get("days_left")
    countdown = "Set date" if days is None else f"{days} days"
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Triathlon HQ</title>
<style>
:root {{ --bg:#050b15; --card:#0e1728; --card2:#111f33; --line:#243247; --text:#f8fafc; --muted:#9ca3af; --cyan:#38bdf8; --green:#34d399; --amber:#fbbf24; --rose:#fb7185; }}
* {{ box-sizing:border-box }} body {{ margin:0; font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; color:var(--text); background:radial-gradient(circle at top left,#123a61 0,#050b15 46rem); }}
main {{ width:min(1180px,100%); margin:auto; padding:28px 18px 48px }}
.hero {{ display:grid; grid-template-columns:1.35fr .65fr; gap:18px }}
.card {{ background:linear-gradient(180deg,rgba(17,31,51,.94),rgba(14,23,40,.94)); border:1px solid rgba(148,163,184,.18); border-radius:28px; padding:24px; box-shadow:0 24px 80px rgba(0,0,0,.25) }}
h1 {{ margin:12px 0 10px; font-size:clamp(2.5rem,7vw,5.7rem); line-height:.92; letter-spacing:-.06em }}
h2 {{ margin:0 0 16px; font-size:1.15rem }} p {{ color:#d1d5db; line-height:1.5 }}
.pill {{ display:inline-flex; gap:.45rem; align-items:center; background:rgba(56,189,248,.12); color:#bae6fd; border:1px solid rgba(56,189,248,.25); border-radius:999px; padding:.45rem .72rem; font-weight:800 }}
.count {{ color:var(--green); font-size:clamp(3rem,8vw,6rem); font-weight:950; letter-spacing:-.07em; line-height:1 }}
.phase {{ color:#fef3c7; font-weight:800 }}
.grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-top:16px }}
.two {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-top:16px }}
.big {{ font-size:2.4rem; font-weight:950; letter-spacing:-.04em }}
.score {{ width:146px; aspect-ratio:1; border-radius:50%; display:grid; place-items:center; font-size:2.7rem; font-weight:950; background:conic-gradient(var(--green) calc(var(--score)*1%), #243247 0); position:relative }}
.score::after {{ content:""; position:absolute; inset:12px; background:var(--card); border-radius:50% }} .score span {{ position:relative; z-index:1 }}
.readiness {{ display:flex; gap:22px; align-items:center }}
ul {{ margin:8px 0 0; padding-left:1.25rem; color:#d1d5db }} li {{ margin:.4rem 0 }}
.sport-head {{ display:flex; gap:.6rem; align-items:center; font-size:1.1rem }} .sport-head span {{ font-size:1.6rem }}
.swim .big {{ color:var(--cyan) }} .bike .big {{ color:var(--green) }} .run .big {{ color:var(--amber) }}
.bar {{ height:10px; background:#07111f; border-radius:99px; overflow:hidden; border:1px solid #26364f }} .bar i {{ display:block; height:100%; border-radius:99px; background:linear-gradient(90deg,var(--cyan),var(--green),var(--amber)) }}
.health {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px }} .tile {{ background:#091323; border:1px solid rgba(148,163,184,.14); border-radius:18px; padding:16px }} .tile b {{ display:block; font-size:1.65rem }} .tile span {{ color:var(--muted); font-size:.92rem }}
table {{ width:100%; border-collapse:collapse; color:#e5e7eb }} th,td {{ text-align:left; padding:11px 8px; border-bottom:1px solid rgba(148,163,184,.13); font-size:.95rem }} th {{ color:#9ca3af; font-weight:800 }}
.footer {{ margin-top:16px; color:var(--muted); font-size:.92rem }} code {{ background:#020617; padding:.18rem .42rem; border-radius:.45rem; border:1px solid #243247 }}
@media(max-width:880px) {{ .hero,.grid,.two,.health {{ grid-template-columns:1fr }} .readiness {{ align-items:flex-start; flex-direction:column }} }}
</style>
</head>
<body><main>
<section class="hero">
  <div class="card"><span class="pill">🏊‍♂️🚴‍♂️🏃 Triathlon HQ</span><h1>{html.escape(race['name'])}</h1><p>{html.escape(race['distance'])} · bike course: {html.escape(race['bike_elevation'])}</p><p class="phase">{html.escape(race['phase'])}</p></div>
  <div class="card"><h2>Race countdown</h2><div class="count">{html.escape(countdown)}</div><p>Race date: <strong>{html.escape(race['date'])}</strong></p><p class="footer">Updated {html.escape(data['generated_at'])}</p></div>
</section>
<section class="two">
  <div class="card"><h2>Readiness</h2><div class="readiness"><div class="score" style="--score:{readiness['score']}"><span>{readiness['score']}</span></div><div><div class="big">{html.escape(readiness['label'])}</div><ul>{reasons}</ul></div></div></div>
  <div class="card"><h2>Coach focus</h2><p><strong>{week['hours']} h</strong> swim/bike/run in the last 7 days.</p><ul>{gaps}</ul></div>
</section>
<section class="grid">{sport_card('swim','🏊')}{sport_card('bike','🚴')}{sport_card('run','🏃')}</section>
<section class="card" style="margin-top:16px"><h2>Health signals</h2><div class="health">
  <div class="tile"><b>{fmt(health['sleep_score'])}</b><span>Sleep score</span></div>
  <div class="tile"><b>{fmt(health['sleep_hours'], ' h')}</b><span>Sleep time</span></div>
  <div class="tile"><b>{fmt(health['hrv'], ' ms')}</b><span>Overnight HRV</span></div>
  <div class="tile"><b>{fmt(health['resting_hr'], ' bpm')}</b><span>Resting HR</span></div>
  <div class="tile"><b>{fmt(health['body_battery_wake'])}</b><span>Body battery wake</span></div>
  <div class="tile"><b>{fmt(health['stress'], '%')}</b><span>Stress</span></div>
  <div class="tile"><b>{fmt(health['vo2_run'])}</b><span>VO₂max run</span></div>
  <div class="tile"><b>{fmt(health['vo2_bike'])}</b><span>VO₂max bike</span></div>
</div></section>
<section class="card" style="margin-top:16px"><h2>Recent activities</h2><table><thead><tr><th>Time</th><th>Sport</th><th>Name</th><th>Distance</th><th>Time</th><th>Pace/speed</th><th>Avg HR</th></tr></thead><tbody>{rows_html}</tbody></table></section>
<p class="footer">InfluxDB: <code>{html.escape(data['influx']['url'])}</code> database <code>{html.escape(data['influx']['database'])}</code>. API: <code>/api/summary</code>.</p>
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
