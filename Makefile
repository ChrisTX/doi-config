# Installs the tools and the systemd units of the servers, for a package (deploy/arch/PKGBUILD) or by
# hand: make install DESTDIR=… PREFIX=/usr, with the Python package nwi_server_kit and its command
# nwi-server (pyproject.toml), which make builds first. The configs aren't installed: the tools read them from the
# servers' config sources, which the updater keeps (nwi_server_kit.games).
# See docs/kit/Systemd.md.

PREFIX ?= /usr
LIBDIR ?= $(PREFIX)/lib
DATADIR ?= $(PREFIX)/share
# The checks (checks/) and the tests (tests/) aren't installed: they're for this repository
UNITS = $(wildcard deploy/systemd/*)
# The user units of a player's machine: the scan of the game client's workshop items
USER_UNITS = $(wildcard deploy/systemd-user/*)
QUADLET = $(wildcard deploy/quadlet/*)
# The book (docs/) is installed with its folders, which its links need
DOCS = README.md CONTRIBUTING.md $(shell find docs -name '*.md')

.PHONY: all install uninstall check

# The package's wheel, built without isolation from the system's hatchling, as for Arch Linux packages
all:
	python -m build --wheel --no-isolation --outdir dist

install:
	python -m installer --destdir="$(DESTDIR)" --prefix="$(PREFIX)" dist/*.whl
	install -Dm644 -t "$(DESTDIR)$(LIBDIR)/systemd/system" $(UNITS)
	install -Dm644 -t "$(DESTDIR)$(LIBDIR)/systemd/user" $(USER_UNITS)
	install -Dm644 deploy/sysusers.d/nwi-server.conf "$(DESTDIR)$(LIBDIR)/sysusers.d/nwi-server.conf"
	# Copied into ~/.config by whoever runs the containers: in Podman's folders, they'd be every user's
	install -Dm644 -t "$(DESTDIR)$(DATADIR)/nwi-server-kit/quadlet" $(QUADLET)
	for file in $(DOCS); do install -Dm644 "$$file" "$(DESTDIR)$(DATADIR)/doc/nwi-server-kit/$$file"; done

uninstall:
	rm -rf "$(DESTDIR)$(DATADIR)/nwi-server-kit" \
		"$(DESTDIR)$(DATADIR)/doc/nwi-server-kit"
	rm -f $(addprefix "$(DESTDIR)$(LIBDIR)/systemd/system/,$(addsuffix ",$(notdir $(UNITS)))) \
		$(addprefix "$(DESTDIR)$(LIBDIR)/systemd/user/,$(addsuffix ",$(notdir $(USER_UNITS)))) \
		"$(DESTDIR)$(LIBDIR)/sysusers.d/nwi-server.conf"

# The checks of the git hooks on all files (CONTRIBUTING.md)
check:
	prek run --all-files
