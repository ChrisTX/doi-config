#!/bin/bash
# Checks the summary of a commit message against CONTRIBUTING.md: "<scope>: <Summary>", the scope a file or
# folder of the repository (its name, or its name without the extension, in any case) or one of the areas
# below, the summary starting with a capital letter, without a trailing period. Run by the commit-msg hook.
# $1: the file of the commit message
set -euo pipefail

# The scopes that aren't a single file or folder. Where a path fits, it's the scope instead, e.g.
# nwi_difficulty_scaler rather than DS, mods for the mods.
areas=(
	# The configs of a game mode, across the cfg files and the servers
	Coop
	PVP
	Private
	# SourceTV's settings
	STV
	# Texts across the repository, like the British English of CONTRIBUTING.md
	Texts
	# The layout of the repository
	Repository
	# The checks as a whole: the hooks, their settings and GitHub Actions
	Checks
)

# The first line that isn't empty or a comment, git strips those afterwards
summary=$(grep -v -m1 -e '^#' -e '^[[:space:]]*$' "$1" || true)
case $summary in
	# Written by git
	'Merge '* | 'Revert "'* | 'fixup! '* | 'squash! '* | 'amend! '*)
		exit 0
		;;
esac

if [[ ! $summary =~ ^([^\ :]+):\ (.*)$ ]]; then
	echo "The summary has to be '<scope>: <Summary>', see CONTRIBUTING.md: $summary" >&2
	exit 1
fi
scope=${BASH_REMATCH[1]}
text=${BASH_REMATCH[2]}

known=false
for area in "${areas[@]}"; do
	[[ ${scope,,} == "${area,,}" ]] && known=true
done
if [[ $known == false ]]; then
	# Every part of the paths of the staged files and of HEAD's, which removed files are still in
	while IFS= read -r name; do
		name=${name,,}
		if [[ ${scope,,} == "$name" || ${scope,,} == "${name%.*}" ]]; then
			known=true
			break
		fi
	done < <({
		git ls-files
		git ls-tree -r --name-only HEAD 2>/dev/null || true
	} | tr / '\n' | sort -u)
fi
if [[ $known == false ]]; then
	echo "The scope '$scope' is neither a file or folder of the repository nor an area of tools/check_commit_msg.sh" >&2
	exit 1
fi

if [[ ! $text =~ ^[[:upper:]] ]]; then
	echo "The summary has to start with a capital letter: $summary" >&2
	exit 1
fi
if [[ $text == *. ]]; then
	echo "The summary has to end without a period: $summary" >&2
	exit 1
fi
