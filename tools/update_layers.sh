#!/bin/bash
# Updates the layers the servers share in the state folder STATE (/var/lib/doi-server): this
# repository's clone, the game, the workshop items, the compiled plugins, the patcher and the mods. The
# layers mustn't change while servers run on them, so an update while they run goes into a copy:
#
#   update_layers.sh --stage STATE  update a copy of the layers in STATE/next, while the servers run:
#                                   a reflinked copy (btrfs, XFS), which shares the data of the files
#                                   with the layers, so it only takes the space of what the update
#                                   changes, and the running servers' files stay as they are
#   update_layers.sh STATE          with the servers stopped: put a complete STATE/next in place,
#                                   keeping the layers it replaces in STATE/previous, or without one,
#                                   update the layers in place
#
# doi-restart.service stages, stops the servers, runs doi-update.service, which runs this without
# --stage, and starts them again: the servers are only down for the restart. At boot, doi-update.service
# updates in place, before the servers start.
set -euo pipefail

# The layers, as the units and tools/mount_server.sh name them in STATE
layers=(doi-config game workshop plugins mods doi_patch.so)

# The update of the layers in DIR, with the tools of the clone in DIR once it's pulled, as the
# repository may have changed them
update() {
	local dir=$1
	git -C "$dir/doi-config" pull --ff-only
	"$dir/doi-config/tools/update_game.sh" --game "$dir/game" --workshop "$dir/workshop" \
		--plugins "$dir/plugins" --patcher "$dir/doi_patch.so" --check-patches "$dir/game"
	# The map scripts of the game and the workshop items: the log lists those whose braces are repaired,
	# or can't be, which a mod's fix table repairs. Broken ones don't fail the update, as the servers run
	# without the maps.
	python3 "$dir/doi-config/tools/make_mods.py" --game "$dir/game" --workshop "$dir/workshop" --check ||
		echo "Warning: map scripts that can't be repaired, see above" >&2
	python3 "$dir/doi-config/tools/make_mods.py" --game "$dir/game" --workshop "$dir/workshop" \
		"$dir/mods" "$dir/doi-config/mods"
}

stage() {
	local state=$1 next=$1/next layer
	rm -rf "$next"
	mkdir "$next"
	for layer in "${layers[@]}"; do
		if [[ -e $state/$layer ]]; then
			cp -a --reflink=always "$state/$layer" "$next/"
		fi
	done
	update "$next"
	# Only a complete update is put in place
	touch "$next/.complete"
	echo "Staged the update in $next"
}

swap() {
	local state=$1 next=$1/next layer
	rm -rf "$state/previous"
	mkdir "$state/previous"
	for layer in "${layers[@]}"; do
		[[ -e $next/$layer ]] || continue
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
		stage "${2:?Usage: $0 [--stage] STATE}"
		;;
	-*)
		echo "Usage: $0 [--stage] STATE" >&2
		exit 2
		;;
	*)
		state=${1:?Usage: $0 [--stage] STATE}
		if [[ -f $state/next/.complete ]]; then
			swap "$state"
		else
			# An incomplete stage, e.g. one that was stopped, is of no use
			rm -rf "$state/next"
			update "$state"
		fi
		;;
esac
