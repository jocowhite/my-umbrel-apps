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
   Changing the manifest port to a free port fixed that part.

3. The manifest `port:` is the Umbrel-facing app port, not necessarily the same as the internal container port.
   It is fine for the container to listen on one port internally while Umbrel exposes the app on another unique external port.

4. Umbrel clones community stores under `/home/umbrel/umbrel/app-stores/`, not `~/umbrel/repos/` on newer installs.
   That path is the right place to inspect when checking what Umbrel actually fetched.

5. If Umbrel is showing old metadata, inspect the cloned repo on the Umbrel box rather than trusting the local working copy.
   In our case, Umbrel was correctly pulling the repo, but it was still reading older manifest content until the relevant commits were pushed.

6. Keeping the manifest close to Umbrel's documented format helps reduce surprises.
   For new apps, `gallery: []` and `releaseNotes: ""` are good defaults.
   Using a lowercase category like `development` is also safer.

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
PORT=3117
sudo grep -R --include='umbrel-app.yml' -n "^port: $PORT$" /home/umbrel/umbrel/app-stores 2>/dev/null || echo "No app manifest uses port $PORT"
```

Show common listening ports on the Umbrel host:

```bash
sudo ss -ltnp | egrep ':(80|443|3000|3100|3117|4000)\b' || true
```
