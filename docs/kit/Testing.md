<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# Testing

## Testing locally

`tests/integration/instance.py` runs a server of one of the configs in a
Podman pod, together with a new MariaDB. The database has the tables of
SourceBans++ and SourceMod and the test server registered, the passwords are
generated, and without its config the Discord forward stays silent, so nothing
reaches the live servers. `TEST_ADMIN` makes SteamIDs root admin, separated by
spaces, each in any of Steam's forms (`STEAM_0:0:123`, `STEAM_1:0:123`,
`[U:1:246]` or the SteamID64 `76561197960265974`). Your settings, like your own
SteamID, can stay in `~/.config/nwi-server-kit/test-instance.env`, one `VAR=value` a
line, so you don't type them each time; variables of the environment take
precedence:

```bash
mkdir -p ~/.config/nwi-server-kit
echo 'TEST_ADMIN=[U:1:246]' >>~/.config/nwi-server-kit/test-instance.env
tests/integration/instance.py build
# The games and the workshop items of all configs into the state folder: about
# 20 GB for Day of Infamy at first, and 10 GB for Insurgency's test server;
# with configs, e.g. update coop-commando, only theirs
tests/integration/instance.py update
tests/integration/instance.py up coop-commando
tests/integration/instance.py rcon sm plugins list
tests/integration/instance.py down
```

The server is then at this machine's address, port 27015, which `up` prints.
Not at `127.0.0.1`: rootless Podman passes connections from there on from the
pod's own address, and the server drops them. `build` and `up` take the packages
and SourceBans++'s tables from the public repository, verified with its key, or
with `NWI_TEST_REPO=local` from the local pacman repository, which they find
like aurutils: `aur repo --status`, or without aurutils the one repository of
pacman.conf with a `file://` server. `AUR_REPO` and `AUR_DBROOT` name its name
and folder, as for aurutils. `build --testing` builds the image with Arch
Linux's testing repositories, for packages built against them on a machine that
uses them. `rcon` runs a command on the server over RCON, as `nwi-rcon` does,
with the password in `RCON_PASSWORD`.

`up --developer 2` starts the server with the game's developer messages, and
options after `--` go on its command line, after those of its `server.toml`:

```bash
tests/integration/instance.py up --developer 2 coop-commando \
  -- +sv_cheats 1
```

They're `LAUNCH_OPTIONS` of the server's environment file, which
`nwi-server start` adds, for the systemd units of `up --db-only` too.

The systemd units can be tested on this machine as well, set up as in [Running
with systemd](Systemd.md), with only the test instance's database:
`up --db-only` starts it at `127.0.0.1:3306` (`TEST_DB_PORT` for another port)
and prints the commands that copy the server's environment file to
`/etc/nwi-server` and its database's credential to `/etc/credstore`, unencrypted
for the test. `down` removes the database again.

The admins get into the database and, through the server's environment file,
into SourceMod's `admins_simple.ini` (`nwi-server prepare`). So
`TEST_ADMIN` in the environment file of any server, e.g.
`/etc/nwi-server/<server>.env`, makes test admins on a server without the
database, too. The live servers' environment files don't have it.

```bash
tests/integration/instance.py up --db-only coop-commando
```

## Testing with sanitisers

Test builds of SourceMod, Metamod:Source and their extensions with Clang's
sanitisers find undefined behaviour and memory errors in them:
UndefinedBehaviorSanitizer (`undefined`), AddressSanitizer (`address`) or both
(`address,undefined`). The AUR packages build them on request, into a repository
of their own that the build keeps and names at the end, not into the local one:

```bash
./aur-packages build --sanitize=undefined metamod-source sourcemod \
  sourcemod-smjansson sourcemod-steamworks
```

`tests/integration/sanitiser` builds an image on top of the usual one with these
packages and the sanitisers' 32-bit runtime (`compiler-rt`), from that
repository's folder. With `SANITISER` set to the sanitisers of the build,
`instance.py up` starts the server from that image, and
`nwi-server start` preloads the runtime into srcds. The reports go to the
server's output, with stack traces:

```bash
podman build --format docker --build-context packages=/tmp/aur-build.XXXXXX \
  -f tests/integration/sanitiser/Containerfile \
  -t localhost/nwi-server-sanitiser .
SANITISER=undefined tests/integration/instance.py up soak-bots
podman logs nwi-test-server 2>&1 |
  grep -E 'runtime error:|ERROR: AddressSanitizer'
```

The soak test runs the `soak-bots` server for hours without players: 20 bots a
team on the frontline maps at 128 tick, the maps changing as in a game. Its
config is a test's, in `tests/integration/servers/soak-bots`, with its own settings and
mapcycle in its `cfg` folder; the test instance mounts it among the image's
configs, so it runs in the container only. `instance.py soak` updates and
starts it, with `tests/integration/soak_watch.py` logging the map, the bots, srcds' memory
and the number of sanitiser reports every five minutes as TSV, adding the bots
again when a map change lost them. At the end, or when it's stopped, it keeps
the server's output next to the log and removes the test instance.
AddressSanitizer takes a lot more memory and time than
UndefinedBehaviorSanitizer, so a long run with it is best left overnight:

```bash
SANITISER=address tests/integration/instance.py soak --hours 8 soak.tsv
```

The round test has bots play a config's rounds and checks that they do:
`instance.py rounds` updates and starts each config in turn, `coop-commando`
and `soak-bots` by default, puts in its plugin
(`tests/integration/plugins/nwi_test_rounds.sp`, which logs the game's round
events), lets bots play with `nwi_bot_only_rounds` and checks, each in its
time, that the game and a round start, that the bots take an objective and
die, and that SourceMod reports no errors of our plugins
(`tests/integration/rounds.py`). It takes a few minutes a config:

```bash
tests/integration/instance.py rounds
```
