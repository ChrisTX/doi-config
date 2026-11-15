#!/bin/bash
# Updates the layers the servers share: a game's depots, the workshop items of its servers and this
# repository's compiled plugins, and checks the plugins' gamedata against a game. nwi-update.service
# runs it as the updater's user while no server runs, as the lower layers of an overlay mustn't change
# while they're mounted; the container image runs each step in a layer of its own. The downloads are
# DepotDownloader's, anonymous: its record of a download is in .DepotDownloader of the download's folder.
#
#   --game GAME STATE
#                    install or update the depots of GAME's dedicated server (doi, insurgency:
#                    tools/games.py) for Linux, the public branch's, each in STATE/depots/<depot>,
#                    which the games share, e.g. the Steamworks SDK Redist (1006); the depots and
#                    their manifests in STATE/GAME/depots, a line each, the game's own last, the one
#                    with the game's folder, which STATE/GAME/game links to; without its outdated
#                    libraries. An install of SteamCMD's in STATE/GAME/game becomes the game's depot,
#                    whose files are checked, so only what differs is downloaded.
#   --workshop GAME DIR
#                    download the workshop items of GAME's servers (tools/games.py) into DIR, as
#                    SteamCMD would (steamapps/workshop/content/<app>/<item>, and its record of them,
#                    steamapps/workshop/appworkshop_<app>.acf), and remove the items no server lists
#                    any more
#   --plugins DIR    compile this repository's plugins into DIR/addons/sourcemod/plugins, replacing DIR
#   --check-gamedata DIR
#                    check that the game in DIR has the functions of the plugins' gamedata
#                    (tools/check_gamedata.py), so that a game update that moved them fails the update
#                    rather than the plugins when the servers start
set -euo pipefail

tools=$(realpath "$(dirname "${BASH_SOURCE[0]}")")
# The configs, with the plugins' sources (NWI_CONFIG, see tools/games.py)
config=$(python3 "$tools/games.py" config)

# DepotDownloader, tried three times: downloads fail at times. Its output goes to the log as well,
# through a pipe: /dev/stderr can't be opened when it's a socket, like the journal's
download() {
	local attempt
	for attempt in 1 2 3; do
		# Without its progress, a line a file
		depotdownloader "$@" > >(grep -v -E '^ *[0-9.]+% |^Pre-allocating ' >&2) && return
		echo "Warning: DepotDownloader failed, attempt $attempt of 3: $*" >&2
	done
	return 1
}

update_game() {
	local game=$1 state=$2 app listing list line depot manifest content='' old
	local -a depots=()
	app=$(python3 "$tools/games.py" app "$game")
	# The public branch's depots for Linux and their manifests, as manifest_<depot>_<manifest>.txt,
	# which lists their files: the game's own depot has its folder's gameinfo.txt
	listing=$(mktemp -d)
	download -app "$app" -os linux -manifest-only -dir "$listing"
	for list in "$listing"/manifest_*_*.txt; do
		[[ -f $list ]] || continue
		line=$(basename "$list" .txt)
		line=${line#manifest_}
		depot=${line%%_*} manifest=${line#*_}
		if grep -q -E " $game/gameinfo\.txt$" "$list"; then
			content="$depot $manifest"
		else
			depots+=("$depot $manifest")
		fi
	done
	rm -rf "$listing"
	if [[ -z $content ]]; then
		echo "Error: no depot of app $app has $game/gameinfo.txt" >&2
		return 1
	fi
	depots+=("$content")

	mkdir -p "$state/depots" "$state/$game"
	# SteamCMD's install, before the depots: the game's depot to be, checked file by file
	old=$state/$game/game
	local -a validate=()
	if [[ -d $old && ! -L $old && ! -e $state/depots/${content%% *} ]]; then
		rm -rf "$old/steamapps"
		mv "$old" "$state/depots/${content%% *}"
		validate=(-validate)
	fi
	for line in "${depots[@]}"; do
		depot=${line%% *} manifest=${line#* }
		download -app "$app" -os linux -depot "$depot" -manifest "$manifest" -dir "$state/depots/$depot" \
			"${validate[@]}"
	done
	printf '%s\n' "${depots[@]}" >"$state/$game/depots"
	ln -sfn "../depots/${content%% *}" "$state/$game/game"

	# Remove the shipped, outdated C++ runtime, so the system's is used instead, and libogg and
	# libvorbis, which no library of the game loads (the engine has its own Vorbis decoder): the
	# server puts bin/ on LD_LIBRARY_PATH, where they could take the place of the system's
	rm -f "$state/$game/game"/bin/{libgcc_s.so.1,libstdc++.so.6,libogg.so,libvorbis.so}
}

# The game only downloads an item once and never updates it; DepotDownloader gets its current version.
# Items that fail to download are kept as they were.
update_workshop() {
	local workshop=$2 app='' line_app item content listing
	local -a items=() failed=()
	# "<app> <item>" a line, the app being the workshop's, the same for all. Kept apart from the loop's
	# variables, which read empties at the end of the list.
	listing=$(python3 "$tools/games.py" items "$1")
	while read -r line_app item; do
		[[ -n $item ]] || continue
		app=$line_app
		items+=("$item")
	done <<<"$listing"
	# Also without items, as the servers mount it
	mkdir -p "$workshop/steamapps/workshop"
	local folder
	local -a validate
	for item in "${items[@]}"; do
		folder=$workshop/steamapps/workshop/content/$app/$item
		# An item SteamCMD downloaded, without DepotDownloader's record: checked file by file
		validate=()
		if [[ -d $folder && ! -d $folder/.DepotDownloader ]]; then
			validate=(-validate)
		fi
		download -app "$app" -pubfile "$item" -dir "$folder" "${validate[@]}" || failed+=("$item")
	done
	if ((${#failed[@]})); then
		echo "Warning: workshop items not updated, kept as they were: ${failed[*]}" >&2
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
	# The record of the items, which the game checks before downloading them itself
	if [[ -n $app ]]; then
		python3 "$tools/games.py" workshop-record "$workshop" "$app"
	fi
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
			echo "Usage: $0 [--game GAME STATE] [--workshop GAME DIR] [--plugins DIR] [--check-gamedata DIR]" >&2
			exit 2
			;;
	esac
done
