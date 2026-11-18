#!/usr/bin/env bash
# SPDX-FileCopyrightText: Christian Pfeiffer
# SPDX-License-Identifier: MIT

# Drops the console commands a malicious Steam invite can smuggle onto the game's command line (see
# client/README.md), then starts the game with the rest. Day of Infamy and Insurgency take +commands
# from their command line, and an invite's connect string is appended to it, so an invite can point
# the client's RCON client at a server of the attacker's (+rcon_address, +rcon) or write to the
# client's config (+host_writeconfig). This wrapper removes those, as a client never needs them, and
# passes everything else on, +connect included, so invites and the launch options still work.
#
# Set it as the game's launch options in Steam (Properties, General), with %command% after it:
#     /path/to/safe-launch.sh %command%
# NWI_SAFE_LAUNCH_LOG names a file to append what it drops to, for a look afterwards.

set -euo pipefail

# The +commands a client never needs, which an invite abuses, without their + and in lower case. A
# denied +command and its arguments, up to the next +command or -option, are dropped.
denied=(
	rcon
	rcon_address
	rcon_password
	rcon_port
	host_writeconfig
	host_writeconfig_ss
	alias
)

is_denied() {
	local name
	for name in "${denied[@]}"; do
		[[ "$1" == "$name" ]] && return 0
	done
	return 1
}

keep=()
dropped=()
dropping=false
for token in "$@"; do
	case "$token" in
		+*)
			dropping=false
			name="${token#+}"
			if is_denied "${name,,}"; then
				dropping=true
				dropped+=("$token")
				continue
			fi
			keep+=("$token")
			;;
		-*)
			dropping=false
			keep+=("$token")
			;;
		*)
			if "$dropping"; then
				dropped+=("$token")
			else
				keep+=("$token")
			fi
			;;
	esac
done

if [[ ${#dropped[@]} -gt 0 ]]; then
	message="safe-launch dropped: ${dropped[*]}"
	printf '%s\n' "$message" >&2
	if [[ -n "${NWI_SAFE_LAUNCH_LOG:-}" ]]; then
		printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$message" >>"$NWI_SAFE_LAUNCH_LOG"
	fi
fi

exec "${keep[@]}"
