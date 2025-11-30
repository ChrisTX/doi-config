# Day of Infamy client configuration

## BattlEye
There are two ways to work around the BattlEye bluescreen issue: Either launch the game directly without BattlEye, in which case you can only join servers with BattlEye disabled, or update the BattlEye files with those of a current game.

### Updating BattlEye
As a first step, it is necessary to download a game that has never BattlEye files. A great candidate for this is the free to play game Unturned.
After downloading it, copy the files in the BattlEye folder of that game, and overwrite the ones in the BattlEye folder of Day of Infamy.
Overwrite all files except for `BEClient_x64.cfg`, `BELauncher.ini`, `Install_BattlEye.bat` and `Uninstall_BattlEye.bat`. These files contain Day of Infamy specific configuration and must not be overwritten.

### Launch without BattlEye
The alternative is to avoid starting `dayofinfamy_BE.exe`, and instead directly launch `dayofinfamy_x64.exe`.
It's also possible to replace `dayofinfamy_BE.exe` with `dayofinfamy_x64.exe` to make the Steam Play button launch the game without BattlEye.
While this is sufficent for the Kim Jong Un servers, as they disable BattlEye, other servers cannot be joined with this method.

## HunkAlloc
Modder created maps, especially large ones like `ardennes` can crash the game due to their size.
It's recommended to add `+r_hunkalloclightmaps 0` to your game launch options to reduce the likelyhood of crashing.
For this, right click the game in Steam, go to properties and then in General you can find the launch options.
Add `+r_hunkalloclightmaps 0` to those launch options.

## Slot keybinds for menus
SourceMod menus, like `sm_admin` require the keys 6 to 0 to be bound to commands.
By default, the game only binds the keys 1 to 5 to slot commands, thus the menus will not work properly.
Edit your `client.cfg` in the `doi/cfg` folder and add the following block

```
bind "6" "slot6"
bind "7" "slot7"
bind "8" "slot8"
bind "9" "slot9"
bind "0" "slot10"
```
