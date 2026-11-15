#!/bin/bash
# Updates the layers the servers share: a game's install, the workshop items of its servers and this
# repository's compiled plugins, and checks the plugins' gamedata against a game. doi-update.service
# runs it as the servers' user while no server runs, as the lower layers of an overlay mustn't change
# while it's mounted; the container image runs each step in a layer of its own.
#
#   --game GAME DIR  install or update the dedicated server of GAME (doi, insurgency: tools/games.py) in
#                    DIR, without its outdated libraries
#   --workshop GAME DIR
#                    download the workshop items of GAME's servers (tools/games.py) into DIR, and
#                    remove the items no server lists any more
#   --plugins DIR    compile this repository's plugins into DIR/addons/sourcemod/plugins, replacing DIR
#   --check-gamedata DIR
#                    check that the game in DIR has the functions of the plugins' gamedata
#                    (tools/check_gamedata.py), so that a game update that moved them fails the update
#                    rather than the plugins when the servers start
set -euo pipefail

tools=$(realpath "$(dirname "${BASH_SOURCE[0]}")")
# The configs, with the plugins' sources (DOI_CONFIG, see tools/games.py)
config=$(python3 "$tools/games.py" config)

update_game() {
	local app game=$2 attempt
	app=$(python3 "$tools/games.py" app "$1")
	# A new SteamCMD fails its first install with "Missing configuration", before it has the app's
	# configuration, and downloads fail at times: tried three times
	for attempt in 1 2 3; do
		steamcmd +force_install_dir "$game" +login anonymous +app_update "$app" validate +quit && break
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
	local workshop=$2 app='' line_app item output content listing
	local -a items=() pending downloads failed
	# "<app> <item>" a line, the app being the workshop's, the same for all. Kept apart from the loop's
	# variables, which read empties at the end of the list.
	listing=$(python3 "$tools/games.py" items "$1")
	while read -r line_app item; do
		[[ -n $item ]] || continue
		app=$line_app
		items+=("$item")
	done <<<"$listing"
	pending=("${items[@]}")
	# Also without items, as the servers mount it
	mkdir -p "$workshop/steamapps/workshop"
	for _ in 1 2 3; do
		((${#pending[@]})) || break
		downloads=()
		for item in "${pending[@]}"; do
			downloads+=(+workshop_download_item "$app" "$item")
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
	for content in "$workshop"/steamapps/workshop/content/*/*/; do
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
	for plugin in "$config"/game/addons/sourcemod/scripting/*.sp; do
		spcomp -i "$config/game/addons/sourcemod/scripting/include" \
			-o "$layer/addons/sourcemod/plugins/$(basename "$plugin" .sp).smx" "$plugin"
	done
}

# The plugins' gamedata against the game in DIR
check_gamedata() {
	python3 "$tools/check_gamedata.py" "$1"
}

while (($#)); do
	case $1 in
		--game | --workshop)
			"update_${1#--}" "$2" "$3"
			shift 3
			;;
		--plugins)
			update_plugins "$2"
			shift 2
			;;
		--check-gamedata)
			check_gamedata "$2"
			shift 2
			;;
		*)
			echo "Usage: $0 [--game GAME DIR] [--workshop GAME DIR] [--plugins DIR] [--check-gamedata DIR]" >&2
			exit 2
			;;
	esac
done
