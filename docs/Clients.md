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

The problem is specific to the 32-bit builds of the game and its server: the
64-bit game has much more memory available, so it practically never crashes this
way. Which build you run depends on the platform:

- Windows: the game comes in 32-bit and 64-bit, and Steam starts the 64-bit one
  by default.
- Linux: the native game is 32-bit only, so it's affected. Playing through
  Proton runs the 64-bit Windows game instead, which is what we recommend for
  Day of Infamy on Linux.
- The dedicated server only exists as a 32-bit Linux build, which is why our
  servers set `r_hunkalloclightmaps 0` themselves.

With a 32-bit game, the native Linux one or the 32-bit one on Windows, add
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
