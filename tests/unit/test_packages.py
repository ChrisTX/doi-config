"""The check of the container image's packages against the package's (checks/check_packages.py)."""

import pytest

from checks import check_packages

PKGBUILD = """\
pkgname=nwi-server-kit-git
depends=(
  bash
  git
  python>=3.12
  # spcomp
  sourcemod-scripting
  util-linux
)
makedepends=(git make)
optdepends=(
  'podman: the container image (deploy/quadlet)'
  'sourcemod-advertisements: the advertisements'
)
"""

CONTAINERFILE = """\
FROM docker.io/library/archlinux:base
RUN pacman -Syu --noconfirm --needed lib32-glibc && pacman -Scc --noconfirm
RUN pacman-key --lsign-key "$(gpg --with-colons x | awk -F: '/^fpr/ { print $10; exit }')" \\
  && pacman -S --needed python sourcemod-scripting \\
    sourcemod-advertisements \\
  && rm -rf /tmp/x
"""


def test_pkgbuild() -> None:
    """Versions, descriptions (with parentheses) and comments left out."""
    depends, optdepends = check_packages.pkgbuild_packages(PKGBUILD)
    assert depends == {"bash", "git", "python", "sourcemod-scripting", "util-linux"}
    assert optdepends == {"podman", "sourcemod-advertisements"}
    assert check_packages.bash_array("arch=(any)\n", "arch") == ["any"]


def test_image() -> None:
    """pacman -S's packages of every RUN, across lines; a quoted ; doesn't end a command."""
    assert check_packages.image_packages(CONTAINERFILE) == {
        "lib32-glibc",
        "python",
        "sourcemod-scripting",
        "sourcemod-advertisements",
    }


def test_matching() -> None:
    assert check_packages.check(PKGBUILD, CONTAINERFILE) == []


@pytest.mark.parametrize(
    ("change", "finding"),
    [
        (
            ("python sourcemod", "sourcemod"),
            "python, a dependency of the package, isn't",
        ),
        (
            ("lib32-glibc", "lib32-glibc steamworks"),
            "steamworks is installed in the image",
        ),
        (
            ("lib32-glibc", "lib32-glibc git"),
            "git is an exception, but the image installs it",
        ),
    ],
)
def test_findings(change: tuple[str, str], finding: str) -> None:
    findings = check_packages.check(PKGBUILD, CONTAINERFILE.replace(*change))
    assert len(findings) == 1 and finding in findings[0]


def test_stale_exception() -> None:
    findings = check_packages.check(PKGBUILD.replace("  bash\n", ""), CONTAINERFILE)
    assert findings == ["bash is an exception, but no dependency of the package"]


def test_repository() -> None:
    """The repository's own files match."""
    assert check_packages.main() == 0
