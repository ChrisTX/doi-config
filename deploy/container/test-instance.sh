#!/bin/bash
# A local test instance of a server in a Podman pod, with a new MariaDB that has SourceBans++'s and
# SourceMod's tables, the server registered in SourceBans++ and optionally an admin. Nothing of it reaches
# the live servers: the passwords are generated, and without its config the Discord forward stays silent.
#
#   build [--testing] build the image (podman build, see README.md) from the local pacman repository;
#                     with --testing with Arch Linux's testing repositories, for packages built against
#                     them, as on a machine that uses them
#   update [--stage]  update the game, the workshop items and the mods of the state folder with the
#                     image's updater (entrypoint.sh update), which the server mounts; the first
#                     downloads the game and the items
#   up [--db-only] [CONFIG]
#                     start the test instance of a config of servers/ (coop-commando by default), anew;
#                     with --db-only only its database, for the systemd units on this machine
#   down              remove the test instance, its database and volumes
#   rcon COMMAND...   run a command on the server over RCON
#   logs              follow the server's log
#
# The local pacman repository with the packages, which aurutils builds into, found like aurutils finds
# it (aur repo --status, or the one file:// repository of pacman.conf without aurutils); its package of
# the SourceBans++ web panel has the tables, and the signature of its database names its key
# AUR_REPO, AUR_DBROOT: the repository's name and folder, as for aurutils
# DOI_TEST_DIR: the test instance's files (${XDG_STATE_HOME:-~/.local/state}/doi-config-test)
# DOI_STATE: the state folder with the game, the workshop items and the mods
# (${XDG_STATE_HOME:-~/.local/state}/doi-server, as for the Quadlet units of deploy/quadlet)
# DISABLE_PLUGINS: plugins the server starts without, by name, e.g. nwi_cvar_unlocker for the game's own
# bounds in tools/dump_cvars.py
# TEST_ADMIN: a SteamID (STEAM_0:…) that gets root admin
# TEST_DB_PORT: the database's port on 127.0.0.1 with --db-only (3306)
# SANITISER: undefined, address or address,undefined: up starts the server from the sanitiser image
# (localhost/doi-server-sanitiser, deploy/container/sanitiser, see README.md), with its runtime preloaded
set -euo pipefail

repo=$(realpath "$(dirname "${BASH_SOURCE[0]}")/../..")
# Set by find_repo
repo_name=''
repo_root=''
dir=${DOI_TEST_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/doi-config-test}
state=${DOI_STATE:-${XDG_STATE_HOME:-$HOME/.local/state}/doi-server}
# The image's user is this one, who owns the state folder
userns=keep-id:uid=1000,gid=1000
image=localhost/doi-server
# The server's image, the sanitiser one with SANITISER
server_image=$image
if [[ -n ${SANITISER:-} ]]; then
	server_image=localhost/doi-server-sanitiser
fi
pod=doi-test
db_port=${TEST_DB_PORT:-3306}
# Set by up --db-only
db_only=

usage() {
	sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed -e '/^set -euo/d' -e 's/^# \?//' >&2
	exit 2
}

# The local repository's name and folder
find_repo() {
	[[ -z $repo_root ]] || return 0
	if command -v aur >/dev/null; then
		local status
		status=$(aur repo --status)
		repo_name=$(sed -n 's/^repo://p' <<<"$status")
		repo_root=$(sed -n 's/^root://p' <<<"$status")
	else
		# The one repository with a file:// server, or the one AUR_REPO names
		local repo server
		local -a repos found=()
		mapfile -t repos < <(pacman-conf --repo-list)
		for repo in "${repos[@]}"; do
			[[ -z ${AUR_REPO:-} || $repo == "$AUR_REPO" ]] || continue
			server=$(pacman-conf --repo="$repo" Server | head -n 1)
			if [[ $server == file://* ]]; then
				found+=("$repo")
				repo_name=$repo
				repo_root=${server#file://}
			fi
		done
		if [[ -n ${AUR_REPO:-} && ${#found[@]} == 0 ]]; then
			echo "Error: pacman.conf has no local (file://) repository $AUR_REPO" >&2
			exit 1
		elif ((${#found[@]} != 1)); then
			echo "Error: ${#found[@]} local repositories in pacman.conf (${found[*]}), name one with AUR_REPO" >&2
			exit 1
		fi
		repo_root=${AUR_DBROOT:-${repo_root%/}}
	fi
	if [[ ! -f $repo_root/$repo_name.db ]]; then
		echo "Error: no database of the repository $repo_name in $repo_root" >&2
		exit 1
	fi
}

# The key the repository's database is signed with
repo_key() {
	local db=$repo_root/$repo_name.db
	gpg --homedir /etc/pacman.d/gnupg --no-permission-warning --status-fd 1 --verify "$db.sig" "$db" 2>/dev/null |
		awk '/^\[GNUPG:\] VALIDSIG/ { print $3; exit }'
}

cmd_build() {
	local -a testing=()
	if [[ ${1:-} == --testing ]]; then
		testing=(--build-arg TESTING=1)
		shift
	fi
	find_repo
	local fingerprint
	fingerprint=$(repo_key)
	if [[ -z $fingerprint ]]; then
		echo "Error: the database of $repo_name in $repo_root has no valid signature" >&2
		exit 1
	fi
	# Global, for the trap, which runs after the function has returned
	key=$(mktemp)
	trap 'rm -f "$key"' EXIT
	gpg --homedir /etc/pacman.d/gnupg --no-permission-warning --export -a "$fingerprint" >"$key"
	podman build --format docker --build-context repo="$repo_root" --secret id=repo-key,src="$key" \
		--build-arg REPO_NAME="$repo_name" "${testing[@]}" -f "$repo/deploy/container/Containerfile" -t "$image" "$repo" "$@"
}

# A config of servers/: its server.toml has the server's settings
check_config() {
	if [[ ! -f $repo/servers/$1/server.toml ]]; then
		echo "Error: no config $1 in servers/" >&2
		exit 1
	fi
}

password() {
	head -c 18 /dev/urandom | base64 | tr -d '/+='
}

# The tables of SourceBans++ (from the web panel's package, its placeholders filled in), SourceMod's
# admins and client preferences (from the image), the test server and the admin
write_database() {
	local package
	find_repo
	package=$(find "$repo_root" -maxdepth 1 -name 'sourcebans-pp-[0-9]*.pkg.tar.zst' | sort -V | tail -1)
	if [[ -z $package ]]; then
		echo "Error: $repo_root has no sourcebans-pp package with SourceBans++'s tables" >&2
		exit 1
	fi
	mkdir -p "$dir/init"
	# One at a time: bsdtar writes several files in the order of the archive, and the tables have to
	# come before their data
	local sql
	for sql in struc.sql data.sql; do
		bsdtar -xOf "$package" "usr/share/sourcebans-pp/install/includes/sql/$sql"
	done | sed -e 's/{prefix}/sb/g' -e 's/{charset}/utf8mb4/g' >"$dir/init/01-sourcebans.sql"
	# SourceMod of the server: the image's, or this machine's for the systemd units
	local scripts=/usr/lib/sourcemod/addons/sourcemod/configs/sql-init-scripts/mysql
	local -a cat=(podman run --rm --entrypoint cat "$image")
	[[ -z $db_only ]] || cat=(cat)
	"${cat[@]}" "$scripts/create_admins.sql" "$scripts/clientprefs-mysql.sql" >"$dir/init/02-sourcemod.sql"
	cat >"$dir/init/03-test.sql" <<-'EOF'
		-- The test server, which SourceBans++ finds by its address (SOURCEBANS_SERVER_IP) and port
		INSERT INTO sb_mods (mid, name, icon, modfolder, steam_universe, enabled) VALUES
		(100, 'Day of Infamy', 'web.png', 'doi', 0, 1);
		INSERT INTO sb_servers (sid, ip, port, rcon, modid, enabled) VALUES (1, '127.0.0.1', 27015, '', 100, 1);
	EOF
	if [[ -n ${TEST_ADMIN:-} ]]; then
		if [[ ! $TEST_ADMIN =~ ^STEAM_[0-5]:[01]:[0-9]+$ ]]; then
			echo "Error: TEST_ADMIN isn't a SteamID like STEAM_0:0:123: $TEST_ADMIN" >&2
			exit 1
		fi
		# Root on the test server for SourceMod and SourceBans++, without a web panel login: the password
		# isn't a hash
		cat >"$dir/init/04-admin.sql" <<-EOF
			INSERT INTO sm_admins (authtype, identity, password, flags, name, immunity) VALUES
			('steam', '$TEST_ADMIN', NULL, 'z', 'Test admin', 100);
			INSERT INTO sb_admins (user, authid, password, gid, email, extraflags, immunity, srv_flags) VALUES
			('Test admin', '$TEST_ADMIN', '!', -1, '', 0, 100, 'z');
			INSERT INTO sb_admins_servers_groups (admin_id, group_id, srv_group_id, server_id)
			SELECT aid, 0, -1, 1 FROM sb_admins WHERE authid = '$TEST_ADMIN';
		EOF
	fi
}

write_secrets() {
	local db_password=$1 entry port=3306
	# The server of the systemd units reaches the database at its port on this machine, the
	# container's within the pod
	[[ -z $db_only ]] || port=$db_port
	mkdir -p "$dir/secrets/addons/sourcemod/configs"
	{
		printf '"Databases"\n{\n\t"driver_default"\t"mysql"\n'
		for entry in default sourcebans clientprefs; do
			printf '\n\t"%s"\n\t{\n\t\t"driver"\t"mysql"\n\t\t"host"\t"127.0.0.1"\n' "$entry"
			printf '\t\t"port"\t"%s"\n' "$port"
			printf '\t\t"database"\t"doi"\n\t\t"user"\t"doi"\n\t\t"pass"\t"%s"\n\t}\n' "$db_password"
		done
		printf '\n\t"storage-local"\n\t{\n\t\t"driver"\t"sqlite"\n\t\t"database"\t"sourcemod-local"\n\t}\n}\n'
	} >"$dir/secrets/addons/sourcemod/configs/databases.cfg"
}

cmd_update() {
	if ! podman image exists "$image"; then
		echo "Error: no image $image, build it first: $0 build" >&2
		exit 1
	fi
	mkdir -p "$state"
	podman run --rm --userns "$userns" --health-cmd none -v "$state:/srv/state" "$image" update "$@"
}

cmd_up() {
	if [[ ${1:-} == --db-only ]]; then
		db_only=1
		shift
	fi
	local config=${1:-coop-commando} db_password volume
	check_config "$config"
	if [[ -z $db_only ]] && ! podman image exists "$server_image"; then
		echo "Error: no image $server_image, build it first (see README.md)" >&2
		exit 1
	fi
	if [[ -z $db_only && ! -x $state/game/srcds_linux ]]; then
		echo "Error: no game in $state, download it first: $0 update" >&2
		exit 1
	fi
	if podman pod exists "$pod"; then
		echo "Error: the test instance is running, remove it first: $0 down" >&2
		exit 1
	fi
	rm -rf "$dir"
	mkdir -p "$dir"
	# The test's passwords, for the user only: the containers get the files bind-mounted
	chmod 700 "$dir"
	db_password=$(password)
	printf 'MARIADB_DATABASE=doi\nMARIADB_USER=doi\nMARIADB_PASSWORD=%s\nMARIADB_RANDOM_ROOT_PASSWORD=1\n' \
		"$db_password" >"$dir/db.env"
	{
		# A client port other than the game's 27005, which a client on this machine sends from
		printf 'SERVER_PORT=27015\nTV_PORT=27020\nCLIENT_PORT=27025\nSERVER_PASSWORD=\n'
		printf 'SOURCEBANS_SERVER_IP=127.0.0.1\nRCON_PASSWORD=%s\n' "$(password)"
	} >"$dir/server.env"
	write_database
	write_secrets "$db_password"

	# A private address of the pod's own: by default, rootless Podman's pasta gives the pod the host's
	# address, and the server ignores connections that seem to come from its own address
	local -a ports=(-p 27015:27015/udp -p 27015:27015/tcp -p 27020:27020/udp)
	[[ -z $db_only ]] || ports=(-p "127.0.0.1:$db_port:3306/tcp")
	podman pod create --name "$pod" --userns "$userns" --network pasta:-a,10.0.2.100,-n,24,-g,10.0.2.2 \
		"${ports[@]}" >/dev/null
	# The database on a tmpfs: it's the test's only, and with the pod's user namespace for the server, a
	# volume would belong to an ID that MariaDB's user isn't
	podman run -d --pod "$pod" --name "$pod-db" --env-file "$dir/db.env" --tmpfs /var/lib/mysql:rw,mode=1777 \
		-v "$dir/init:/docker-entrypoint-initdb.d:ro" docker.io/library/mariadb:lts >/dev/null
	echo "Waiting for the database"
	until podman exec "$pod-db" healthcheck.sh --connect --innodb_initialized >/dev/null 2>&1; do
		if [[ $(podman inspect -f '{{.State.Running}}' "$pod-db") != true ]]; then
			echo "Error: the database stopped, see podman logs $pod-db" >&2
			exit 1
		fi
		sleep 2
	done
	if [[ -n $db_only ]]; then
		echo "The database of the test instance of $config is up at 127.0.0.1:$db_port." \
			"For doi-server@$config.service, its settings and the server's secrets, as root:"
		printf '\n  install -D -m 640 -g doi %q /etc/doi-server/%q\n' "$dir/server.env" "$config.env"
		printf '  install -d -m 750 -g doi /etc/doi-server/secrets\n'
		printf '  cp -r %q /etc/doi-server/secrets/\n' "$dir/secrets/."
		printf '  chgrp -R doi /etc/doi-server/secrets\n  chmod -R u=rwX,g=rX,o= /etc/doi-server/secrets\n'
		return
	fi

	local -a volumes=()
	for volume in dumps:/srv/doi-data/dumps logs:/srv/doi-data/logs sm-logs:/srv/doi-data/sourcemod/logs \
		sm-data:/srv/doi-data/sourcemod/data; do
		volumes+=(-v "$pod-$volume")
	done
	local -a geoip=()
	if [[ -d /var/lib/GeoIP ]]; then
		geoip=(-v /var/lib/GeoIP:/var/lib/GeoIP:ro)
	fi
	# The state's game and workshop items with an overlay of the container's own, its mods read-only
	# Plugins prepare_server.sh disables, e.g. for tools/dump_cvars.py
	local -a extra_env=()
	if [[ -n ${DISABLE_PLUGINS:-} ]]; then
		extra_env=(-e DISABLE_PLUGINS="$DISABLE_PLUGINS")
	fi
	# The sanitisers start_server.sh preloads the runtime of
	if [[ -n ${SANITISER:-} ]]; then
		extra_env+=(-e SANITISER="$SANITISER")
	fi
	podman run -d --pod "$pod" --name "$pod-server" --env-file "$dir/server.env" -e SERVER_NAME="$config" \
		"${extra_env[@]}" \
		-v "$state/game:/srv/doi:O" -v "$state/workshop/steamapps/workshop:/srv/doi/steamapps/workshop:O" \
		-v "$state/mods:/srv/mods:ro" \
		-v "$dir/secrets:/run/secrets/doi-server:ro" "${geoip[@]}" "${volumes[@]}" \
		--health-on-failure restart "$server_image" >/dev/null
	echo "Waiting for the server"
	until podman exec "$pod-server" python3 /opt/doi-config/tools/srcds_watchdog.py --check --port 27015 \
		--timeout 2 >/dev/null 2>&1; do
		if [[ $(podman inspect -f '{{.State.Running}}' "$pod-server") != true ]]; then
			echo "Error: the server stopped, see $0 logs" >&2
			exit 1
		fi
		sleep 3
	done
	# The server drops connections from 127.0.0.1, which pasta passes on from the pod's own address
	local address
	address=$(ip -4 route get 192.0.2.1 | sed -n 's/.* src \([0-9.]*\).*/\1/p')
	echo "The test instance of $config is up: connect ${address:-<the host address>}:27015" \
		"(not 127.0.0.1), RCON with $0 rcon"
}

cmd_down() {
	local volume
	podman pod rm -f --ignore "$pod" >/dev/null
	for volume in dumps logs sm-logs sm-data; do
		podman volume rm -f "$pod-$volume" >/dev/null 2>&1 || true
	done
	rm -rf "$dir"
}

cmd_rcon() {
	RCON_PASSWORD=$(sed -n 's/^RCON_PASSWORD=//p' "$dir/server.env") "$repo/tools/rcon.py" "$@"
}

cmd_logs() {
	podman logs -f "$pod-server"
}

(($#)) || usage
command=$1
shift
case $command in
	build | update | up | down | rcon | logs) "cmd_$command" "$@" ;;
	*) usage ;;
esac
