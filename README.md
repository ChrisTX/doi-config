# Day of Infamy Open Configuration

[![Checks](https://github.com/ChrisTX/doi-config/actions/workflows/check.yml/badge.svg)](https://github.com/ChrisTX/doi-config/actions/workflows/check.yml)

The configuration of the Kim Jong Un Day of Infamy servers: the game and
SourceMod settings of each game mode, the MOTDs and the SourceMod plugins, and
`nwi-server-kit`, the tools and units that install, update, run and monitor a
server, of Day of Infamy or Insurgency.

The documentation is a book in [docs](docs/README.md), in three parts:

- [The games](docs/games/Clients.md): for players, the
  [client settings](docs/games/Clients.md) the servers need; the
  [cvars](docs/games/Cvars.md) that don't do what they seem to; and for admins,
  [which build of the server to run](docs/games/Builds.md).
- [The configuration](docs/configs/Server-settings.md): the servers' settings,
  configs, plugins, mods and playlists.
- [The server kit](docs/kit/Systemd.md): running the servers with systemd or in
  containers, their workshop items, hardening and testing.

[docs/SUMMARY.md](docs/SUMMARY.md) has all its chapters. With
[mdBook](https://rust-lang.github.io/mdBook/), `mdbook serve` shows it as a
website, `mdbook build` makes one in `target/book`.

To set up a server, see [Running with systemd](docs/kit/Systemd.md) or
[Running in a container](docs/kit/Containers.md); to work on the repository,
[CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

The configuration, scripts and units are licensed under the [MIT](LICENSE)
licence. The SourceMod plugins written for these servers, `nwi_cvar_unlocker`,
`nwi_difficulty_scaler`, `nwi_gamedata`, `nwi_mode_config`, `nwi_netstats`,
`nwi_physics_timestep`, `nwi_playlist_unlock` and `nwi_server_visibility`, are available under the MIT licence or the GPL-3.0-only with SourceMod's linking
exception, at your choice, so they can be used in other SourceMod projects
either way.

AFK Manager, vendored in `game/common/addons/sourcemod` together with its include,
translations and configuration, is licensed under the GPL-3.0-only with
SourceMod's linking exception, like its earlier versions. The mods' map scripts
aren't part of this repository: `nwi-server make-mods` makes them from the game's
own when a server is set up, so they remain New World Interactive's.

`REUSE.toml`, the file headers and the `LICENSES` folder say this in the
[REUSE](https://reuse.software/) format.
