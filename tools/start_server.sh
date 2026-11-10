#!/bin/bash
# Starts a server, prepared by prepare_server.sh, under srcds_watchdog.py: for doi-server@.service and the
# container's entrypoint, which share the command line this way.
#
#   start_server.sh ROOT   start the server of ROOT (srcds_linux there), with the settings of its
#                          ROOT/doi/server.toml (tools/server_config.py: the slots, LAN or not, the
#                          workshop, the first map, the theater and more options) and its environment
#                          file's
#
# SERVER_PORT, TV_PORT, CLIENT_PORT, SERVER_PASSWORD: the server's ports and password, from its
# environment file (/etc/doi-server/<server>.env)
# DOI_PATCH: the patcher of the server library to preload into srcds (tools/doi_patch.c, built as
# doi_patch.so), which applies patches/server_srv.patches; without it, srcds runs unpatched
# SANITISER: undefined, address or address,undefined, for a server with test builds of SourceMod and
# Metamod:Source with these sanitisers (./aur-packages build --sanitize of the AUR packages, see
# README.md): their 32-bit runtime of compiler-rt is preloaded into srcds too, and they report to the
# server's output with stack traces (UBSAN_OPTIONS and ASAN_OPTIONS, unless they're set)
set -euo pipefail

repo=$(realpath "$(dirname "${BASH_SOURCE[0]}")/..")
root=$1

# The options of server.toml, one per line
options=$(python3 "$repo/tools/server_config.py" args "$root")
mapfile -t settings <<<"$options"

# Preloaded into srcds only, as srcds_watchdog.py is a 64-bit Python: the sanitisers' runtime first, as
# ASan requires, then the patcher
libraries=() preload=()
if [[ -n ${SANITISER:-} ]]; then
	case $SANITISER in
		undefined) runtime=libclang_rt.ubsan_standalone.so ;;
		address | address,undefined | undefined,address) runtime=libclang_rt.asan.so ;;
		*)
			echo "Error: unknown SANITISER $SANITISER (undefined, address or address,undefined)" >&2
			exit 1
			;;
	esac
	runtimes=(/usr/lib/clang/*/lib/i386-pc-linux-gnu/"$runtime")
	if [[ ! -r ${runtimes[-1]} ]]; then
		echo "Error: no $runtime of compiler-rt for 32-bit x86" >&2
		exit 1
	fi
	libraries+=("${runtimes[-1]}")
	export UBSAN_OPTIONS=${UBSAN_OPTIONS:-print_stacktrace=1:report_error_type=1}
	export ASAN_OPTIONS=${ASAN_OPTIONS:-print_stacktrace=1:detect_leaks=1}
fi
if [[ -n ${DOI_PATCH:-} ]]; then
	if [[ ! -r $DOI_PATCH ]]; then
		echo "Error: no patcher at $DOI_PATCH, which the update builds" >&2
		exit 1
	fi
	libraries+=("$DOI_PATCH")
	preload+=(DOI_PATCH_LIST="$repo/patches/server_srv.patches")
fi
if ((${#libraries[@]})); then
	preload+=(LD_PRELOAD="$(
		IFS=:
		echo "${libraries[*]}"
	)")
fi

exec python3 "$repo/tools/srcds_watchdog.py" -- env "${preload[@]}" "$root/srcds_linux" -game doi -usercon \
	-port "${SERVER_PORT:-27015}" +tv_port "${TV_PORT:-27020}" +clientport "${CLIENT_PORT:-27005}" \
	+r_hunkalloclightmaps 0 +sv_password "${SERVER_PASSWORD:-}" "${settings[@]}"
