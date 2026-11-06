#!/bin/bash
# Updates the game install that all servers share, the lowest layer of their overlays, and compiles this
# repository's plugins into a layer of their own. Run by doi-update.service as the servers' user, while no
# server runs: the lower layers of an overlay mustn't change while it's mounted.
# $1: the state directory (/var/lib/doi-server)
set -euo pipefail

state=$1
game=$state/game
repo=$(realpath "$(dirname "${BASH_SOURCE[0]}")/..")

steamcmd +force_install_dir "$game" +login anonymous +app_update 462310 validate +quit

# Patch the server library to lift the playlist restrictions and enable stats with custom content.
# SteamCMD's validate restores the original, which the patch applies to. A game update needs a new patch.
server_srv_original=be44b24b6525ec0a622310a91803e5f8444c1b501e057032800e6f1dd924a318
server_srv_patched=104743f75a63ebf6137f4e1dbcd83897fee50386a895fad3bf26ccd2051f5358
server_srv=$game/doi/bin/server_srv.so
server_srv_sum=$(sha256sum "$server_srv" | cut -d ' ' -f 1)
if [[ $server_srv_sum == "$server_srv_original" ]]; then
	xxd -r "$repo/patches/server_srv.xxd" "$server_srv"
	server_srv_sum=$(sha256sum "$server_srv" | cut -d ' ' -f 1)
fi
if [[ $server_srv_sum != "$server_srv_patched" ]]; then
	echo "Error: $server_srv isn't the version patches/server_srv.xxd is made for" >&2
	exit 1
fi

# Remove the shipped, outdated standard libraries, the system's are used instead
rm -f "$game"/bin/{libgcc_s.so.1,libstdc++.so.6,libogg.so,libvorbis.so}

# The workshop items of all servers, the layer above the game install. The game only downloads an item
# once and never updates it, SteamCMD gets its current version. Items that fail to download, which
# SteamCMD's timeouts make happen with large ones, are tried again and otherwise kept as they were.
workshop=$state/workshop
mapfile -t items < <(grep -hoE '^[0-9]+' "$repo"/game/cfg/doi-config/workshop-ids-*.txt | sort -u)
pending=("${items[@]}")
for _ in 1 2 3; do
	((${#pending[@]})) || break
	downloads=()
	for item in "${pending[@]}"; do
		downloads+=(+workshop_download_item 447820 "$item")
	done
	output=$(steamcmd +force_install_dir "$workshop" +login anonymous "${downloads[@]}" +quit | tee /dev/stderr) || true
	failed=()
	for item in "${pending[@]}"; do
		grep -q "Success. Downloaded item $item " <<<"$output" || failed+=("$item")
	done
	pending=("${failed[@]}")
done
if ((${#pending[@]})); then
	echo "Warning: workshop items not updated, kept as they were: ${pending[*]}" >&2
fi

# The items no list names any more
declare -A listed
for item in "${items[@]}"; do
	listed[$item]=1
done
for content in "$workshop"/steamapps/workshop/content/447820/*/; do
	[[ -d $content ]] || continue
	item=$(basename "$content")
	[[ -n ${listed[$item]:-} ]] || rm -rf "$content"
done

# This repository's plugins, compiled with SourceMod's include files and those of the installed packages
plugins=$state/plugins/addons/sourcemod/plugins
rm -rf "$state/plugins"
mkdir -p "$plugins"
for plugin in "$repo"/game/addons/sourcemod/scripting/*.sp; do
	name=$(basename "$plugin" .sp)
	spcomp -i "$repo/game/addons/sourcemod/scripting/include" -o "$plugins/$name.smx" "$plugin"
done
