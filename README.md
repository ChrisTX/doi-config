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

### HunkAlloc
The configuration includes a setting of `r_hunkalloclightmaps 0` to prevent crashes with large maps like `ardennes`. Under certain circumstances, like loading such a map as the default server map, it might be necessary to add this to the server launch parameters.

### Tickrate
The tickrate for Day of Infamy should not be changed. While it's possible to run with 128 tick, the game never supported this properly. In particular, at 128 tick, throwables like grenades will start to bounce excessively. Effectively, the game physics break down, even if the game otherwise runs fine.

### Difficulty scaler
Included is a SourceMod plugin that automatically adjusts the bot count depending on the amount of players, independent from map scripting. For this to work, the currently active game mode needs to have a `server_<gamemode>.cfg` as it should have from the `gamemodes` folder.

### Server patch
In order to enable stats with custom content and the playlist restrictions not to apply, the `engine_srv.so` has to be copied into `doi/bin`. It is patched to disable these restrictions.

### SourceMod keybinds
The admin menu `sm_admin` requires the keys 6 to 0 to be bound. Add the following to your client configuration (`config.cfg`):

```
bind "6" "slot6"
bind "7" "slot7"
bind "8" "slot8"
bind "9" "slot9"
bind "0" "slot10"
```

### SourceMod plugins
Aside from the included plugins the servers run the following additions:

- [SourceBans](https://github.com/sbpp/sourcebans-pp)
- [Advertisements](https://forums.alliedmods.net/showthread.php?t=155705)
- The threaded SQL admins module (included with SourceMod)
