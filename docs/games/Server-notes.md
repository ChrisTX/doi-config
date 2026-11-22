<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# Server notes

## Engine hunk overflow

The configuration sets `r_hunkalloclightmaps 0`, which prevents crashes on large
maps like `ardennes`. Community maps of that size contain a lot of lightmap data
and otherwise crash the server with an [Engine Hunk
Overflow](https://developer.valvesoftware.com/wiki/Engine_Hunk_Overflow). In
some cases, like when such a map is the server's startup map, the setting also
has to be passed on the server's command line, as `nwi-server@.service` does.

## Libraries (Linux)

The game server needs the following 32-bit libraries on Linux, here with the
Arch Linux packages that provide them:

| Library | Arch Linux package |
| --- | --- |
| glibc | `lib32-glibc` |
| libgcc, libstdc++ | `lib32-gcc-libs` |
| SDL3 | `lib32-sdl3` |

The server's binaries only link glibc and libstdc++. The Steam client library
(`steamclient.so`) loads SDL3 while the server runs. SDL2 isn't needed: of the
server's libraries, only `libtier0_srv.so` names it, and servers without it run
and don't try to load it. The update removes the outdated copies of
libgcc, libstdc++, libogg and libvorbis that come with the game, so the system's
libraries are used instead.

SourceMod's MySQL and PostgreSQL extensions need zlib besides, which
`lib32-zlib-ng-compat` or `lib32-zlib` provides; the game itself doesn't use it.

The Steam client library can load these libraries as well, but only in the game
client, not in a server:

| Library | Arch Linux package |
| --- | --- |
| libX11 | `lib32-libx11` |
| PulseAudio (libpulse) | `lib32-libpulse` |

The game server binaries also reference these libraries:

| Library | Arch Linux package |
| --- | --- |
| OpenAL | `lib32-openal` (AUR) |
| util-linux | `lib32-util-linux` |
| freetype2 | `lib32-freetype2` |
| fontconfig | `lib32-fontconfig` |

Only the client code paths in `engine.so` load them, so if a server asks for any
of them, something is wrong. This happened when an update removed BattlEye from
the game [in
2025](https://steamdb.info/depot/462311/history/?changeid=M:9106077001589815964),
until [a second
update](https://steamdb.info/depot/462311/history/?changeid=M:1007577009454669389)
fixed it the next day.
