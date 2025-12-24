# Day of Infamy client configuration

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
