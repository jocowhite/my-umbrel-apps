# Garmin Sync UI App

## Goal

Package the Garmin sync workflow as a real Umbrel app so you no longer need to
SSH into the server and run:

```bash
cd garmin-sync/
sudo docker compose up
```

This app adds:

1. a small setup UI for entering Garmin and InfluxDB credentials
2. persistent storage in Umbrel app data
3. automatic startup with Umbrel
4. an automatically restarted worker when settings are saved

## Architecture

The app contains two services:

1. `web`
   A small Flask-based settings UI available through Umbrel.

2. `worker`
   A wrapper around the upstream Garmin fetch image that waits for config,
   loads it from app data, and then starts the Garmin sync process.

Both services share `${APP_DATA_DIR}`.

## Storage

The app stores data in:

1. `${APP_DATA_DIR}/config/settings.json`
   Human-readable saved settings.

2. `${APP_DATA_DIR}/config/worker.env`
   Worker environment generated from the UI.

3. `${APP_DATA_DIR}/garminconnect`
   Garmin token/session files.

## Notes

1. The UI writes the Garmin password in Base64 form because that is what the
   upstream worker expects.

2. The worker uses Umbrel's external `umbrel_main_network` so it can reach the
   existing InfluxDB app container.

3. The chosen app port is `3587`. It should still be checked on the target
   Umbrel if you already have many custom apps installed.
