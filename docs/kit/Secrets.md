<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# Secrets

A server's secrets are systemd credentials, encrypted in
`/etc/credstore.encrypted`, bound to the machine's TPM if it has one, which
systemd only decrypts for the server's unit. `nwi-server.<name>` is for every
server, `nwi-server@<server>.<name>` for one, which takes precedence:

- `sourcemod-databases`: SourceMod's `databases.cfg`, the databases of
  SourceMod and SourceBans++
- `rcon-password`: the RCON password, without which each start makes a new
  random one
- `server-password`: the password to join, if the server has one
- `secret-cvars`: more secret settings, as lines of a config, e.g. the webhooks
  of SourceBans++'s Discord forward (`sbpp_discord_banhook "…"`)

```bash
systemd-creds encrypt --with-key=tpm2 --name=nwi-server.sourcemod-databases \
  databases.cfg /etc/credstore.encrypted/nwi-server.sourcemod-databases
```

`nwi-server prepare` puts them into the server's folder, readable by the server
only; the passwords go into a config, not the command line, which every user
could see. Each server's RCON password is in `/run/nwi-server/rcon/<server>`,
which the members of the group `nwi-rcon` can read. `nwi-rcon` uses it:

```bash
nwi-rcon --server coop-commando status
nwi-rcon --ssh admin@example.org --server coop-commando sm plugins list
```

With `--ssh`, `nwi-rcon` runs on the server's machine, and the password never
leaves it. RCON is TCP on the game's port, while the game itself is UDP, so a
firewall that only lets UDP in keeps RCON to the machine.
