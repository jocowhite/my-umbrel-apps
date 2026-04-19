## Umbrel Community App Store Template

This repository is a template to create an Umbrel Community App Store. These additional app stores allow developers to distribute applications without submitting to the [Official Umbrel App Store](https://github.com/getumbrel/umbrel-apps).

## How to use:

1. Start by clicking the "Use this template" button located above.
2. Assign an ID and name to your app store within the `umbrel-app-store.yml` file. This file specifies two important attributes:
    - `id` - Acts as a unique prefix for every app within your Community App Store. You must start your application's ID with your app store's ID. For instance, in this template, the app store ID is `sparkles`, and there's an app named `hello world`. Consequently, the app's ID should be: `sparkles-hello-world`.
    - `name` - This is the name of the Community App Store displayed in the umbrelOS UI.
3. Change the name of the `sparkles-hello-world` folder to match your app's ID. The app ID is for you to decide. For example, if your app store ID is `whistles`, and your app is named My Video Downloader, you could set its app ID to `whistles-my-video-downloader`, and rename the folder accordingly.
4. Next, enter your app's listing details in the `whistles-my-video-downloader/umbrel-app.yml`. These are displayed in the umbrelOS UI.
5. Include the necessary Docker services in `whistles-my-video-downloader/docker-compose.yml`.
6. That's it! Your Community App Store, featuring your unique app, is now set up and ready to go. To use your Community App Store, you can add its GitHub url the umbrelOS user interface as shown in the following demo:


https://user-images.githubusercontent.com/10330103/197889452-e5cd7e96-3233-4a09-b475-94b754adc7a3.mp4

## What We Learned

While adding the `my-store-paperclip` app, a few Umbrel-specific gotchas showed up:

1. The app store `id` in [umbrel-app-store.yml](./umbrel-app-store.yml) must match the prefix of every app `id`.
   If the store ID is `my-store`, app IDs need to start with `my-store-...`.
   This was the main reason Paperclip did not appear at first.

2. Port conflicts can hide an app from the store.
   The original Paperclip manifest used `port: 3100`, which collided with `core-lightning-rtl` from the official Umbrel store.
   A later attempt with `3117` also conflicted with the official `bitwatch` app.
   `3118` was verified as free and is the current Paperclip app port in this repo.

3. The manifest `port:` is the Umbrel-facing app port, not necessarily the same as the internal container port.
   It is fine for the container to listen on one port internally while Umbrel exposes the app on another unique external port.

4. Umbrel clones community stores under `/home/umbrel/umbrel/app-stores/`, not `~/umbrel/repos/` on newer installs.
   That path is the right place to inspect when checking what Umbrel actually fetched.

5. If Umbrel is showing old metadata, inspect the cloned repo on the Umbrel box rather than trusting the local working copy.
   In our case, Umbrel was correctly pulling the repo, but it was still reading older manifest content until the relevant commits were pushed.

6. Keeping the manifest close to Umbrel's documented format helps reduce surprises.
   For new apps, `gallery: []` and `releaseNotes: ""` are good defaults.
   Using a lowercase category like `development` is also safer.

7. For apps with hooks, use `manifestVersion: 1.1`.
   Basic manifests can stay on `1`, but as soon as an app needs `pre-start`,
   `post-start`, or other lifecycle hooks, the manifest should be upgraded to
   `1.1`.

8. Relative bind mounts work for quick experiments, but `${APP_DATA_DIR}` is the
   proper Umbrel persistence pattern.
   For Paperclip we moved from `./data/paperclip:/paperclip` to
   `${APP_DATA_DIR}/data:/paperclip` so the app stores its state in Umbrel's
   managed app-data location.

9. Official-style Umbrel apps pin Docker images instead of using `latest`.
   The official app store generally tracks updates through Git commits that bump
   `version` in `umbrel-app.yml` and change image references in
   `docker-compose.yml`. Using `latest` makes updates less predictable and
   harder to debug.

10. Some images need a custom startup command on Umbrel.
    Our first Paperclip attempt failed with
    `error: failed switching to "node": operation not permitted`.
    The Umbrel PR for Paperclip worked around that by overriding the image
    startup with a custom `entrypoint` and `command` instead of relying on the
    default image entrypoint.

11. Built-in app authentication and Umbrel proxy authentication are separate
    concerns.
    Paperclip works better in `authenticated` / `private` mode with
    `PROXY_AUTH_ADD: "false"`, letting Paperclip handle its own login flow
    instead of stacking Umbrel auth in front of it.

12. Hostname allowlists matter for apps that validate public URLs.
    Paperclip needed a broad `PAPERCLIP_ALLOWED_HOSTNAMES` value including
    `DEVICE_DOMAIN_NAME`, `DEVICE_HOSTNAME`, `APP_DOMAIN`, hidden-service names,
    local IPs, and the internal Docker service name.

13. Some apps need lifecycle hooks for first-run setup.
    Paperclip uses:
    - `pre-start` to create a config file in the app data directory
    - `post-start` to wait for health and generate a bootstrap invite for the
      first admin account

14. A community-store app can be “visible in the store” but still be broken at
    runtime.
    Discovery issues and runtime issues are separate:
    - visibility problems usually come from store ID, manifest format, or port collisions
    - startup problems usually come from the image, user permissions, entrypoint,
      persistent volume layout, or environment variables

## Debugging Checklist

When an app does not appear in the Umbrel store:

1. Confirm the store repo was added and updated in Umbrel logs:
   `sudo journalctl -u umbrel -n 200 --no-pager | egrep -i 'appstore|apprepository|error'`

2. Inspect the cloned app store on Umbrel:
   `sudo find /home/umbrel/umbrel/app-stores -maxdepth 2 -name 'umbrel-app.yml' | sort`

3. Verify the community store metadata:
   `sudo sed -n '1,20p' /home/umbrel/umbrel/app-stores/<your-store>/umbrel-app-store.yml`

4. Verify the app manifest Umbrel actually sees:
   `sudo sed -n '1,120p' /home/umbrel/umbrel/app-stores/<your-store>/<your-app>/umbrel-app.yml`

5. Check for port collisions across all stores:
   `sudo find /home/umbrel/umbrel/app-stores -name umbrel-app.yml -print0 | xargs -0 grep -Hn '^port:' | sort -t: -k3,3n`

When an app appears in the store but fails to start:

1. Check the manifest currently cloned on Umbrel:
   `sudo sed -n '1,120p' /home/umbrel/umbrel/app-stores/<your-store>/<your-app>/umbrel-app.yml`

2. Check the app compose file currently cloned on Umbrel:
   `sudo sed -n '1,220p' /home/umbrel/umbrel/app-stores/<your-store>/<your-app>/docker-compose.yml`

3. Check container logs:
   `sudo docker logs <app-id>_server_1 --tail 200`

4. Check proxy logs:
   `sudo docker logs <app-id>_app_proxy_1 --tail 200`

5. Check whether the app container is actually running:
   `sudo docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'`

6. If the app uses hooks, make sure the hooks exist in the cloned store and are executable.

## Packaging Patterns

These patterns worked well or were confirmed by comparing with official Umbrel
apps and the Paperclip submission PR:

1. Store persistent data under `${APP_DATA_DIR}`.

2. Use a specific image tag, and ideally pin it further with `@sha256:...`.

3. Treat `umbrel-app.yml` as the user-facing metadata source and
   `docker-compose.yml` as the runtime source.

4. Keep the manifest `port:` unique across all app stores on the Umbrel device.

5. Keep the internal service port and the external Umbrel app port conceptually
   separate.

6. Prefer explicit environment variables for hostnames, base URLs, and auth
   secrets rather than relying on image defaults.

7. If an app needs one-time bootstrap logic, put it in hooks instead of trying
   to encode it all inside the main container command.

8. Expect uninstall/reinstall to discard app data even if normal restarts keep
   persistent volumes.

## Paperclip Notes

The current `my-store-paperclip` app in this repo is based on lessons from the
official Umbrel Paperclip PR while keeping the community-store app ID and a free
external port for this setup.

Current Paperclip-specific choices:

1. External Umbrel port: `3118`

2. Internal app port behind the proxy: `3100`

3. Persistence path in the container: `/paperclip`

4. Persistence source on Umbrel: `${APP_DATA_DIR}/data`

5. Deployment mode: `authenticated`

6. Exposure mode: `private`

7. Proxy auth: disabled with `PROXY_AUTH_ADD: "false"`

8. Hooks:
   `pre-start` creates the initial config if missing
   `post-start` generates a bootstrap invite after health checks succeed

## Useful Umbrel Commands

Refresh the cloned repo manually on Umbrel:

```bash
STORE=/home/umbrel/umbrel/app-stores/jocowhite-my-umbrel-apps-github-64b67b4c
sudo git -C "$STORE" fetch origin
sudo git -C "$STORE" reset --hard origin/master
sudo systemctl restart umbrel
```

Show whether a chosen port is already used by app manifests:

```bash
PORT=3118
sudo grep -R --include='umbrel-app.yml' -n "^port: $PORT$" /home/umbrel/umbrel/app-stores 2>/dev/null || echo "No app manifest uses port $PORT"
```

Show common listening ports on the Umbrel host:

```bash
sudo ss -ltnp | egrep ':(80|443|3000|3100|3118|4000)\b' || true
```

Show app and proxy logs:

```bash
sudo docker logs my-store-paperclip_server_1 --tail 200
sudo docker logs my-store-paperclip_app_proxy_1 --tail 200
```

Show the cloned Paperclip app files Umbrel is currently using:

```bash
STORE=/home/umbrel/umbrel/app-stores/jocowhite-my-umbrel-apps-github-64b67b4c
sudo sed -n '1,120p' "$STORE/my-store-paperclip/umbrel-app.yml"
sudo sed -n '1,220p' "$STORE/my-store-paperclip/docker-compose.yml"
find "$STORE/my-store-paperclip" -maxdepth 2 -type f | sort
```
