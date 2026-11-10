#!/bin/bash
# Prints the map of a library's functions for ApplySdkTypes.java: "<address> <mangled name>" per line,
# from its symbol table, at the addresses Ghidra loads it at (image base 0x10000 for 32-bit shared
# libraries, 0x100000 for 64-bit ones, or --base).
#   symbol_map.sh [--base ADDRESS] LIBRARY
set -euo pipefail

base=''
if [[ "${1:-}" == --base ]]; then
	base=$2
	shift 2
fi
if (($# != 1)); then
	echo "Usage: symbol_map.sh [--base ADDRESS] LIBRARY" >&2
	exit 1
fi
if [[ -z "$base" ]]; then
	case "$(od -An -tx1 -j4 -N1 "$1" | tr -d ' ')" in
		01) base=0x10000 ;;
		02) base=0x100000 ;;
		*)
			echo "Not an ELF file: $1" >&2
			exit 1
			;;
	esac
fi
nm --defined-only "$1" | awk -v base="$((base))" '$2 ~ /[tTwW]/ { printf "%08x %s\n", strtonum("0x" $1) + base, $3 }'
