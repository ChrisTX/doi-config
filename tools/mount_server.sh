#!/bin/bash
# Assembles a server from read-only layers with overlayfs in /run/nwi-server/<name>, as root, for
# nwi-server@.service (ExecStartPre=+), which runs the server there:
#
#   <runtime>          the workshop items of the game's servers and the game's depots, which the
#                      servers of the game share, with a writable layer
#   <runtime>/<game>   of its config source: servers/<config> (its links resolved), the compiled
#                      plugins, the mods made for the game from mods/<game> (tools/make_mods.py),
#                      game/; then SourceMod and Metamod:Source (SOURCEMOD_DIR, METAMOD_DIR), the
#                      game's folder of its install (doi, insurgency), with a writable layer
#
# The server's game is its config's (server.toml), or GAME of its environment file, see tools/games.py.
#
# The server and the updater that makes the layers run as users of their own (DynamicUser=), whose
# state systemd keeps as the user nobody's on disk and maps to the unit's user. So the layers are
# mounted with an ID mapping of nobody to the server's user, which sees the updater's files
# (/var/lib/nwi-server/layers) as its own; overlayfs takes only layers of one mapping, so the packages'
# and the config's are mapped alike, which leaves their files root's, read-only to the server. So is
# the server's own state (/var/lib/nwi-server/servers/<name>), whose paths it keeps are bind-mounted
# into the server. Its writable layers are folders of its own in /run/nwi-server/.work/<name>, not on
# the mapped state: overlayfs writes there as root, whom the mapping doesn't have. They start empty
# whenever the layers are mounted, so updates of the lower layers always show. The secrets are the
# unit's credentials (tools/prepare_server.sh).
#
#   mount_server.sh NAME UNIT       mount the layers of the server NAME, whose unit UNIT (its
#                                   nwi-server@NAME.service) runs it, anew
#   mount_server.sh --unmount NAME  unmount them
#
# SERVER_CONFIG_NAME: the config of servers/ to use, by default the server's name if there's one
# CONFIG_SOURCE: the server's config source, whose configs, plugins and mods it gets (see
# tools/games.py), "default" by default
# SOURCEMOD_DIR, METAMOD_DIR: SourceMod's and Metamod:Source's files, laid out like the game's folder
# (/usr/lib/sourcemod and /usr/lib/metamod, of the sourcemod and metamod-source packages)
# GAME: the server's game without a config, doi by default
set -euo pipefail
# Out of the server's folder, systemd's WorkingDirectory=, which would keep it busy
cd /

# The owner on disk of the dynamic users' state, which systemd maps to the units' users
nobody=65534

# The mounts of a server, its overlays, their ID-mapped layers and the bind mounts of its state, left
# over or mounted, the deepest first, and its writable layers
unmount() {
	local name=$1 target
	local -a targets=() deepest
	while read -r target; do
		if [[ $target == "/run/nwi-server/$name" || $target == "/run/nwi-server/$name/"* ||
			$target == "/run/nwi-server/.work/$name/"* ]]; then
			targets+=("$target")
		fi
	done < <(findmnt -rn -o TARGET)
	mapfile -t deepest < <(printf '%s\n' "${targets[@]}" | sort -r)
	for target in "${deepest[@]}"; do
		[[ -n $target ]] || continue
		# Busy for a moment after the server stopped, while systemd takes down its mount namespace,
		# which has the mounts too; detached at last, as every start mounts them anew
		for _ in 1 2 3 4 5; do
			umount "$target" 2>/dev/null && continue 2
			sleep 1
		done
		umount --lazy "$target"
	done
	rm -rf "/run/nwi-server/.work/$name"
	rm -f "/run/nwi-server/rcon/$name"
	if [[ -d /run/nwi-server/$name ]]; then
		rmdir "/run/nwi-server/$name"
	fi
}

if [[ ${1:-} == --unmount ]]; then
	unmount "$2"
	exit
fi

name=$1
unit=$2
tools=$(realpath "$(dirname "${BASH_SOURCE[0]}")")
# The folders on disk, which systemd links to from /var/lib for the dynamic users
state=$(realpath /var/lib/nwi-server/layers)
server=$(realpath "/var/lib/nwi-server/servers/$name")
source=${CONFIG_SOURCE:-default}
repo=$(python3 "$tools/games.py" config "$source")
runtime=/run/nwi-server/$name
work=/run/nwi-server/.work/$name
uid=$(systemctl show -P UID "$unit")
if [[ ! $uid =~ ^[1-9][0-9]*$ ]]; then
	echo "Error: $unit has no user of its own (DynamicUser=): ${uid:-none}" >&2
	exit 1
fi

config=${SERVER_CONFIG_NAME:-}
if [[ -z $config && -d $repo/servers/$name ]]; then
	config=$name
fi
if [[ -n $config && ! -d $repo/servers/$config ]]; then
	echo "Error: Config $config requested but unknown!" >&2
	exit 1
fi
if [[ -f $repo/servers/$config/server.toml ]]; then
	game=$(python3 "$tools/server_config.py" game "$repo/servers/$config/server.toml")
else
	game=${GAME:-doi}
fi
games=$state/$game
if [[ ! -d $games/game/$game ]]; then
	echo "Error: $game isn't installed in $games/game, update first (nwi-update.service)" >&2
	exit 1
fi

# The paths, relative to the server's root, that are kept between starts: folders with a trailing /,
# files without. The game's caches and the crash handler's logs are written anew on every start.
state_paths=(
	# Crash dumps
	dumps/
	"$game/logs/"
	"$game/addons/sourcemod/logs/"
	# SourceBans++'s and SourceComms' queues while the database is unreachable, the server's ID
	"$game/addons/sourcemod/data/"
)

unmount "$name"
install -d -m 755 /run/nwi-server "$runtime"
install -d -m 700 /run/nwi-server/.work "$work"
# The RCON passwords, which prepare_server.sh writes, for the admins of the group nwi-rcon
install -d -m 750 -g nwi-rcon /run/nwi-server/rcon
install -d -o "$uid" -g "$uid" "$work"/{upper,work} "$work"/{upper,work}/{root,game}

# FOLDER as the server's at TARGET, with the files of the owner FROM mapped to its user, and root's
# as root's: overlayfs can't copy up a file whose owner the mapping doesn't have, e.g. when
# prepare_server.sh moves a plugin of the packages
idmapped() {
	[[ -e $3 ]] || mkdir -p "$3"
	mount --bind -o "X-mount.idmap=b:0:0:1 b:$1:$uid:1" "$2" "$3"
}

# The server's config, copied with its symbolic links resolved: a link to another server's file, like
# private-mp's motd.txt, points out of the server's folder, which the overlay wouldn't have
if [[ -n $config ]]; then
	cp -rL "$repo/servers/$config" "$work/config"
fi

# Top layer first, all mapped alike
lower=()
if [[ -n $config ]]; then
	idmapped "$nobody" "$work/config" "$work/lower/config"
	lower+=("$work/lower/config")
fi
idmapped "$nobody" "$state/plugins/$source" "$work/lower/plugins"
idmapped "$nobody" "$games/mods/$source" "$work/lower/mods"
idmapped "$nobody" "$repo/game" "$work/lower/configs"
idmapped "$nobody" "${SOURCEMOD_DIR:-/usr/lib/sourcemod}" "$work/lower/sourcemod"
idmapped "$nobody" "${METAMOD_DIR:-/usr/lib/metamod}" "$work/lower/metamod"
idmapped "$nobody" "$(realpath "$games/game")" "$work/lower/game"
lower+=("$work/lower/plugins" "$work/lower/mods" "$work/lower/configs" "$work/lower/sourcemod"
	"$work/lower/metamod" "$work/lower/game/$game")

# The game's depots, its own (the game's folder) last, as tools/update_game.sh records them: the others,
# e.g. the Steam client library (1006), above it
root_lower=()
while read -r depot _; do
	[[ -n $depot && $state/depots/$depot != "$(realpath "$games/game")" ]] || continue
	idmapped "$nobody" "$state/depots/$depot" "$work/lower/depot-$depot"
	root_lower+=("$work/lower/depot-$depot")
done <"$games/depots"
root_lower+=("$work/lower/game")
if [[ -d $games/workshop ]]; then
	idmapped "$nobody" "$games/workshop" "$work/lower/workshop"
	root_lower=("$work/lower/workshop" "${root_lower[@]}")
fi

# The lower layers as options of their own (lowerdir+, Linux 6.8): the kernel takes no more than 256
# characters for all of them in one lowerdir. Without xino, which a 64-bit kernel may turn on by itself
# (OVERLAY_FS_XINO_AUTO), e.g. with the writable layer on tmpfs: its inode numbers beyond 32 bits make
# the 32-bit server's stat() fail.
lower_layers() {
	local layer
	for layer in "$@"; do
		printf 'lowerdir+=%s,' "$layer"
	done
}

mount -t overlay overlay -o "$(lower_layers "${root_lower[@]}")upperdir=$work/upper/root,workdir=$work/work/root,xino=off" \
	"$runtime"
mount -t overlay overlay -o "$(lower_layers "${lower[@]}")upperdir=$work/upper/game,workdir=$work/work/game,xino=off" \
	"$runtime/$game"

# The paths the server keeps, in its state, as systemd's dynamic users have it: the user nobody's
for path in "${state_paths[@]}"; do
	if [[ $path == */ ]]; then
		mkdir -p "$server/state/$path" "$runtime/$path"
	else
		# A file is mounted over a file, which a lower layer may already have
		mkdir -p "$(dirname "$server/state/$path")" "$(dirname "$runtime/$path")"
		touch "$server/state/$path" "$runtime/$path"
	fi
done
chown -R "$nobody:$nobody" "$server/state"
for path in "${state_paths[@]}"; do
	idmapped "$nobody" "$server/state/$path" "$runtime/$path"
done
