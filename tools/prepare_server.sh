#!/bin/bash
# Configures a server in its writable layer: one assembled by mount_server.sh, whose writable layer starts
# empty whenever doi-mount@.service mounts it, on every start of the server (doi-server@.service runs
# this as root with "!", as the layers of the packages belong to root), or the container's
# (deploy/container/entrypoint.sh), which keeps its writable layer when the container restarts, so
# changing it twice changes nothing.
# $1: the server's root, $2: the server's name
set -euo pipefail

repo=$(realpath "$(dirname "${BASH_SOURCE[0]}")/..")
cd "$1" || exit

# SourceMod looks for the engine's library, which gamedata of the library "engine" needs (e.g.
# nwi_gamedata.smx's), in the game's bin folder (doi/bin) and the server's EXECUTABLE_PATH, which is the
# server's root here, not bin/ with engine_srv.so. A link in the root lets it find the library srcds has
# loaded; it caches a failed lookup, so the link has to be there when srcds starts.
if [[ -f bin/engine_srv.so && ! -e engine_srv.so ]]; then
	ln -s bin/engine_srv.so engine_srv.so
fi

# The server's server.cfg and subscribed_file_ids.txt, made from its server.toml
# (tools/server_config.py), before rcon.cfg is added to it below. Without a server.toml, e.g. a
# server of no config of servers/, its own cfg/server.cfg comes from the secrets.
if [[ -f doi/server.toml ]]; then
	python3 "$repo/tools/server_config.py" prepare .
fi

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
# Plugins the environment disables, e.g. DISABLE_PLUGINS=nwi_cvar_unlocker for the game's own bounds of
# its cvars (tools/dump_cvars.py)
read -ra disabled <<<"${DISABLE_PLUGINS:-}"
for plugin in "${disabled[@]}"; do
	move_plugin "$plugin.smx" disabled
done
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

# Without a server.toml, users need to provide their own server.cfg
if [[ -n ${RCON_PASSWORD:-} ]]; then
	echo "rcon_password \"$RCON_PASSWORD\"" >doi/cfg/rcon.cfg
	if ! grep -q "exec rcon.cfg" doi/cfg/server.cfg; then
		echo "exec rcon.cfg" >>doi/cfg/server.cfg
	fi
fi
