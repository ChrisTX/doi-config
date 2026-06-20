#!/bin/bash

steamcmd +force_install_dir "$1" +login anonymous +app_update 462310 validate +quit

cd "$1" || exit
if [ -d "doi/cfg/doi-config" ]; then
    git -C doi/cfg/doi-config pull
else
    git clone https://github.com/ChrisTX/doi-config.git doi/cfg/doi-config
fi

# Apply server playlist unlock patch
cp doi/cfg/doi-config/server-patch/server_srv.so doi/bin/server_srv.so

# Remove the shipped, outdated standard libraries
rm bin/libgcc_s.so.1
rm bin/libstdc++.so.6
rm bin/libogg.so
rm bin/libvorbis.so

# Add included mods
mkdir -p doi/custom
for modfolder in doi/cfg/doi-config/mods/*/; do
    modfolder_path="${modfolder%*/}"
    modfolder_name="${modfolder_path##*/}"
    ln -sfn ../cfg/doi-config/mods/"$modfolder_name" doi/custom/"$modfolder_name"
done

# Create config symlinks
for gameconfig in doi/cfg/doi-config/configs/gamemodes/*.cfg; do
    gameconfig_file="${gameconfig##*/}"
    ln -sf doi-config/configs/gamemodes/"$gameconfig_file" doi/cfg/"$gameconfig_file"
done

# Remove all theater VPKs to ensure they update
./doi/cfg/doi-config/scripts/wscache_deleter.py -p "$PWD" -i 3627608872 3591171916 3545048108 3431251359 3431242570 3431236539

# Update metamod source and sourcemod
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
# This isn't supported yet via HTTPS either, according to the core.cfg comment.
sed -i -E "s/(\"DisableAutoUpdate\"\s+)\"no\"/\1\"yes\"/" doi/addons/sourcemod/configs/core.cfg

# Link included sourcemod scripts
for smscript in doi/cfg/doi-config/sourcemod/*.sp; do
    smscript_file="${smscript##*/}"
    ln -sf ../../../cfg/doi-config/sourcemod/"$smscript_file" doi/addons/sourcemod/scripting/"$smscript_file"
done

# Update sourcebans-pp
git clone https://github.com/sbpp/sourcebans-pp.git
cp -r sourcebans-pp/game/addons/sourcemod/scripting doi/addons/sourcemod
cp -r sourcebans-pp/game/addons/sourcemod/translations doi/addons/sourcemod
cp -r sourcebans-pp/game/addons/sourcemod/configs doi/addons/sourcemod
rm -rf sourcebans-pp

sourcebans_replacer () {
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

# Add our advertisements
ln -sf ../../../cfg/doi-config/texts/advertisements.txt doi/addons/sourcemod/configs/advertisements.txt

# Update AFK Manager
ln -sf ../doi-config/configs/afk_manager.cfg doi/cfg/sourcemod/afk_manager.cfg
curl -o doi/addons/sourcemod/scripting/afk_manager4.sp http://afkmanager.dawgclan.net/scripting/afk_manager4.sp
curl -o doi/addons/sourcemod/translations/afk_manager.phrases.txt http://afkmanager.dawgclan.net/translations/afk_manager.phrases.txt
git clone https://github.com/Bara/Multi-Colors.git
cp -r Multi-Colors/addons/sourcemod/scripting/include doi/addons/sourcemod/scripting/include
rm -rf Multi-Colors
patch -N doi/addons/sourcemod/scripting/afk_manager4.sp doi/cfg/doi-config/scripts/afkmanager.patch

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

pushd doi/cfg || exit

# Install MOTDs if known to our config system
# Otherwise users need to make their own server.cfg loading init-...
if [[ ! -n $SERVER_CONFIG_NAME && -f doi-config/texts/server_"$2".cfg ]]; then
    SERVER_CONFIG_NAME=$2
fi
if [[ -n $SERVER_CONFIG_NAME ]]; then
    if [[ ! -f doi-config/texts/server_"$SERVER_CONFIG_NAME".cfg ]]; then
        echo "Error: Config ""$SERVER_CONFIG_NAME requested but unknown!" >&2
        exit 1
    fi
    cp doi-config/texts/server_"$SERVER_CONFIG_NAME".cfg server.cfg
    cp doi-config/texts/motd_"$SERVER_CONFIG_NAME".txt ../motd.txt
fi

if [[ -n $RCON_PASSWORD ]]; then
    echo "rcon_password \"$RCON_PASSWORD\"" > rcon.cfg
    if ! grep -q "exec rcon.cfg" server.cfg; then
        echo "exec rcon.cfg" >> server.cfg
    fi
fi

popd || exit
