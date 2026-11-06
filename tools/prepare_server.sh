#!/bin/bash
# Configures a server assembled by mount_server.sh, in its writable layer, which starts empty on every
# start. doi-server@.service runs it as root with "!", in the service's mount namespace: the layers of
# the packages belong to root.
# $1: the server's root, $2: the server's name
set -euo pipefail

cd "$1" || exit

pushd doi/addons/sourcemod/plugins || exit
# Enable SQL admin plugins
mv disabled/admin-sql-threaded.smx .
mv disabled/sql-admin-manager.smx .
# Nextmap is incompatible with DOI
mv nextmap.smx disabled
# SourceBans requires basebans to be off
mv basebans.smx disabled
popd || exit

sourcebans_replacer() {
	sed -i -E "s/(\"$1\"\s+)\"[^\"]*\"/\1\"$2\"/" doi/addons/sourcemod/configs/sourcebans/sourcebans.cfg
}

sourcebans_replacer "BackupConfigs" "0"
if [[ -n ${SOURCEBANS_WEBSITE:-} ]]; then
	sourcebans_replacer "Website" "https:\/\/$SOURCEBANS_WEBSITE"
fi
if [[ -n ${SOURCEBANS_SERVER_ID:-} ]]; then
	sourcebans_replacer "ServerID" "$SOURCEBANS_SERVER_ID"
fi

# Without a config of this repository, users need to provide their own server.cfg loading init-...
if [[ -n ${RCON_PASSWORD:-} ]]; then
	echo "rcon_password \"$RCON_PASSWORD\"" >doi/cfg/rcon.cfg
	if ! grep -q "exec rcon.cfg" doi/cfg/server.cfg; then
		echo "exec rcon.cfg" >>doi/cfg/server.cfg
	fi
fi
