#!/bin/bash
# Configures a server in its writable layer: one assembled by mount_server.sh, whose writable layer starts
# empty on every start (doi-server@.service runs it as root with "!", in the service's mount namespace, as
# the layers of the packages belong to root), or the container's (deploy/container/entrypoint.sh).
# $1: the server's root, $2: the server's name
set -euo pipefail

cd "$1" || exit

# Moves a plugin unless it's moved already: a container that restarts keeps its writable layer
move_plugin() {
	if [[ -f $1 ]]; then
		mv "$1" "$2"
	fi
}

pushd doi/addons/sourcemod/plugins || exit
# Enable SQL admin plugins
move_plugin disabled/admin-sql-threaded.smx .
move_plugin disabled/sql-admin-manager.smx .
# Nextmap is incompatible with DOI
move_plugin nextmap.smx disabled
# SourceBans requires basebans to be off
move_plugin basebans.smx disabled
popd || exit

sourcebans_replacer() {
	sed -i -E "s/(\"$1\"\s+)\"[^\"]*\"/\1\"$2\"/" doi/addons/sourcemod/configs/sourcebans/sourcebans.cfg
}

sourcebans_replacer "BackupConfigs" "0"
if [[ -n ${SOURCEBANS_WEBSITE:-} ]]; then
	sourcebans_replacer "Website" "https:\/\/$SOURCEBANS_WEBSITE"
fi
# The server's ID in the panel. Left at -1, SourceBans++ looks it up by the server's address and port,
# with the address from hostip, or from SOURCEBANS_SERVER_IP where hostip is a private address, as in a
# container
if [[ -n ${SOURCEBANS_SERVER_ID:-} ]]; then
	sourcebans_replacer "ServerID" "$SOURCEBANS_SERVER_ID"
fi
if [[ -n ${SOURCEBANS_SERVER_IP:-} ]]; then
	sourcebans_replacer "ServerIP" "$SOURCEBANS_SERVER_IP"
fi

# Without a config of this repository, users need to provide their own server.cfg loading init-...
if [[ -n ${RCON_PASSWORD:-} ]]; then
	echo "rcon_password \"$RCON_PASSWORD\"" >doi/cfg/rcon.cfg
	if ! grep -q "exec rcon.cfg" doi/cfg/server.cfg; then
		echo "exec rcon.cfg" >>doi/cfg/server.cfg
	fi
fi
