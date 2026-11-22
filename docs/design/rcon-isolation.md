<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# RCON isolation and per-server handlers (design)

**Status: draft, for discussion.** This is a proposal, not the current setup and
not finished guidance. It sketches an architecture and the reasons for it, to be
refined before any of it is built.

## The problem

RCON is how a server is administered from outside the game. The protocol is weak
by design:

- It is **unencrypted**. The password, and every command after it, cross the
  network in clear text. Anyone who can see the traffic learns the password;
  anyone who can sit in the middle can read or alter commands and responses.
  This needs no exploit of any kind — it is how the protocol works.
- It rides the **game's own socket** on the game port, so it can't be moved to a
  separate, private listener in server config. Isolating it has to happen at the
  network layer.
- The implementation is **old and unaudited**. The engine is Source 2013
  ([public source](https://github.com/ValveSoftware/source-sdk-2013)), written
  for a different security era and, as far as anyone knows, never fuzzed. Latent
  bugs in an old C++ parser that reads attacker-controlled bytes *before*
  authentication can't be ruled out — not as a specific claim, but as ordinary
  risk. Recent surprises in mature, audited projects (nginx, PHP, Ruby, Java)
  make the point: you can't enumerate what you don't know, so you contain it.

Today the only thing isolating one server's RCON from another is the password.
Each server gets a random `token_urlsafe(24)` in `/run/nwi-server/rcon`, readable
by the `nwi-rcon` group, and a server's own dynamic user isn't in that group — so
a compromised server can reach another's RCON port but can't authenticate. That
is a single control, and it only helps *after* the auth exchange: a pre-auth bug
or a connection flood doesn't care about the password. All servers share the host
network namespace, so every RCON port is reachable by every local process.

## Who this is for

This design is for *our* servers and the people who run them from outside the
game. It's worth being clear who it does and doesn't touch:

- **In-game admins** administer from inside the game with `sm_rcon` and the
  SourceMod admin menu — which runs inside the server process, gated by
  SourceMod's flags, not over the external RCON port. Today they use *only* this,
  because out-of-game RCON is reachable only locally or over the VPN, and that has
  proved too much to ask of them. So two things matter here: the isolation must
  leave in-game `sm_rcon` untouched (it does — that path never crosses the
  namespace boundary), and the access layer should finally give these admins a
  safe out-of-game path that hides the transport (see the front-ends below).
- **Operators (us)** administer from outside the game — deploys, config, server
  commands — and need external RCON. That is what the handler and its access
  layer below are for, and it assumes real systemd and Git fluency.
- **Peer operators**, such as other communities, run their own servers their own
  way and can't adopt this setup. The portable piece for them is a standalone
  RCON-over-SSH wrapper (see the last section), independent of the handler and
  the broker logic — not this design.

## Goals

- A compromised server can't reach another server's RCON, read another's secret,
  or pivot between servers (limit lateral movement).
- The pre-auth RCON surface is reachable only by our own code, never by other
  hosts or other local processes.
- Operator RCON is never spoken in clear text over an untrusted network.
- A compromised server can't damage shared state (the database) beyond its own
  data.
- In-game `sm_rcon` keeps working exactly as now (it's in-process, not the
  external port).
- Non-technical in-game admins get a safe out-of-game RCON path that hides SSH,
  the VPN and the password, so they're no longer limited to `sm_rcon`.

## Design

### 1. Per-server network namespace

Each server runs in its own network namespace:

- The public **game UDP** is forwarded in from the host. An **XDP** filter on the
  ingress drops malformed connectionless packets (bad split counts, impossible
  lengths) and pre-challenge floods — the connectionless-layer sanity check that
  bounds A2S reflection and the earliest out-of-band surface.
- **RCON TCP** is bound inside the namespace and reachable only across the veth
  from the handler side. There is no external route to the TCP port at all. The
  server's own in-process `sm_rcon` still reaches its loopback RCON inside the
  namespace, so in-game admins are unaffected.

The container deployment (podman/Quadlet) already puts each server in its own
network namespace, so most of this comes for free there. The systemd-on-overlays
path would need the namespace plumbed explicitly; getting the public game UDP
back into the namespace is the fiddly part.

### 2. One RCON handler per server

A small handler service per server (e.g. `nwi-rcon-handler@.service`), rather
than a single central broker:

- It `JoinsNamespaceOf=` its server, so it can reach the private RCON TCP, and it
  holds **only that server's** password (reads only
  `/run/nwi-server/rcon/<server>`).
- It exposes a **unix-domain socket** on the host filesystem — unix sockets are
  filesystem objects, so the socket crosses the namespace boundary while the
  network port does not. The socket is group-gated (a per-server group such as
  `nwi-rcon-doi1`), and `SO_PEERCRED` identifies the caller for authorisation and
  an audit log.
- The handler is the **only** thing that ever speaks RCON to the server from
  outside. Operators never hold the password; the pre-auth RCON surface is
  reachable only by our code.

Per-server handlers beat a single broker here: a broker would hold every password
and be able to command everything, a single high-value target. A per-server
handler holds one secret, a compromise of it yields one server, and per-server
groups give natural per-server operator accounts — useful because the games'
commands can't be subdivided anyway (a map change is `sm_rcon`), so access is
all-or-nothing *per server*, which is exactly the granularity this gives.

### 3. Access front-ends

Everything reaches a server through its handler socket; different people get
different front-ends onto it.

**Operators, over SSH.** SSH already solves authentication, encryption and
identity, so there's nothing to hand-roll. It authenticates the operator and runs
a small relay **as that user**, which connects to the handler's unix socket (the
user's group membership is the authorisation). The RCON password never leaves the
handler, and there is **no broker port on the network** — it all rides the SSH
channel. For per-server targeting, either a named SSH subsystem per server, or an
`authorized_keys` `command=` / `ForceCommand` wrapper that takes the server name
(`ssh host nwi-rcon doi1 "…"`); the wrapper form is more flexible, and the model
is the same as PowerShell remoting over SSH. This assumes SSH fluency — it's the
operator path.

**Non-technical admins, over the web.** Our own moderators can't be asked to
drive SSH or the VPN — today that's exactly why they're limited to in-game
`sm_rcon`. A web front-end asks nothing of them: no install, a login, and it
works from a phone. It fits what we already run — SourceBans++ is a web service
with admin accounts, roles and the server list — so the front-end reuses that
identity rather than inventing its own, and relays the admin's command to the
handler socket. It never exposes SSH, the VPN or the password, and rides the same
isolated, audited handler as everything else.

A web front-end that can command servers is a *trusted deputy*, so two things
keep it contained. First, keep the RCON-relaying code a small, separate, hardened
service that only *borrows* SourceBans++' accounts for single sign-on — not a
page bolted into the whole PHP app — so the code that can actually reach a server
stays tiny and auditable. Second, the handler, not the web app, is the trust
boundary: the front-end carries the admin's identity to the handler, which
enforces per-admin, per-server policy and logs every command. A compromised
front-end is then contained to "issue RCON as an authorised admin to authorised
servers" — RCON, not host code execution — and every action is attributable. A
desktop GUI that abstracts SSH (generate a keypair, paste the public key to us)
stays possible for anyone who'd rather have a local tool, but it's a skin on the
operator SSH path, not the path for the non-technical majority.

### 4. Database least privilege

Each server gets its own database account with scoped grants, so a compromised
server can't tamper with shared state:

- SourceBans++: `SELECT` on the admin/server/settings tables; `INSERT`, `SELECT`
  and `UPDATE` on the ban/comment tables. An unban in SourceBans++ is a *soft
  delete* — it `UPDATE`s the ban row (`RemoveType`, `RemovedBy`, `ends`) to mark
  it removed while keeping the history — so even in-game `sm_unban` needs only
  `UPDATE`, not `DELETE`. So: **no** `DELETE`, **no** writes to the admin tables,
  **no** DDL.
- SourceMod's admin tables: `SELECT` only, if admins are managed centrally.

At worst a compromised server adds or marks ban rows; it can't drop tables or
rewrite the admin list. Borgmatic backups cover the residue.

This assumes SourceBans++' soft-delete model and that in-game unbans (if enabled
at all — many installs route unbans through the web panel) go through it. Stock
SourceMod bans, or a plugin that hard-deletes, would want `DELETE`. So the exact
grants need checking against the plugins' real SQL before locking them down.

## Why hardening, not bug-hunting

Deliberately, this invests in containment rather than finding specific bugs.
Finding one wouldn't change much — it is unlikely to be fixed upstream, so we'd
harden anyway — and *not* finding one rules nothing out. So the design assumes
the engine may fail in ways we can't enumerate and limits the blast radius when it
does: isolate the surface, hold the least privilege, keep recoverable backups.

## Peer operators: a standalone RCON-over-SSH wrapper

Other communities can't adopt this setup — it assumes our systemd and Git
tooling, the per-server handlers and the broker logic. What *is* portable is the
plain RCON-over-SSH wrapper our tooling already has: connect to a server's RCON
over an SSH tunnel so the protocol is never spoken in clear text on the wire.

Split out as a standalone tool — independent of the handler, the namespaces and
everything else here — it's something we could hand to a peer like shoubi on its
own. It gives them the one property that matters most (encrypted RCON, no
plaintext MITM) without any of our infrastructure. This fits the planned split of
the NWI tools from the server configuration, and it's tracked here only to keep
it clearly *separate* from the handler design, not part of it.

## Open questions

- **Deployment lead.** The container path gives per-server namespaces for free;
  the systemd path needs explicit plumbing for the public game UDP. Which leads,
  and does the other follow?
- **Admin web front-end.** Leaning to a web service that reuses SourceBans++'
  accounts for login. Open: how tightly to couple it — a page inside
  SourceBans++ (most reuse, largest trusted surface) or a small separate service
  that only borrows its login (smallest surface) — and how the handler verifies
  the admin identity the front-end hands it.
- **Exact database grants.** Verify against SourceBans++ and SourceMod's actual
  SQL (especially the unban path) before locking them down.
- **Handler shape.** Interactive console, one-shot command, or both; how it logs;
  how it maps a user to the servers they may touch.
- **Standalone wrapper scope.** How far to take the split-out wrapper for peers —
  a thin SSH-tunnel helper, or something with a little more comfort — without
  dragging in any of this design.

## Relation to the rest

This belongs with the NWI tools, alongside the existing `rcon.py` (which already
has `connect`/`run`) and the per-instance `nwi-server@.service` template — the
handler is the daemon form of the former on the model of the latter. It leans on
the container deployment for the namespace, sits behind the same "encrypted RCON
only" rule written up for admins in [Hardening](../kit/Hardening.md), and the
standalone wrapper above is a piece of the planned NWI-tools / config split.
