# Installs the tools and the systemd units of the servers, for a package (deploy/arch/PKGBUILD) or by
# hand: make install DESTDIR=… PREFIX=/usr. The configs aren't installed: the tools read them from the
# servers' clone of this repository, /var/lib/nwi-server/config (NWI_CONFIG, see tools/games.py).
# See README.md.

PREFIX ?= /usr
BINDIR ?= $(PREFIX)/bin
LIBDIR ?= $(PREFIX)/lib
DATADIR ?= $(PREFIX)/share
# The tools' folder, which the units run them from
TOOLSDIR = $(LIBDIR)/nwi-server-kit

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
	# The admins' RCON client
	install -dm755 "$(DESTDIR)$(BINDIR)"
	ln -sf "$(TOOLSDIR)/rcon.py" "$(DESTDIR)$(BINDIR)/nwi-rcon"
	install -dm755 "$(DESTDIR)$(LIBDIR)/systemd/system"
	for unit in $(UNITS); do \
		sed 's|/usr/lib/nwi-server-kit/|$(TOOLSDIR)/|g' "$$unit" \
			>"$(DESTDIR)$(LIBDIR)/systemd/system/$${unit##*/}" || exit; \
	done
	install -Dm644 deploy/sysusers.d/nwi-server.conf "$(DESTDIR)$(LIBDIR)/sysusers.d/nwi-server.conf"
	# Copied into ~/.config by whoever runs the containers: in Podman's folders, they'd be every user's
	install -Dm644 -t "$(DESTDIR)$(DATADIR)/nwi-server-kit/quadlet" $(QUADLET)
	install -Dm644 -t "$(DESTDIR)$(DATADIR)/doc/nwi-server-kit" $(DOCS)

uninstall:
	rm -rf "$(DESTDIR)$(LIBDIR)/nwi-server-kit" "$(DESTDIR)$(DATADIR)/nwi-server-kit" \
		"$(DESTDIR)$(DATADIR)/doc/nwi-server-kit"
	rm -f $(addprefix "$(DESTDIR)$(LIBDIR)/systemd/system/,$(addsuffix ",$(notdir $(UNITS)))) \
		"$(DESTDIR)$(LIBDIR)/sysusers.d/nwi-server.conf" "$(DESTDIR)$(BINDIR)/nwi-rcon"

# The checks of the git hooks on all files (CONTRIBUTING.md)
check:
	prek run --all-files
