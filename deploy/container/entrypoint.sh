#!/bin/bash
# Starts the server of the container: the server's config of this repository and the secrets into the
# game's doi folder, then prepare_server.sh and the server, run by srcds_watchdog.py, which passes the
# container's stop signal on.
#
# SERVER_NAME: the server's config in servers/, if it has one; without, the secrets need a cfg/server.cfg
# /run/secrets/doi-server: the secrets, laid out like the doi folder (e.g. the database credentials in
# addons/sourcemod/configs/databases.cfg)
# The other settings are the variables of doi-server@.service's environment file (SERVER_PORT, …).
set -euo pipefail

repo=/opt/doi-config
root=/srv/doi

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

exec python3 "$repo/tools/srcds_watchdog.py" -- "$root/srcds_linux" -game doi -usercon +maxplayers 64 \
	+sv_lan 0 -workshop -port "${SERVER_PORT:-27015}" +tv_port "${TV_PORT:-27020}" \
	+clientport "${CLIENT_PORT:-27005}" +map "${STARTUP_MAP:?}" +sv_workshop_list_file "${WORKSHOP_IDS_FILE:?}" \
	+r_hunkalloclightmaps 0 +mp_theater_override "${THEATER:-}" +sv_password "${SERVER_PASSWORD:-}"
