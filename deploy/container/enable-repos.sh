#!/bin/bash
# Enables multilib in the image's pacman.conf, and with an argument (any value) Arch Linux's testing
# repositories too, each before the repository it tests, for packages built against them
set -euo pipefail

if [[ -n ${1:-} ]]; then
	sed -i '/^#\[\(core\|extra\)-testing\]$/,/^#Include/ s/^#//' /etc/pacman.conf
	printf '\n[multilib-testing]\nInclude = /etc/pacman.d/mirrorlist\n' >>/etc/pacman.conf
fi
printf '\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n' >>/etc/pacman.conf
