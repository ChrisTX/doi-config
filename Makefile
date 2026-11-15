# Installs the tools and the systemd units of the servers, for a package (deploy/arch/PKGBUILD) or by
# hand: make install DESTDIR=… PREFIX=/usr. The configs aren't installed: the tools read them from the
# servers' clone of this repository, /var/lib/doi-server/doi-config (DOI_CONFIG, see tools/games.py).
# See README.md.

PREFIX ?= /usr
LIBDIR ?= $(PREFIX)/lib
DATADIR ?= $(PREFIX)/share
# The tools' folder, which the units run them from
TOOLSDIR = $(LIBDIR)/doi-config/tools

# The tools of the servers and of their admins; the checks of this repository's files stay in it
TOOLS = check_gamedata.py check_updates.py dump_cvars.py games.py make_mods.py mount_server.sh \
	prepare_server.sh rcon.py server_config.py soak_watch.py srcds_watchdog.py start_server.sh \
	update_game.sh update_layers.sh
UNITS = $(wildcard deploy/systemd/*)
QUADLET = $(wildcard deploy/quadlet/*)
DOCS = README.md CONTRIBUTING.md docs/Clients.md docs/Cvars.md

.PHONY: all install uninstall check

all:

install:
	install -Dm755 -t "$(DESTDIR)$(TOOLSDIR)" $(addprefix tools/,$(TOOLS))
	install -dm755 "$(DESTDIR)$(LIBDIR)/systemd/system"
	for unit in $(UNITS); do \
		sed 's|/usr/lib/doi-config/tools/|$(TOOLSDIR)/|g' "$$unit" \
			>"$(DESTDIR)$(LIBDIR)/systemd/system/$${unit##*/}" || exit; \
	done
	install -Dm644 deploy/sysusers.d/doi-server.conf "$(DESTDIR)$(LIBDIR)/sysusers.d/doi-server.conf"
	# Copied into ~/.config by whoever runs the containers: in Podman's folders, they'd be every user's
	install -Dm644 -t "$(DESTDIR)$(DATADIR)/doi-config/quadlet" $(QUADLET)
	install -Dm644 -t "$(DESTDIR)$(DATADIR)/doc/doi-config" $(DOCS)

uninstall:
	rm -rf "$(DESTDIR)$(LIBDIR)/doi-config" "$(DESTDIR)$(DATADIR)/doi-config" \
		"$(DESTDIR)$(DATADIR)/doc/doi-config"
	rm -f $(addprefix "$(DESTDIR)$(LIBDIR)/systemd/system/,$(addsuffix ",$(notdir $(UNITS)))) \
		"$(DESTDIR)$(LIBDIR)/sysusers.d/doi-server.conf"

# The checks of the git hooks on all files (CONTRIBUTING.md)
check:
	prek run --all-files
