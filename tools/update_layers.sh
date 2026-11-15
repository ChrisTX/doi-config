#!/bin/bash
# Updates the layers the servers share in the state folder STATE (/var/lib/nwi-server): this
# repository's clone and the compiled plugins, and of each game of the servers (tools/games.py) its
# install, its servers' workshop items and the mods made for it, in STATE/<game>/game,
# STATE/<game>/workshop and STATE/<game>/mods. The layers mustn't change while servers run on them, so
# an update while they run goes into a copy:
#
#   update_layers.sh --stage STATE  update a copy of the layers in STATE/next, while the servers run:
#                                   a reflinked copy (btrfs, XFS), which shares the data of the files
#                                   with the layers, so it only takes the space of what the update
#                                   changes, and the running servers' files stay as they are
#   update_layers.sh STATE          with the servers stopped: put a complete STATE/next in place,
#                                   keeping the layers it replaces in STATE/previous, or without one,
#                                   update the layers in place
#
# The tools are those this script is with, the configs those of the clone, STATE/config, which is
# pulled first (NWI_CONFIG of the tools, see tools/games.py). With --image first, for the container
# image (deploy/container), the layers are only the games': the configs and the plugins are the
# image's, the repository this script is in.
#
# With --image, each server gets links to its game's layers, STATE/servers/<server>/{game,workshop,mods},
# which the containers of deploy/quadlet mount, as a unit can't pick the folders by the server's game.
# The systemd units' tools/mount_server.sh picks them itself, and STATE/servers is root's there.
#
# nwi-restart.service stages, stops the servers, runs nwi-update.service, which runs this without
# --stage, and starts them again: the servers are only down for the restart. At boot, nwi-update.service
# updates in place, before the servers start.
set -euo pipefail

tools=$(realpath "$(dirname "${BASH_SOURCE[0]}")")

# The layers all games share, as the units and tools/mount_server.sh name them in STATE; each game's
# are in STATE/<game>
shared=(config plugins)
image=
if [[ ${1:-} == --image ]]; then
	shared=()
	image=$(realpath "$(dirname "${BASH_SOURCE[0]}")/..")
	shift
fi

# The layers of Day of Infamy were in STATE itself, before there were others
migrate() {
	local dir=$1 layer
	[[ -d $dir/game && ! -e $dir/doi ]] || return 0
	mkdir "$dir/doi"
	for layer in game workshop mods; do
		if [[ -e $dir/$layer ]]; then
			mv "$dir/$layer" "$dir/doi/"
		fi
	done
}

# The update of the layers in DIR, with the configs of the clone in DIR once it's pulled, or those of
# the image. With FROM, the layers of a game that DIR doesn't have yet are reflinked from there first.
update() {
	local dir=$1 from=${2:-} used game
	local -a games
	export NWI_CONFIG=${image:-$1/config}
	if [[ -z $image ]]; then
		git -C "$NWI_CONFIG" pull --ff-only
		"$tools/update_game.sh" --plugins "$dir/plugins"
	fi
	used=$(python3 "$tools/games.py" used)
	mapfile -t games <<<"$used"
	for game in "${games[@]}"; do
		if [[ -n $from && -e $from/$game && ! -e $dir/$game ]]; then
			cp -a --reflink=always "$from/$game" "$dir/"
		fi
		mkdir -p "$dir/$game"
		"$tools/update_game.sh" --game "$game" "$dir/$game/game" \
			--workshop "$game" "$dir/$game/workshop" --check-gamedata "$dir/$game/game"
		# The mods of mods/<game>, an empty layer for a game without. First the map scripts of the game and
		# the workshop items, which the mods are made from: the log lists those whose braces are repaired,
		# or can't be, which a mod's fix table repairs. Broken ones don't fail the update, as the servers
		# run without the maps.
		if [[ -d $NWI_CONFIG/mods/$game ]]; then
			python3 "$tools/make_mods.py" --game "$dir/$game/game" --workshop "$dir/$game/workshop" --check ||
				echo "Warning: map scripts of $game that can't be repaired, see above" >&2
			python3 "$tools/make_mods.py" --game "$dir/$game/game" --workshop "$dir/$game/workshop" \
				"$dir/$game/mods" "$NWI_CONFIG/mods/$game"
		else
			rm -rf "$dir/$game/mods"
			mkdir "$dir/$game/mods"
		fi
	done
}

# The servers' links to their games' layers
link_servers() {
	local state=$1 used names game name layer
	local -a games servers
	export NWI_CONFIG=${image:-$1/config}
	used=$(python3 "$tools/games.py" used)
	mapfile -t games <<<"$used"
	for game in "${games[@]}"; do
		names=$(python3 "$tools/games.py" servers "$game")
		mapfile -t servers <<<"$names"
		for name in "${servers[@]}"; do
			[[ -n $name ]] || continue
			mkdir -p "$state/servers/$name"
			for layer in game workshop mods; do
				ln -sfn "../../$game/$layer" "$state/servers/$name/$layer"
			done
		done
	done
}

stage() {
	local state=$1 next=$1/next layer
	rm -rf "$next"
	mkdir "$next"
	for layer in "${shared[@]}"; do
		if [[ -e $state/$layer ]]; then
			cp -a --reflink=always "$state/$layer" "$next/"
		fi
	done
	update "$next" "$state"
	# Only a complete update is put in place
	touch "$next/.complete"
	echo "Staged the update in $next"
}

# The staged layers in place: the shared ones and the games' folders
swap() {
	local state=$1 next=$1/next layer
	rm -rf "$state/previous"
	mkdir "$state/previous"
	for layer in "$next"/*; do
		layer=$(basename "$layer")
		if [[ -e $state/$layer ]]; then
			mv "$state/$layer" "$state/previous/"
		fi
		mv "$next/$layer" "$state/"
	done
	rm -rf "$next"
	echo "Put the staged update in place, the layers it replaced are in $state/previous"
}

case ${1:-} in
	--stage)
		state=${2:?Usage: $0 [--image] [--stage] STATE}
		migrate "$state"
		stage "$state"
		;;
	-*)
		echo "Usage: $0 [--image] [--stage] STATE" >&2
		exit 2
		;;
	*)
		state=${1:?Usage: $0 [--image] [--stage] STATE}
		migrate "$state"
		if [[ -f $state/next/.complete ]]; then
			migrate "$state/next"
			swap "$state"
		else
			# An incomplete stage, e.g. one that was stopped, is of no use
			rm -rf "$state/next"
			update "$state"
		fi
		if [[ -n $image ]]; then
			link_servers "$state"
		fi
		;;
esac
