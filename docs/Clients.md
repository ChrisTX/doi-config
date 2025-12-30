# Day of Infamy client configuration

## Client issues
### 64-bit version
Historically, Day of Infamy shipped three game executables:

* `dayofinfamy_BE.exe`
* `dayofinfamy.exe`
* `dayofinfamy_x64.exe`

`dayofinfamy.exe` and `dayofinfamy_x64.exe` are the 32-bit and 64-bit versions of the game.

Until the [removal of BattlEye from the game](https://steamdb.info/patchnotes/21294077/), `dayofinfamy_BE.exe` functioned as the loader for BattlEye.
It would start the BattlEye kernel driver among other things, which caused Windows 11 24H2 and newer to variously bluescreen or freeze upon loading.
The BattlEye components hadn't been updated since 2018, eventually leading to that driver becoming a problem.
Afterwards, it would have launched the game variant appropriate for the operating system, launching the 64-bit variant on a 64-bit Windows version and the 32-bit one otherwise.
In general, 32-bit Windows applications can run on both 32-bit and 64-bit Windows editions, but 64-bit applications require a 64-bit Windows edition.
32-bit Windows installations are very rare nowadays, with Windows 11 not even being offered in 32-bit editions at all.

Since BattlEye has been removed however, the Steam game configuration was changed to make Steam's "Play" button launch `dayofinfamy.exe` instead of `dayofinfamy_BE.exe`, putting everyone on the 32-bit variant by default now, whereas the vast majority of players would have been running the 64-bit variant until recently.
It is possible to still launch `dayofinfamy_x64.exe` in the game folder manually.

A convenient way of achieving this without messing with the game files exists by using Steam launch options.
Steam will normally interpret any configured launch options as parameters to pass to the game.
However, if the launch options contain the string `%command%` anywhere, it will instead treat the launch options as a command to execute instead with the `%command%` token being replaced by the command configured by the developers in Steam.
For Day of Infamy, [the configured command](https://steamdb.info/app/447820/config/) is `dayofinfamy.exe -console -crashinprocess`.
Due to this, it's possible to put the following in your game launch options:
```
"<path-to-game>\dayofinfamy_x64.exe" %command%
```
For this, right click the game in Steam, go to properties and then in General you can find the launch options.
Note that it's necessary to put an absolute path here, rather than just `dayofinfamy_x64.exe`, as otherwise Steam won't find the executable.
This will cause the game to be launched with an effective command line of
```
"<path-to-game>\dayofinfamy_x64.exe" "<path-to-game>\dayofinfamy.exe" -console -crashinprocess
```
The game will ignore the first parameter and just launch normally.

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

### Combined solution
It's also possible to combine both of these fixes into one by using the following launch options:

```
"<path-to-game>\dayofinfamy_x64.exe" +r_hunkalloclightmaps 0 %command%
```

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
