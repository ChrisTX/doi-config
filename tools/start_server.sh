#!/bin/bash
# Starts a server, prepared by prepare_server.sh, under srcds_watchdog.py: for doi-server@.service and the
# container's entrypoint, which share the command line this way.
#
#   start_server.sh ROOT   start the server of ROOT (srcds_linux there), with the settings of its
#                          ROOT/doi/server.toml (tools/server_config.py: the first map, the theater and
#                          more options) and its environment file's
#
# SERVER_PORT, TV_PORT, CLIENT_PORT, SERVER_PASSWORD: the server's ports and password, from its
# environment file (/etc/doi-server/<server>.env)
# DOI_PATCH: the patcher of the server library to preload into srcds (tools/doi_patch.c, built as
# doi_patch.so), which applies patches/server_srv.patches; without it, srcds runs unpatched
set -euo pipefail

repo=$(realpath "$(dirname "${BASH_SOURCE[0]}")/..")
root=$1

# The options of server.toml, one per line
options=$(python3 "$repo/tools/server_config.py" args "$root")
mapfile -t settings <<<"$options"

# Preloaded into srcds only, as srcds_watchdog.py is a 64-bit Python
preload=()
if [[ -n ${DOI_PATCH:-} ]]; then
	if [[ ! -r $DOI_PATCH ]]; then
		echo "Error: no patcher at $DOI_PATCH, which the update builds" >&2
		exit 1
	fi
	preload=(LD_PRELOAD="$DOI_PATCH" DOI_PATCH_LIST="$repo/patches/server_srv.patches")
fi

exec python3 "$repo/tools/srcds_watchdog.py" -- env "${preload[@]}" "$root/srcds_linux" -game doi -usercon \
	+maxplayers 64 +sv_lan 0 -workshop -port "${SERVER_PORT:-27015}" +tv_port "${TV_PORT:-27020}" \
	+clientport "${CLIENT_PORT:-27005}" +r_hunkalloclightmaps 0 +sv_password "${SERVER_PASSWORD:-}" \
	"${settings[@]}"
