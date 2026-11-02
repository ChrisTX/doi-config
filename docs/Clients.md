# Day of Infamy client configuration

Settings for players of the servers, to fix crashes on large maps and to make
SourceMod's menus work.

## Engine hunk overflow

Community maps, especially large ones like `ardennes`, can crash the game when
loading. This is an old Source engine problem known as an [Engine Hunk
Overflow](https://developer.valvesoftware.com/wiki/Engine_Hunk_Overflow), and
the crash looks like this:

```text
--------------------------- Engine Error ---------------------------
Out of memory! Attempted to allocate 127401984 bytes
--------------------------- OK ---------------------------
```

The 64-bit game has much more memory available than the 32-bit one, so the
crash practically only happens with the 32-bit game. Use the 64-bit game, or add
`+r_hunkalloclightmaps 0` to the game's launch options in Steam.

## Keys for SourceMod menus

SourceMod menus like the admin menu (`sm_admin`) use the keys 1 to 0 to pick
an entry. The game only binds the keys 1 to 5, so the entries 6 to 10 can't be
picked. To fix this, add the following lines to `config.cfg` in the `doi/cfg`
folder of the game, next to the other key bindings. The game rewrites the file
when it quits, so edit it while the game isn't running:

```text
bind "6" "slot6"
bind "7" "slot7"
bind "8" "slot8"
bind "9" "slot9"
bind "0" "slot10"
```
