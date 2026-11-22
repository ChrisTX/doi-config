<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# Running in a container

Containers do less around the servers than the systemd units, workshop items
among it: see [systemd and containers](Deployments.md).

`deploy/container/Containerfile` builds an image of a server: SourceMod,
Metamod:Source and the plugins from their packages, this repository and its
compiled plugins. The game and the workshop items aren't part
of it, as they may not be passed on: they're in a state folder on the host,
which the image's updater fills with DepotDownloader, like `nwi-update.service` for
the systemd units, and which the servers mount. The packages come from the
public repository `https://repo.rev-crew.info/aurutils`, verified with its key,
`deploy/container/aurutils.asc`, or from a local pacman repository, like the one
of aurutils (`REPO_NAME` its name, `REPO_SERVER=file:///mnt/repo`, the build
context `repo` its folder). With Podman, from the repository's root:

```bash
podman build --format docker --build-context repo=$(mktemp -d) \
  --secret id=repo-key,src=deploy/container/aurutils.asc \
  -f deploy/container/Containerfile -t nwi-server .
```

`tests/integration/instance.py build` does the same, and `build --local` with
the local repository aurutils uses, e.g. for packages not published yet. The image's commands (`src/nwi_server_kit/container.py`) are the
server, `update` and `check`: `nwi-server update --image` and
`nwi-server check-updates` on the state folder, mounted at `/srv/state`, for the
servers whose environment files are mounted at `/etc/nwi-server`. The image's
configs and plugins are its own.

`deploy/quadlet` has the units for rootless Podman, the containers'
counterparts of `deploy/systemd`, with the state folder
`~/.local/state/nwi-server` and the settings in `~/.config/nwi-server`:

- `nwi-update.container` updates the state folder, as its systemd counterpart.
- `nwi-server@<server>.container` runs a server: its settings in
  `~/.config/nwi-server/<server>.env`, as for `nwi-server@.service`, its secrets
  in `~/.config/nwi-server/secrets` (which may be empty), on the host's
  network. The versions of its game's depot and workshop items are mounted with
  an overlay of the container's own (`:O`), its mods read-only, through the links
  the updater keeps in `~/.local/state/nwi-server/servers/<server>`, as a unit
  can't pick the folders by the server's game; the updater makes the workshop
  items one folder for the containers, `<game>/workshop.v`. It's ready once the image's
  health check, A2S like the systemd units' watchdog, passes, and restarted
  when the server stops answering. What it keeps goes into volumes.
- `nwi-build.service` pulls a clone of this repository and builds the image
  anew; `nwi-restart.service` builds, updates while the servers run and
  restarts them, with the new image, every day with
  `nwi-restart.timer`; `nwi-update-check.timer` checks for updates every three
  hours, as for the systemd units.

```bash
cp deploy/quadlet/*.container ~/.config/containers/systemd/
cp deploy/quadlet/*.service deploy/quadlet/*.timer deploy/quadlet/*.target \
  ~/.config/systemd/user/
systemctl --user daemon-reload
# The server's settings in ~/.config/nwi-server/coop-commando.env, with the
# tools and configs of this checkout, the image's
PYTHONPATH=src python3 -m nwi_server_kit add --user coop-commando
systemctl --user start nwi-update.service
systemctl --user enable --now nwi-server@coop-commando.service nwi-servers.target
systemctl --user enable --now nwi-restart.timer nwi-update-check.timer
loginctl enable-linger
```

`SOURCEBANS_SERVER_IP` of the settings is the server's public address, if the
host's is a private one. Images in the OCI format have no health check, hence
`--format docker`.
