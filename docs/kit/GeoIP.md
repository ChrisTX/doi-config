<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# GeoIP2 databases

SourceMod and the SourceBans++ web panel both use MaxMind's GeoIP2 databases.
Both ship MMDB files, but those haven't been updated in years. Instead, install
and configure [geoipupdate](https://github.com/maxmind/geoipupdate), which needs
a free MaxMind account and keeps current databases in `/var/lib/GeoIP`.
The `sourcemod` package and the web panel of the
[sourcebans-pp](https://aur.archlinux.org/packages/sourcebans-pp) package link
their databases from there. The systemd units' servers read them there; the
container image links them there too, so a container needs the host's folder:
the test instance mounts it when it exists, and the Quadlet unit
`nwi-server@.container` has the line to uncomment. A server whose plugins need
them says so with `geoip = true` in its `server.toml`: it then doesn't start
without a database, rather than run with plugins that can't locate players.
Without a database, every server starts without SourceMod's GeoIP extension,
which `nwi-server prepare` removes from the server's own layer: a plugin that
needs it then fails to load, saying so.
