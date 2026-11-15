#!/bin/bash
# Configures a server in its writable layer: one assembled by mount_server.sh, whose writable layer starts
# empty whenever nwi-server@.service mounts it, on every start of the server (nwi-server@.service runs
# this as root with "!", as the layers of the packages belong to root), or the container's
# (deploy/container/entrypoint.sh), which keeps its writable layer when the container restarts, so
# changing it twice changes nothing.
# $1: the server's root, $2: the server's name
#
# The secrets are the unit's credentials (nwi-server@.service imports them as server.<name>):
#   sourcemod-databases  addons/sourcemod/configs/databases.cfg, SourceMod's and SourceBans++'s
#                        databases
#   rcon-password        the RCON password; without one, a new random one at every start
#   server-password      the password to join, if the server has one
#   secret-cvars         more secret settings, as lines of a config, e.g. SourceBans++'s webhooks
#                        (sbpp_discord_banhook "…")
# Without credentials, as in the container, RCON_PASSWORD and SERVER_PASSWORD of the environment.
# The passwords and secret-cvars go into cfg/nwi-secrets.cfg, which server.cfg runs last: on the
# command line, the process list would show them. A generated RCON password is written to
# /run/nwi-server/rcon/<server>, which the group nwi-rcon can read (nwi-rcon --server, tools/rcon.py).
set -euo pipefail

tools=$(realpath "$(dirname "${BASH_SOURCE[0]}")")
cd "$1" || exit
# The game's folder, doi or insurgency (tools/games.py)
game=$(python3 "$tools/games.py" folder .)

# The server's server.cfg and subscribed_file_ids.txt, made from its server.toml
# (tools/server_config.py), before rcon.cfg is added to it below. Without a server.toml, e.g. a
# server of no config of servers/, its own cfg/server.cfg comes from the secrets.
if [[ -f $game/server.toml ]]; then
	python3 "$tools/server_config.py" prepare .
fi

# Moves a plugin unless it's moved already: a container that restarts keeps its writable layer
move_plugin() {
	if [[ -f $1 ]]; then
		mv "$1" "$2"
	fi
}

pushd "$game/addons/sourcemod/plugins" || exit
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

# Test admins: TEST_ADMIN's SteamIDs, separated by spaces, get root in admins_simple.ini, which
# admin-flatfile.smx reads with or without a database, e.g. on a test server of no database. SourceMod
# takes STEAM_0:…, STEAM_1:…, [U:1:…] and SteamID64 there. deploy/container/test-instance.sh sets it in the
# test instance's environment file; the live servers' don't have it.
admins=$game/addons/sourcemod/configs/admins_simple.ini
read -ra test_admins <<<"${TEST_ADMIN:-}"
for admin in "${test_admins[@]}"; do
	if [[ ! $admin =~ ^(STEAM_[0-5]:[01]:[0-9]+|\[U:1:[0-9]+\]|[0-9]{17})$ ]]; then
		echo "Error: TEST_ADMIN has no SteamID like STEAM_0:0:123, [U:1:246] or 76561197960265974: $admin" >&2
		exit 1
	fi
	# Once: a container that restarts keeps its writable layer
	if ! grep -qF "\"$admin\"" "$admins" 2>/dev/null; then
		printf '"%s"\t"100:z"\t// Test admin (TEST_ADMIN)\n' "$admin" >>"$admins"
	fi
done

sourcebans_replacer() {
	sed -i -E "s/(\"$1\"\s+)\"[^\"]*\"/\1\"$2\"/" "$game/addons/sourcemod/configs/sourcebans/sourcebans.cfg"
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

# A credential of the unit, if it has it
credential() {
	local file=${CREDENTIALS_DIRECTORY:-/nonexistent}/server.$1
	[[ -r $file ]] && cat "$file"
}

# Readable by the server's user only: under systemd, which runs this as root with the server's user,
# its dynamic user (DynamicUser=), in USER
secret_file() {
	install -m 600 /dev/null "$1"
	if [[ $EUID == 0 && -n ${USER:-} && $USER != root ]]; then
		chown "$USER:" "$1"
	fi
}

databases=$(credential sourcemod-databases) || databases=
if [[ -n $databases ]]; then
	secret_file "$game/addons/sourcemod/configs/databases.cfg"
	printf '%s\n' "$databases" >"$game/addons/sourcemod/configs/databases.cfg"
fi

rcon=$(credential rcon-password) || rcon=${RCON_PASSWORD:-}
password=$(credential server-password) || password=${SERVER_PASSWORD:-}
# A new RCON password for the servers of nwi-server@.service without one
if [[ -z $rcon && -d /run/nwi-server/rcon ]]; then
	rcon=$(head -c 24 /dev/urandom | base64 | tr -d '/+=')
fi
if [[ $rcon == *'"'* || $password == *'"'* ]]; then
	echo "Error: a password can't have a quote" >&2
	exit 1
fi
if [[ -n $rcon && -d /run/nwi-server/rcon ]]; then
	install -m 640 -g nwi-rcon /dev/null "/run/nwi-server/rcon/$2"
	printf '%s\n' "$rcon" >"/run/nwi-server/rcon/$2"
fi

# Without a server.toml, users need to provide their own server.cfg
secrets=$game/cfg/nwi-secrets.cfg
secret_file "$secrets"
{
	[[ -z $rcon ]] || printf 'rcon_password "%s"\n' "$rcon"
	[[ -z $password ]] || printf 'sv_password "%s"\n' "$password"
	credential secret-cvars || true
} >"$secrets"
if ! grep -qs "exec nwi-secrets.cfg" "$game/cfg/server.cfg"; then
	echo "exec nwi-secrets.cfg" >>"$game/cfg/server.cfg"
fi
