# Garmin Fetcher Umbrel App

## Task

Turn the currently manual Garmin sync setup into a proper Umbrel community app
so it:

1. starts automatically with Umbrel
2. stays managed by Umbrel instead of a hand-run `docker compose up`
3. keeps its Garmin session/token files in Umbrel app storage
4. writes data into the existing Umbrel InfluxDB app

The old manual workflow on the Umbrel server was:

```bash
cd garmin-sync/
sudo docker compose up
```

This package replaces that with an Umbrel app entry in the community store.

## What This App Does

This app only runs the Garmin fetch worker. It does not package its own
InfluxDB or Grafana instance.

It is designed to work with:

1. Umbrel's existing `influxdb` app
2. Umbrel's existing `grafana` app

The fetcher joins `umbrel_main_network` so it can talk to the InfluxDB
container using the hostname that already worked in the manual setup:

`influxdb_influxdb_1`

## Packaging Decisions

The Umbrel app was updated to match the working compose running on the server,
with a few changes to make it safer as a reusable app-store package:

1. The app now only contains the fetcher service.
   InfluxDB and Grafana are treated as dependencies, not bundled containers.

2. Persistent Garmin token/session data is stored under `${APP_DATA_DIR}`.
   The app uses:

   ```yaml
   ${APP_DATA_DIR}/garminconnect:/home/appuser/.garminconnect
   ```

   This is the Umbrel-friendly replacement for a manual host path like:

   ```yaml
   /home/umbrel/umbrel/data/storage/garmin-fetcher:/home/appuser/.garminconnect
   ```

3. The app joins the external `umbrel_main_network`.
   That preserves the working connectivity model from the manual compose.

4. The app ID was changed to `my-store-garmin-fetcher`.
   This is required because app IDs in a community store must start with the
   app-store ID prefix from `umbrel-app-store.yml`.

5. Secrets were intentionally replaced with placeholders.
   The compose that worked on the Umbrel server included real Garmin and
   InfluxDB credentials. Those should not be committed to the repository.

## Required Configuration

Before publishing or installing this app for real use, update
[docker-compose.yml](./docker-compose.yml) with your actual values for:

1. `GARMINCONNECT_EMAIL`
2. `GARMINCONNECT_BASE64_PASSWORD`
3. `INFLUXDB_PASSWORD`

Current placeholder values are there only to keep secrets out of Git.

## Notes

1. This app has no UI and no exposed port. It is a background worker app.

2. If Umbrel's InfluxDB app ever changes its container hostname, the
   `INFLUXDB_HOST=influxdb_influxdb_1` setting may need to be updated.

3. If you want to avoid hardcoding credentials in `docker-compose.yml`, the
   next improvement would be to add a `pre-start` hook that writes a local env
   or config file from values stored in app data.
