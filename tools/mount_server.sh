#!/bin/bash
# Assembles a server from read-only layers with overlayfs in /run/doi-server/<name>, as root, for
# doi-mount@.service; doi-server@.service runs the server there:
#
#   <runtime>          the workshop items of the game's servers and the game's install, which the
#                      servers of the game share, with a writable layer
#   <runtime>/<game>   /etc/doi-server/secrets, servers/<config> (its links resolved), the compiled
#                      plugins, the mods made for the game from mods/<game> (tools/make_mods.py), game/
#                      of this repository, /usr/lib/sourcemod, /usr/lib/metamod, the game's folder of
#                      its install (doi, insurgency), with a writable layer
#
# The server's game is its config's (server.toml), or GAME of its environment file, see tools/games.py.
#
# The writable layers start empty whenever the layers are mounted, so updates of the lower layers always
# show. What the server writes and has to keep is bind-mounted from the server's state folder instead.
#
#   mount_server.sh NAME USER       mount the layers of the server NAME (the instance of doi-server@),
#                                   which runs as USER, anew
#   mount_server.sh --unmount NAME  unmount them
#
# SERVER_CONFIG_NAME: the config of servers/ to use, by default the server's name if there's one
# GAME: the server's game without a config, doi by default
set -euo pipefail

# The overlays and the bind mounts of the state paths in them, left over or mounted
unmount() {
	if mountpoint -q "$1"; then
		umount -R "$1"
	fi
	if [[ -d $1 ]]; then
		rmdir "$1"
	fi
}

if [[ ${1:-} == --unmount ]]; then
	unmount "/run/doi-server/$2"
	exit
fi

name=$1
user=$2
state=/var/lib/doi-server
repo=$state/doi-config
runtime=/run/doi-server/$name
server=$state/servers/$name

config=${SERVER_CONFIG_NAME:-}
if [[ -z $config && -d $repo/servers/$name ]]; then
	config=$name
fi
if [[ -n $config && ! -d $repo/servers/$config ]]; then
	echo "Error: Config $config requested but unknown!" >&2
	exit 1
fi
if [[ -f $repo/servers/$config/server.toml ]]; then
	game=$(python3 "$repo/tools/server_config.py" game "$repo/servers/$config/server.toml")
else
	game=${GAME:-doi}
fi
games=$state/$game
if [[ ! -d $games/game/$game ]]; then
	echo "Error: $game isn't installed in $games/game, update first (doi-update.service)" >&2
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

unmount "$runtime"
install -d -m 755 /run/doi-server "$runtime"
rm -rf "$server/upper" "$server/work"
mkdir -p "$server"/{upper,work}/{root,game} "$server/state"
chown "$user:" "$server" "$server"/{upper,work}/{root,game} "$server/state"

# The server's config, copied with its symbolic links resolved: a link to another server's file, like
# private-mp's motd.txt, points out of the server's folder, which the overlay wouldn't have
rm -rf "$server/config"
if [[ -n $config ]]; then
	cp -rL "$repo/servers/$config" "$server/config"
fi

# Top layer first
lower=()
[[ -d /etc/doi-server/secrets ]] && lower+=(/etc/doi-server/secrets)
[[ -n $config ]] && lower+=("$server/config")
lower+=("$state/plugins" "$games/mods" "$repo/game" /usr/lib/sourcemod /usr/lib/metamod "$games/game/$game")

root_lower=("$games/game")
[[ -d $games/workshop ]] && root_lower=("$games/workshop" "${root_lower[@]}")

mount -t overlay overlay \
	-o "lowerdir=$(
		IFS=:
		echo "${root_lower[*]}"
	),upperdir=$server/upper/root,workdir=$server/work/root" "$runtime"
mount -t overlay overlay \
	-o "lowerdir=$(
		IFS=:
		echo "${lower[*]}"
	),upperdir=$server/upper/game,workdir=$server/work/game" "$runtime/$game"

for path in "${state_paths[@]}"; do
	if [[ $path == */ ]]; then
		mkdir -p "$server/state/$path" "$runtime/$path"
	else
		# A file is mounted over a file, which a lower layer may already have
		mkdir -p "$(dirname "$server/state/$path")" "$(dirname "$runtime/$path")"
		touch "$server/state/$path" "$runtime/$path"
	fi
	chown "$user:" "$server/state/$path"
	mount --bind "$server/state/$path" "$runtime/$path"
done
