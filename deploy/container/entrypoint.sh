#!/bin/bash
# The commands of the image, one for the server and for its updates, as the systemd units have them:
#
#   server (the default)  run the server
#   update [--stage]      update the game, the workshop items and the mods in the state folder
#                         /srv/state, like doi-update.service (and doi-stage.service with --stage, see
#                         tools/update_layers.sh): its game, workshop and mods folders, as the server
#                         mounts them
#   check                 check the state's game and workshop items for updates (tools/check_updates.py):
#                         exit status 0 if there are, 1 if not, 255 if it can't tell
#
# The server's mounts, the state's folders: game at /srv/doi and workshop/steamapps/workshop at
# /srv/doi/steamapps/workshop, both with Podman's overlay (:O), so that the server's writes stay in its
# container, and mods/custom at /srv/doi/doi/custom, read-only. Its start copies the image's files of
# the doi folder (/opt/doi-layer: SourceMod, Metamod:Source, the plugins and game/ of this
# repository), the server's config of this repository and the secrets into the doi folder, then runs
# prepare_server.sh and the server, run by srcds_watchdog.py, which passes the container's stop signal
# on.
#
# SERVER_NAME: the server's config in servers/, if it has one; without, the secrets need a cfg/server.cfg
# /srv/doi-data: what the server keeps between its containers, volumes or folders of the image's user:
# dumps (crash dumps), logs (the game's), sourcemod/logs and sourcemod/data (SourceMod's)
# /run/secrets/doi-server: the secrets, laid out like the doi folder (e.g. the database credentials in
# addons/sourcemod/configs/databases.cfg)
# The other settings are the variables of doi-server@.service's environment file (SERVER_PORT, …).
set -euo pipefail

repo=/opt/doi-config
root=/srv/doi
state=/srv/state

case ${1:-server} in
	update)
		shift
		exec "$repo/tools/update_layers.sh" --image "$@" "$state"
		;;
	check)
		exec python3 "$repo/tools/check_updates.py" --game "$state/game" --workshop "$state/workshop"
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
cp -a /opt/doi-layer/. "$root/doi/"
# What the server keeps, in volumes at /srv/doi-data: mounted there rather than in the game's folders,
# where Podman would make the folders above them root's, so the folders are linked
for kept in dumps:dumps logs:doi/logs sourcemod/logs:doi/addons/sourcemod/logs \
	sourcemod/data:doi/addons/sourcemod/data; do
	rm -rf "${root:?}/${kept#*:}"
	ln -s "/srv/doi-data/${kept%%:*}" "$root/${kept#*:}"
done

if [[ -n ${SERVER_NAME:-} ]]; then
	if [[ ! -d $repo/servers/$SERVER_NAME ]]; then
		echo "Error: Config $SERVER_NAME requested but unknown!" >&2
		exit 1
	fi
	cp -r "$repo/servers/$SERVER_NAME/." "$root/doi/"
fi
if [[ -d /run/secrets/doi-server ]]; then
	cp -r /run/secrets/doi-server/. "$root/doi/"
fi

"$repo/tools/prepare_server.sh" "$root" "${SERVER_NAME:-}"

# The patcher of the server library, preloaded into srcds only (srcds_watchdog.py is a 64-bit Python)
exec python3 "$repo/tools/srcds_watchdog.py" -- env LD_PRELOAD=/opt/doi-patch/doi_patch.so \
	DOI_PATCH_LIST="$repo/patches/server_srv.patches" "$root/srcds_linux" -game doi -usercon +maxplayers 64 \
	+sv_lan 0 -workshop -port "${SERVER_PORT:-27015}" +tv_port "${TV_PORT:-27020}" \
	+clientport "${CLIENT_PORT:-27005}" +map "${STARTUP_MAP:?}" +sv_workshop_list_file "${WORKSHOP_IDS_FILE:?}" \
	+r_hunkalloclightmaps 0 +mp_theater_override "${THEATER:-}" +sv_password "${SERVER_PASSWORD:-}"
