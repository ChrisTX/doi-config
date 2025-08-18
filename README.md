# Day of Infamy Open Configuration

This is the configuration for the Kim Jong Un servers.

## Usage

In order to use this configuration, clone it in your `doi/cfg` folder, i.e. as `doi/cfg/doi-config`.
Afterwards, create a server config that loads the `init-<gamemode>.cfg` config files.
For example, for the Coop Commando configuration set, use

```
hostname "MY-SERVER-NAME"
rcon_password "MY-PASSWORD"

exec doi-config/init-coop-commando.cfg
```
The included `prepare_server.sh` can be used to start up the server and perform most automatic tasks.
It will update SourceMod, Metamod:Source, SourceBans, etc. as well as install the needed symbolic links for everything.

The appropriate workshop ID file for the server has to be passed on commandline to SRCDS via `sv_workshop_list_file`.

### Difficulty scaler
Included is a SourceMod plugin that automatically adjusts the bot count depending on the amount of players, independent from map scripting. For this to work, the currently active game mode needs to have a `server_<gamemode>.cfg` as it should have from the `gamemodes` folder.

### Server patch
In order to enable stats with custom content and the playlist restrictions not to apply, the `engine_srv.so` has to be copied into `doi/bin`. It is patched to disable these restrictions.

### SourceMod plugins
Aside from the included plugins the servers run the following additions:

- [SourceBans](https://github.com/sbpp/sourcebans-pp)
- [Accelerator](https://forums.alliedmods.net/showthread.php?t=277703)
- [Advertisements](https://forums.alliedmods.net/showthread.php?t=155705)
- The threaded SQL admins module (included with SourceMod)
