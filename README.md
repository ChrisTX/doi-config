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
Next, create a symbolic link for the `subscribed_file_ids.txt` in your `doi` folder.

You can create symbolic links to the SourcePawn scripts in your SourceMod scripting folder.
After compiling the scripts with `spcomp`, they are ready for use.
