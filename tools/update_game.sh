#!/bin/bash
# Updates the layers the servers share: the game install, the workshop items of all servers and this
# repository's compiled plugins, and builds the patcher of the server library. doi-update.service runs it as the servers' user while no server runs, as
# the lower layers of an overlay mustn't change while it's mounted; the container image runs each step in
# a layer of its own.
#
#   --game DIR       install or update the game in DIR, without its outdated libraries
#   --workshop DIR   download the workshop items of all workshop-ids-*.txt files into DIR
#   --plugins DIR    compile this repository's plugins into DIR/addons/sourcemod/plugins, replacing DIR
#   --patcher FILE   build tools/doi_patch.c, which patches the server library in memory, as FILE
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

	# Remove the shipped, outdated standard libraries, the system's are used instead
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

# The patcher, for srcds (32-bit); replaced only once it's built
update_patcher() {
	local file=$1
	gcc -m32 -std=c23 -O2 -shared -fPIC -Wall -Wextra -o "$file.new" "$repo/tools/doi_patch.c"
	mv "$file.new" "$file"
}

while (($#)); do
	case $1 in
		--game | --workshop | --plugins | --patcher)
			"update_${1#--}" "$2"
			shift 2
			;;
		*)
			echo "Usage: $0 [--game DIR] [--workshop DIR] [--plugins DIR] [--patcher FILE]" >&2
			exit 2
			;;
	esac
done
