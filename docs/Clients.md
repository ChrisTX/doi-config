# Day of Infamy client configuration

## Client issues
### Engine hunk overflow
Modder created maps, especially large ones like `ardennes`, can crash the game due to their size.
This is due to an ancient Source game engine problem called an [Engine Hunk Overflow](https://developer.valvesoftware.com/wiki/Engine_Hunk_Overflow).
Such an overflow causes the client to crash with an error message looking as follows:

```
---------------------------
Engine Error
---------------------------
Out of memory! Attempted to allocate 127401984 bytes
---------------------------
OK
---------------------------
```

Due to differences in memory limits between the 32-bit and 64-bit versions, this issue is practically only seen in the 32-bit game client or server.
Thus, it's recommended to use the 64-bit game client or add `+r_hunkalloclightmaps 0` to your game launch options.

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
