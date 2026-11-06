#!/bin/bash
# Assembles a server from read-only layers with overlayfs, in the mount namespace of its service
# (doi-server@.service runs it as root with "!", so the mounts disappear when the service stops):
#
#   <runtime>          the workshop items of all servers and the shared game install, with a writable
#                      layer
#   <runtime>/doi      /etc/doi-server/secrets, servers/<config>, the compiled plugins, game/ of this
#                      repository, /usr/lib/sourcemod, /usr/lib/metamod, the game's doi folder,
#                      with a writable layer
#
# The writable layers start empty on every start, so updates of the lower layers always show. What the
# server writes and has to keep is bind-mounted from the server's state folder instead.
# $1: the server's name (the instance of doi-server@), $2: the user the server runs as
# SERVER_CONFIG_NAME: the config of servers/ to use, by default the server's name if there's one
set -euo pipefail

name=$1
user=$2
state=/var/lib/doi-server
repo=$state/doi-config
runtime=/run/doi-server/$name
server=$state/servers/$name

# The paths, relative to the server's root, that are kept between starts: folders with a trailing /,
# files without. The game's caches and the crash handler's logs are written anew on every start.
state_paths=(
	# Crash dumps
	dumps/
	doi/logs/
	doi/addons/sourcemod/logs/
	# SourceBans++'s and SourceComms' queues while the database is unreachable, the server's ID
	doi/addons/sourcemod/data/
)

config=${SERVER_CONFIG_NAME:-}
if [[ -z $config && -d $repo/servers/$name ]]; then
	config=$name
fi
if [[ -n $config && ! -d $repo/servers/$config ]]; then
	echo "Error: Config $config requested but unknown!" >&2
	exit 1
fi

rm -rf "$server/upper" "$server/work"
mkdir -p "$server"/{upper,work}/{root,doi} "$server/state"
chown "$user:" "$server" "$server"/{upper,work}/{root,doi} "$server/state"

# Top layer first
lower=()
[[ -d /etc/doi-server/secrets ]] && lower+=(/etc/doi-server/secrets)
[[ -n $config ]] && lower+=("$repo/servers/$config")
lower+=("$state/plugins" "$repo/game" /usr/lib/sourcemod /usr/lib/metamod "$state/game/doi")

root_lower=("$state/game")
[[ -d $state/workshop ]] && root_lower=("$state/workshop" "${root_lower[@]}")

mount -t overlay overlay \
	-o "lowerdir=$(
		IFS=:
		echo "${root_lower[*]}"
	),upperdir=$server/upper/root,workdir=$server/work/root" "$runtime"
mount -t overlay overlay \
	-o "lowerdir=$(
		IFS=:
		echo "${lower[*]}"
	),upperdir=$server/upper/doi,workdir=$server/work/doi" "$runtime/doi"

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
