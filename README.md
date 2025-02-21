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
Next, create a symbolic link for the workshop ID file for the respective game mode to `subscribed_file_ids.txt` in your `doi` folder.

You can create symbolic links to the SourcePawn scripts in your SourceMod scripting folder.
After compiling the scripts with `spcomp`, they are ready for use.
Note that the difficulty scaler needs a `server_stronghold.cfg` file to exist, but this can be empty.

### Server patch
In order to enable stats with custom content and the playlist restrictions not to apply, the `engine_srv.so` has to be copied into `doi/bin`. It is patched to disable these restrictions.

### SourceMod plugins
Aside from the included plugins the servers run the following additions:

- [SourceBans](https://github.com/sbpp/sourcebans-pp)
- [Accelerator](https://forums.alliedmods.net/showthread.php?t=277703)
- [Advertisements](https://forums.alliedmods.net/showthread.php?t=155705)
- The threaded SQL admins module (included with SourceMod)
