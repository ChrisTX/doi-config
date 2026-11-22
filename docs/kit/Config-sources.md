<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# Config sources

A server's configs, its `server.toml`, the configs of `game` and the mods,
come from a config source: a repository like this one, e.g. a community's, at a
branch or tag. `/etc/nwi-server/configs/<source>.env` names it, `URL=` the
repository and `REF=` the branch or tag (the repository's own branch, pulled,
without one); the updater keeps its clone in its state. A server takes the
source `CONFIG_SOURCE` of its environment file, `default` without one, so
servers of different communities can run on one machine, each with its own
configs, plugins and mods:

```ini
# /etc/nwi-server/configs/theirs.env
URL=https://example.org/theirs/server-configs.git
REF=live
# /etc/nwi-server/their-server.env
CONFIG_SOURCE=theirs
```

The workshop items stay one download per game for all sources, and each server
mounts the items of its own list.
