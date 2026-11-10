#!/bin/bash
# Prints the class path of Ghidra's jars, which the scripts of this folder are compiled and linted
# against (the javac and pmd hooks of .pre-commit-config.yaml). GHIDRA_INSTALL_DIR is Ghidra's folder,
# /opt/ghidra by default.
set -euo pipefail

ghidra=${GHIDRA_INSTALL_DIR:-/opt/ghidra}
if [[ ! -d $ghidra/Ghidra ]]; then
	echo "Error: no Ghidra in $ghidra, install ghidra or set GHIDRA_INSTALL_DIR" >&2
	exit 1
fi
find "$ghidra/Ghidra" -path '*/lib/*.jar' | sort | paste -sd :
