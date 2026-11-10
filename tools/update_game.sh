#!/bin/bash
# Updates the layers the servers share: the game install, the workshop items of all servers and this
# repository's compiled plugins, and checks the plugins' gamedata against the game. doi-update.service
# runs it as the servers' user while no server runs, as the lower layers of an overlay mustn't change
# while it's mounted; the container image runs each step in a layer of its own.
#
#   --game DIR       install or update the game in DIR, without its outdated libraries
#   --workshop DIR   download the workshop items of all workshop-ids-*.txt files into DIR
#   --plugins DIR    compile this repository's plugins into DIR/addons/sourcemod/plugins, replacing DIR
#   --check-gamedata DIR
#                    check that the game in DIR has the functions of the plugins' gamedata
#                    (tools/check_gamedata.py), so that a game update that moved them fails the update
#                    rather than the plugins when the servers start
set -euo pipefail

repo=$(realpath "$(dirname "${BASH_SOURCE[0]}")/..")

update_game() {
	local game=$1 attempt
	# A new SteamCMD fails its first install with "Missing configuration", before it has the app's
	# configuration, and downloads fail at times: tried three times
	for attempt in 1 2 3; do
		steamcmd +force_install_dir "$game" +login anonymous +app_update 462310 validate +quit && break
		((attempt < 3)) || exit 1
	done

	# Remove the shipped, outdated C++ runtime, so the system's is used instead, and libogg and
	# libvorbis, which no library of the game loads (the engine has its own Vorbis decoder): the
	# server puts bin/ on LD_LIBRARY_PATH, where they could take the place of the system's
	rm -f "$game"/bin/{libgcc_s.so.1,libstdc++.so.6,libogg.so,libvorbis.so}
}

# The game only downloads an item once and never updates it, SteamCMD gets its current version. Items
# that fail to download, which SteamCMD's timeouts make happen with large ones, are tried again and
# otherwise kept as they were.
update_workshop() {
	local workshop=$1 item output content
	local -a items pending downloads failed
	mapfile -t items < <(grep -hoE '^[0-9]+' "$repo"/game/cfg/doi-config/workshop-ids-*.txt | sort -u)
	pending=("${items[@]}")
	for _ in 1 2 3; do
		((${#pending[@]})) || break
		downloads=()
		for item in "${pending[@]}"; do
			downloads+=(+workshop_download_item 447820 "$item")
		done
		# SteamCMD's output goes to the log as well, through a pipe: /dev/stderr can't be opened when it's
		# a socket, like the journal's
		output=$(steamcmd +force_install_dir "$workshop" +login anonymous "${downloads[@]}" +quit | tee >(cat >&2)) || true
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
	local -A listed
	for item in "${items[@]}"; do
		listed[$item]=1
	done
	for content in "$workshop"/steamapps/workshop/content/447820/*/; do
		[[ -d $content ]] || continue
		item=$(basename "$content")
		[[ -n ${listed[$item]:-} ]] || rm -rf "$content"
	done
}

# Compiled with SourceMod's include files and those of the installed packages
update_plugins() {
	local layer=$1 plugin
	rm -rf "$layer"
	mkdir -p "$layer/addons/sourcemod/plugins"
	for plugin in "$repo"/game/addons/sourcemod/scripting/*.sp; do
		spcomp -i "$repo/game/addons/sourcemod/scripting/include" \
			-o "$layer/addons/sourcemod/plugins/$(basename "$plugin" .sp).smx" "$plugin"
	done
}

# The plugins' gamedata against the game in DIR
check_gamedata() {
	python3 "$repo/tools/check_gamedata.py" "$1"
}

while (($#)); do
	case $1 in
		--game | --workshop | --plugins)
			"update_${1#--}" "$2"
			shift 2
			;;
		--check-gamedata)
			check_gamedata "$2"
			shift 2
			;;
		*)
			echo "Usage: $0 [--game DIR] [--workshop DIR] [--plugins DIR] [--check-gamedata DIR]" >&2
			exit 2
			;;
	esac
done
