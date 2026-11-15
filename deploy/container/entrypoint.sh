#!/bin/bash
# The commands of the image, one for the server and for its updates, as the systemd units have them:
#
#   server (the default)  run the server
#   update [--stage]      update the games, the workshop items and the mods in the state folder
#                         /srv/state, like nwi-update.service (and nwi-stage.service with --stage, see
#                         tools/update_layers.sh): its <game>/game, <game>/workshop and <game>/mods
#                         folders, as the servers mount them, of the games of the servers'
#                         environment files in /etc/nwi-server (tools/games.py)
#   check                 check the state's games and workshop items for updates
#                         (tools/check_updates.py): exit status 0 if there are, 1 if not, 255 if it
#                         can't tell
#
# The server's mounts, its game's folders of the state: game at /srv/game and workshop/steamapps/workshop
# at /srv/game/steamapps/workshop, both with Podman's overlay (:O), so that the server's writes stay in
# its container, and read-only: mods at /srv/mods, the depots at /srv/depots and the game's list of
# them at /srv/depots.list. Its start copies the image's files of the game's
# folder (/opt/nwi-layer: SourceMod, Metamod:Source, the plugins and game/ of this repository), the
# mods (the map scripts in custom/, the playlists' configs in cfg/), the server's config of this
# repository and the secrets into the game's folder (doi, insurgency), then runs prepare_server.sh and
# the server, run by srcds_watchdog.py, which passes the container's stop signal on.
#
# SERVER_NAME: the server's config in servers/, if it has one; without, the secrets need a cfg/server.cfg
# /srv/nwi-data: what the server keeps between its containers, volumes or folders of the image's user:
# dumps (crash dumps), logs (the game's), sourcemod/logs and sourcemod/data (SourceMod's)
# /run/secrets/nwi-server: the secrets, laid out like the game's folder (e.g. the database credentials in
# addons/sourcemod/configs/databases.cfg)
# The other settings are the variables of nwi-server@.service's environment file (SERVER_PORT, …).
set -euo pipefail

repo=/opt/nwi-server-kit
root=/srv/game
state=/srv/state

case ${1:-server} in
	update)
		shift
		exec "$repo/tools/update_layers.sh" --image "$@" "$state"
		;;
	check)
		exec python3 "$repo/tools/check_updates.py" "$state"
		;;
	server) ;;
	*)
		echo "Usage: $0 [server | update [--stage] | check]" >&2
		exit 2
		;;
esac

if [[ ! -x $root/srcds_linux ]]; then
	echo "Error: no game in $root, mount the state's game folder there, after an update" >&2
	exit 1
fi
# The game's other depots, e.g. the Steam client library (1006), linked into it: the container has the
# game's own depot at /srv/game, its others in /srv/depots and their list, the game's own last, in
# /srv/depots.list (tools/update_game.sh)
if [[ -f /srv/depots.list ]]; then
	mapfile -t depots </srv/depots.list
	for line in "${depots[@]:0:${#depots[@]}-1}"; do
		cp -asf "/srv/depots/${line%% *}/." "$root/"
	done
fi
# The game's folder, doi or insurgency (tools/games.py)
game=$(python3 "$repo/tools/games.py" folder "$root")
cp -a /opt/nwi-layer/. "$root/$game/"
if [[ -d /srv/mods ]]; then
	cp -r /srv/mods/. "$root/$game/"
fi
# What the server keeps, in volumes at /srv/nwi-data: mounted there rather than in the game's folders,
# where Podman would make the folders above them root's, so the folders are linked
for kept in dumps:dumps "logs:$game/logs" "sourcemod/logs:$game/addons/sourcemod/logs" \
	"sourcemod/data:$game/addons/sourcemod/data"; do
	rm -rf "${root:?}/${kept#*:}"
	ln -s "/srv/nwi-data/${kept%%:*}" "$root/${kept#*:}"
done

if [[ -n ${SERVER_NAME:-} ]]; then
	if [[ ! -d $repo/servers/$SERVER_NAME ]]; then
		echo "Error: Config $SERVER_NAME requested but unknown!" >&2
		exit 1
	fi
	# With its symbolic links resolved: a link to another server's file, like private-mp's motd.txt,
	# points out of the server's folder
	cp -rL "$repo/servers/$SERVER_NAME/." "$root/$game/"
fi
if [[ -d /run/secrets/nwi-server ]]; then
	cp -r /run/secrets/nwi-server/. "$root/$game/"
fi

"$repo/tools/prepare_server.sh" "$root" "${SERVER_NAME:-}"

# The command line of the server's server.toml and environment file
exec "$repo/tools/start_server.sh" "$root"
