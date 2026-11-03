#!/bin/bash

steamcmd +force_install_dir "$1" +login anonymous +app_update 462310 validate +quit

cd "$1" || exit

# Remove the clone inside doi/cfg and the links into it, which the old layout of the repository used
if [[ -d doi/cfg/doi-config/.git ]]; then
	find doi -lname '*doi-config/*' -delete
	rm -rf doi/cfg/doi-config
fi

if [[ -d doi-config ]]; then
	git -C doi-config pull
else
	git clone https://github.com/ChrisTX/doi-config.git doi-config
fi

# Apply server playlist unlock patch
cp doi-config/server-patch/server_srv.so doi/bin/server_srv.so

# Remove the shipped, outdated standard libraries
rm bin/libgcc_s.so.1
rm bin/libstdc++.so.6
rm bin/libogg.so
rm bin/libvorbis.so

# Remove all theater VPKs to ensure they update
./doi-config/tools/wscache_deleter.py -p "$PWD" -i 3627608872 3591171916 3545048108 3431251359 3431242570 3431236539

# Update metamod source and sourcemod
# The secrets are provided in addons/sourcemod/configs/databases.cfg
# They are deployed via the generic secrets deployment at the end of the systemd startup preparations
# Included are database credentials for sourcemod, sourcebans and userprefs
METAMOD_BRANCH="1.12"
SOURCEMOD_BRANCH="1.12"

METAMOD_BASE_URL="https://mms.alliedmods.net/mmsdrop/${METAMOD_BRANCH}"
SOURCEMOD_BASE_URL="https://sm.alliedmods.net/smdrop/${SOURCEMOD_BRANCH}"

LATEST_METAMOD_FILE=$(curl "${METAMOD_BASE_URL}/mmsource-latest-linux" | xargs)
LATEST_SOURCEMOD_FILE=$(curl "${SOURCEMOD_BASE_URL}/sourcemod-latest-linux" | xargs)

METAMOD_URL="${METAMOD_BASE_URL}/${LATEST_METAMOD_FILE}"
SOURCEMOD_URL="${SOURCEMOD_BASE_URL}/${LATEST_SOURCEMOD_FILE}"

curl -o metamod.tgz "$METAMOD_URL"
curl -o sourcemod.tgz "$SOURCEMOD_URL"

tar -xf metamod.tgz -C doi
tar -xf sourcemod.tgz -C doi

rm metamod.tgz
rm sourcemod.tgz

# Disable SourceMod gamedata update. We update all of SourceMod with this script every time.
# This isn't supported yet via HTTPS either according to the core.cfg comment.
sed -i -E "s/(\"DisableAutoUpdate\"\s+)\"no\"/\1\"yes\"/" doi/addons/sourcemod/configs/core.cfg

# Link the files of this repository's game folder into the server, which is laid out like it: the configs, mods,
# SourceMod plugins, their translations and configs. Links to files that have since been removed go first.
find doi -xtype l -lname "$PWD/doi-config/game/*" -delete
cp -rs --remove-destination "$PWD"/doi-config/game/. doi/

# Update GeoIP databases
if [[ -f "/var/lib/GeoIP/GeoLite2-City.mmdb" ]]; then
	rm doi/addons/sourcemod/configs/geoip/GeoLite2-*.mmdb
	ln -sf /var/lib/GeoIP/GeoLite2-City.mmdb doi/addons/sourcemod/configs/geoip
fi

# Update sourcebans-pp
git clone https://github.com/sbpp/sourcebans-pp.git
./sourcebans-pp/game/addons/sourcemod/scripting/scripts/resolve-plugin-version.sh
cp -r sourcebans-pp/game/addons/sourcemod/scripting doi/addons/sourcemod
cp -r sourcebans-pp/game/addons/sourcemod/translations doi/addons/sourcemod
cp -r sourcebans-pp/game/addons/sourcemod/configs doi/addons/sourcemod
rm -rf sourcebans-pp

sourcebans_replacer() {
	sed -i -E "s/(\"$1\"\s+)\"[^\"]*\"/\1\"$2\"/" doi/addons/sourcemod/configs/sourcebans/sourcebans.cfg
}

sourcebans_replacer "BackupConfigs" "0"
if [[ -n $SOURCEBANS_WEBSITE ]]; then
	sourcebans_replacer "Website" "https:\/\/$SOURCEBANS_WEBSITE"
fi
if [[ -n $SOURCEBANS_SERVER_ID ]]; then
	sourcebans_replacer "ServerID" "$SOURCEBANS_SERVER_ID"
fi

# Update sm-advertisements
git clone https://github.com/ErikMinekus/sm-advertisements.git
cp -r sm-advertisements/addons/sourcemod/scripting doi/addons/sourcemod
rm -rf sm-advertisements

# AFK Manager itself is part of this repository's game folder, it needs Multi-Colors
git clone https://github.com/Bara/Multi-Colors.git
cp -r Multi-Colors/addons/sourcemod/scripting/include doi/addons/sourcemod/scripting/include
rm -rf Multi-Colors

# Add SMJansson, SteamWorks for SourceBans++ Discord integration
# See https://sbpp.github.io/integrations/discord-forward-setup/
git clone https://github.com/davenonymous/SMJansson.git
cp SMJansson/bin/* doi/addons/sourcemod/extensions
cp -r SMJansson/pawn/scripting/. doi/addons/sourcemod/scripting

curl -L -o package-lin.tgz https://github.com/KyleSanderson/SteamWorks/releases/download/1.2.3c/package-lin.tgz

tar -xf package-lin.tgz --strip-components=1 -C doi
rm package-lin.tgz

# Git fixes are needed for compatibility with current SourceMod
curl -L -o doi/addons/sourcemod/scripting/include/SteamWorks.inc https://github.com/KyleSanderson/SteamWorks/raw/refs/heads/master/Pawn/includes/SteamWorks.inc

# Install the actual SourceBans++ discord-forward
# The secrets are provided in cfg/sourcemod/sbpp_discord.cfg
# They are deployed via the generic secrets deployment at the end of the systemd startup preparations
curl -o doi/addons/sourcemod/scripting/sbpp_discord.sp https://raw.githubusercontent.com/sbpp/discord-forward/refs/heads/master/sbpp_discord.sp

# Enable SQL admin plugins
pushd doi/addons/sourcemod/plugins || exit
mv disabled/admin-sql-threaded.smx .
mv disabled/sql-admin-manager.smx .

# Nextmap is incompatible with DOI
mv nextmap.smx disabled

# SourceBans requires basebans to be off
mv basebans.smx disabled

# Recompile scripts
for plugin in *.smx; do
	scriptfile="${plugin%.*}"
	if [[ -f ../scripting/"$scriptfile".sp ]]; then
		../scripting/spcomp64 ../scripting/"$scriptfile".sp
	fi
done
for plugin in ../scripting/sbpp*.sp; do
	../scripting/spcomp64 "$plugin"
done
../scripting/spcomp64 ../scripting/advertisements.sp
../scripting/spcomp64 ../scripting/afk_manager4.sp
../scripting/spcomp64 ../scripting/doi_cvar_unlocker.sp
../scripting/spcomp64 ../scripting/doi_difficulty_scaler.sp
popd || exit

# Install the server.cfg and MOTD of the server, if this repository has the server
# Otherwise users need to make their own server.cfg loading init-...
if [[ ! -n $SERVER_CONFIG_NAME && -d doi-config/servers/"$2" ]]; then
	SERVER_CONFIG_NAME=$2
fi
if [[ -n $SERVER_CONFIG_NAME ]]; then
	if [[ ! -d doi-config/servers/"$SERVER_CONFIG_NAME" ]]; then
		echo "Error: Config ""$SERVER_CONFIG_NAME requested but unknown!" >&2
		exit 1
	fi
	# Copies rather than links, as the RCON password is added to server.cfg
	cp -r doi-config/servers/"$SERVER_CONFIG_NAME"/. doi/
fi

pushd doi/cfg || exit

if [[ -n $RCON_PASSWORD ]]; then
	echo "rcon_password \"$RCON_PASSWORD\"" >rcon.cfg
	if ! grep -q "exec rcon.cfg" server.cfg; then
		echo "exec rcon.cfg" >>server.cfg
	fi
fi

popd || exit
