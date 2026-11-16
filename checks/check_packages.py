#!/usr/bin/env python3
"""Check that the container image installs the packages the systemd units' package needs.

The package (deploy/arch/PKGBUILD) and the image (deploy/container/Containerfile) run the same tools,
so they need the same packages:

- every dependency of the package is installed in the image, but those the image doesn't need or has
  without asking (EXCEPTIONS, with why),
- every package the image installs is a dependency or an optional dependency of the package, but the
  game's 32-bit libraries (lib32-*), which only the servers need: the game's own and those of
  SourceMod's extensions, as sourcemod's optional dependencies have them.

Usage: check_packages.py   (in the repository; exit status 1 on findings)
"""

import re
import shlex
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PKGBUILD = REPO / "deploy/arch/PKGBUILD"
CONTAINERFILE = REPO / "deploy/container/Containerfile"

# The package's dependencies the image doesn't install itself, and why
EXCEPTIONS = {
    "bash": "the base image's, of the base package",
    "util-linux": "the base image's, of the base package",
    "git": "the image's updates take the image's configs (nwi-server update --image), no clone",
}


def bash_array(text: str, name: str) -> list[str]:
    """The words of a bash array of a PKGBUILD, NAME=( … ), its comments left out: on one line, or
    with the closing parenthesis on a line of its own, as descriptions may have parentheses."""
    match = re.search(
        rf"^{name}=\(([^\n]*?)\)$|^{name}=\((.*?)^\)", text, re.MULTILINE | re.DOTALL
    )
    if match is None:
        raise ValueError(f"{PKGBUILD.name} has no {name}")
    return shlex.split(match.group(1) or match.group(2), comments=True)


def package_name(entry: str) -> str:
    """The name of a dependency, without its version (python>=3.12) or description (optdepends)."""
    return re.split(r"[<>=:]", entry, maxsplit=1)[0].strip()


def pkgbuild_packages(text: str) -> tuple[set[str], set[str]]:
    """The dependencies and the optional dependencies of a PKGBUILD."""
    depends = {package_name(entry) for entry in bash_array(text, "depends")}
    optdepends = {package_name(entry) for entry in bash_array(text, "optdepends")}
    return depends, optdepends


def image_packages(text: str) -> set[str]:
    """The packages a Containerfile installs with pacman -S, in any of its RUN instructions."""
    joined = re.sub(r"\\\n", " ", text)
    packages: set[str] = set()
    for line in joined.splitlines():
        if not line.startswith("RUN "):
            continue
        # The shell's words, with its operators (&&, ;, |) as words of their own, but not those quoted
        lexer = shlex.shlex(
            line.removeprefix("RUN "), posix=True, punctuation_chars=True
        )
        lexer.whitespace_split = True
        command: list[str] = []
        for word in [*lexer, ";"]:
            if word.strip("&|;()<>"):
                command.append(word)
                continue
            if (
                command[:1] == ["pacman"]
                and command[1:2]
                and command[1].startswith("-S")
            ):
                packages |= {word for word in command[2:] if not word.startswith("-")}
            command = []
    return packages


def check(pkgbuild: str, containerfile: str) -> list[str]:
    """The findings, see the module's documentation."""
    depends, optdepends = pkgbuild_packages(pkgbuild)
    image = image_packages(containerfile)
    findings = [
        f"{name}, a dependency of the package, isn't installed in the image"
        for name in sorted(depends - image - EXCEPTIONS.keys())
    ]
    findings += [
        f"{name} is installed in the image, but isn't a dependency of the package"
        for name in sorted(image - depends - optdepends)
        if not name.startswith("lib32-")
    ]
    findings += [
        f"{name} is an exception, but the image installs it"
        for name in sorted(image & EXCEPTIONS.keys())
    ]
    findings += [
        f"{name} is an exception, but no dependency of the package"
        for name in sorted(EXCEPTIONS.keys() - depends)
    ]
    return findings


def main() -> int:
    findings = check(PKGBUILD.read_text(), CONTAINERFILE.read_text())
    for finding in findings:
        print(f"{CONTAINERFILE.relative_to(REPO)}: {finding}", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
