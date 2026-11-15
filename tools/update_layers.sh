#!/bin/bash
# Updates the layers the servers share in the state folder STATE (/var/lib/nwi-server/layers): the
# clones of the servers' config sources and the plugins compiled of each, the depots of the games of
# the servers (tools/games.py), which they share, and of each game its servers' workshop items and the
# mods made for it of each source, in STATE/configs/<source>, STATE/plugins/<source>,
# STATE/depots/<depot>, STATE/<game>/workshop and STATE/<game>/mods/<source>; STATE/<game>/depots lists
# a game's depots, and STATE/<game>/game links to its own (tools/update_game.sh). The layers mustn't change while servers run on them, so an update
# while they run goes into a copy:
#
#   update_layers.sh --stage STATE  update a copy of the layers in STATE/next, while the servers run:
#                                   a reflinked copy (btrfs, XFS), which shares the data of the files
#                                   with the layers, so it only takes the space of what the update
#                                   changes, and the running servers' files stay as they are
#   update_layers.sh STATE          with the servers stopped: put a complete STATE/next in place,
#                                   keeping the layers it replaces in STATE/previous, or without one,
#                                   update the layers in place
#
# A config source's clone is made of its repository (URL of /etc/nwi-server/configs/<source>.env) if
# it's missing, and brought to its branch or tag (REF), or pulled without one. The tools are those this
# script is with. With --image first, for the container image (deploy/container), the layers are only
# the games', of one source, the configs and the plugins of the image, the repository this script is
# in.
#
# With --image, each server gets links to its game's layers and list of depots,
# STATE/servers/<server>/{game,workshop,mods,depots}, which the containers of deploy/quadlet mount, as a
# unit can't pick the folders by the server's game.
# The systemd units' tools/mount_server.sh picks them itself, and STATE/servers is root's there.
#
# nwi-restart.service stages, stops the servers, runs nwi-update.service, which runs this without
# --stage, and starts them again: the servers are only down for the restart. At boot, nwi-update.service
# updates in place, before the servers start.
set -euo pipefail

tools=$(realpath "$(dirname "${BASH_SOURCE[0]}")")

# The layers all games share, as the units and tools/mount_server.sh name them in STATE; each game's
# are in STATE/<game>
shared=(configs plugins depots)
image=
if [[ ${1:-} == --image ]]; then
	shared=(depots)
	image=$(realpath "$(dirname "${BASH_SOURCE[0]}")/..")
	shift
fi

# Earlier layouts: the layers of Day of Infamy in STATE itself, before there were other games; one clone
# of the configs, STATE/config, and the plugins and the mods made of it, before there were sources.
# Plugins and mods are made anew anyway.
migrate() {
	local dir=$1 layer mods
	if [[ -d $dir/game && ! -e $dir/doi ]]; then
		mkdir "$dir/doi"
		for layer in game workshop mods; do
			if [[ -e $dir/$layer ]]; then
				mv "$dir/$layer" "$dir/doi/"
			fi
		done
	fi
	if [[ -d $dir/config && ! -e $dir/configs ]]; then
		mkdir "$dir/configs"
		mv "$dir/config" "$dir/configs/default"
	fi
	if [[ -d $dir/plugins/addons ]]; then
		rm -rf "$dir/plugins"
	fi
	for mods in "$dir"/*/mods; do
		if [[ -d $mods/cfg || -d $mods/custom ]]; then
			rm -rf "$mods"
		fi
	done
}

# A config source's clone in DIR/configs: made of its repository if it's missing, brought to its branch
# or tag, or pulled without one
sync_source() {
	local clone=$1/configs/$2 settings url ref
	local -a lines
	settings=$(python3 "$tools/games.py" source "$2")
	mapfile -t lines <<<"$settings"
	url=${lines[0]:-} ref=${lines[1]:-}
	if [[ ! -d $clone/.git ]]; then
		if [[ -z $url ]]; then
			echo "Error: the config source $2 has neither a clone, $clone, nor a repository (URL)" >&2
			return 1
		fi
		mkdir -p "$1/configs"
		git clone --quiet "$url" "$clone"
	elif [[ -n $url ]]; then
		git -C "$clone" remote set-url origin "$url"
	fi
	if [[ -z $ref ]]; then
		git -C "$clone" pull --quiet --ff-only
		return
	fi
	git -C "$clone" fetch --quiet --tags --prune origin
	if git -C "$clone" rev-parse --verify --quiet "refs/remotes/origin/$ref" >/dev/null; then
		git -C "$clone" checkout --quiet --detach "origin/$ref"
	else
		git -C "$clone" checkout --quiet --detach "refs/tags/$ref"
	fi
}

# The update of the layers in DIR, with the configs of the clones in DIR once they're synced, or those of
# the image. With FROM, the layers of a game that DIR doesn't have yet are reflinked from there first.
update() {
	local dir=$1 from=${2:-} listing game source configs
	local -a sources games game_sources
	if [[ -n $image ]]; then
		export NWI_CONFIG=$image
	else
		export NWI_LAYERS=$dir
		listing=$(python3 "$tools/games.py" sources)
		mapfile -t sources <<<"$listing"
		for source in "${sources[@]}"; do
			sync_source "$dir" "$source"
			NWI_CONFIG=$dir/configs/$source "$tools/update_game.sh" --plugins "$dir/plugins/$source"
		done
	fi
	listing=$(python3 "$tools/games.py" used)
	mapfile -t games <<<"$listing"
	for game in "${games[@]}"; do
		if [[ -n $from && -e $from/$game && ! -e $dir/$game ]]; then
			cp -a --reflink=always "$from/$game" "$dir/"
		fi
		mkdir -p "$dir/$game"
		"$tools/update_game.sh" --game "$game" "$dir" --workshop "$game" "$dir/$game/workshop"
		listing=$(python3 "$tools/games.py" sources "$game")
		mapfile -t game_sources <<<"$listing"
		rm -rf "$dir/$game/mods"
		mkdir "$dir/$game/mods"
		for source in "${game_sources[@]}"; do
			[[ -n $source ]] || continue
			configs=$(python3 "$tools/games.py" config "$source")
			# The source's plugins' gamedata against the game
			NWI_CONFIG=$configs "$tools/update_game.sh" --check-gamedata "$dir/$game/game"
			# The source's mods of mods/<game>, an empty layer without. First the map scripts of the game
			# and the workshop items, which the mods are made from: the log lists those whose braces are
			# repaired, or can't be, which a mod's fix table repairs. Broken ones don't fail the update,
			# as the servers run without the maps.
			if [[ -d $configs/mods/$game ]]; then
				python3 "$tools/make_mods.py" --game "$dir/$game/game" --workshop "$dir/$game/workshop" --check ||
					echo "Warning: map scripts of $game that can't be repaired, see above" >&2
				python3 "$tools/make_mods.py" --game "$dir/$game/game" --workshop "$dir/$game/workshop" \
					"$dir/$game/mods/$source" "$configs/mods/$game"
			else
				mkdir "$dir/$game/mods/$source"
			fi
		done
	done
}

# The servers' links to their games' layers
link_servers() {
	local state=$1 used names game name
	local -a games servers
	export NWI_CONFIG=$image
	used=$(python3 "$tools/games.py" used)
	mapfile -t games <<<"$used"
	for game in "${games[@]}"; do
		names=$(python3 "$tools/games.py" servers "$game")
		mapfile -t servers <<<"$names"
		for name in "${servers[@]}"; do
			[[ -n $name ]] || continue
			mkdir -p "$state/servers/$name"
			ln -sfn "../../$game/game" "$state/servers/$name/game"
			ln -sfn "../../$game/workshop" "$state/servers/$name/workshop"
			ln -sfn "../../$game/depots" "$state/servers/$name/depots"
			# The image's one source
			ln -sfn "../../$game/mods/default" "$state/servers/$name/mods"
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
