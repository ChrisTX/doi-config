#!/bin/bash

steamcmd +force_install_dir $1 +login anonymous +app_update 462310 validate +quit

cd $1
if [ -d "doi/cfg/doi-config" ]
then
    FRESH_INSTALLATION=false
    git -C doi/cfg/doi-config pull
else
    FRESH_INSTALLATION=true
    git -C doi/cfg/doi-config clone https://github.com/ChrisTX/doi-config.git
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
for modfolder in doi/cfg/doi-config/mods/*/
do
    modfolder_path="${modfolder%*/}"
    modfolder_name="${modfolder_path##*/}"
    ln -sfn ../cfg/doi-config/mods/$modfolder_name doi/custom/$modfolder_name
done

# Create config symlinks
for gameconfig in doi/cfg/doi-config/configs/gamemodes/*.cfg
do
    gameconfig_file="${gameconfig##*/}"
    ln -sf doi-config/configs/gamemodes/$gameconfig_file doi/cfg/$gameconfig_file
done

# Remove all theater VPKs to ensure they update
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
$SCRIPT_DIR/wscache_deleter.py -p $(pwd) -i 3627608872 3591171916 3545048108 3431251359 3431242570 3431236539

# Update metamod source and sourcemod
METAMOD_BRANCH="1.12"
SOURCEMOD_BRANCH="1.12"

METAMOD_BASE_URL="https://mms.alliedmods.net/mmsdrop/${METAMOD_BRANCH}"
SOURCEMOD_BASE_URL="https://sm.alliedmods.net/smdrop/${SOURCEMOD_BRANCH}"

LATEST_METAMOD_FILE=$(curl "${METAMOD_BASE_URL}/mmsource-latest-linux" | xargs)
LATEST_SOURCEMOD_FILE=$(curl "${SOURCEMOD_BASE_URL}/sourcemod-latest-linux" | xargs)

METAMOD_URL="${METAMOD_BASE_URL}/${LATEST_METAMOD_FILE}"
SOURCEMOD_URL="${SOURCEMOD_BASE_URL}/${LATEST_SOURCEMOD_FILE}"

curl -o metamod.tgz $METAMOD_URL
curl -o sourcemod.tgz $SOURCEMOD_URL

tar -xf metamod.tgz -C doi
if [ "$FRESH_INSTALLATION" = true ] ; then
    tar -xf sourcemod.tgz -C doi
else
    tar -xf sourcemod.tgz -C doi --exclude="configs" --exclude="cfg"
fi

rm metamod.tgz
rm sourcemod.tgz

# Link included sourcemod scripts
for smscript in doi/cfg/doi-config/sourcemod/*.sp
do
    smscript_file="${smscript##*/}"
    ln -sf ../../../cfg/doi-config/sourcemod/$smscript_file doi/addons/sourcemod/scripting/$smscript_file
done

# Update sourcebans-pp
git clone https://github.com/sbpp/sourcebans-pp.git
cp -r sourcebans-pp/game/addons/sourcemod/scripting doi/addons/sourcemod
cp -r sourcebans-pp/game/addons/sourcemod/translations doi/addons/sourcemod
if [ "$FRESH_INSTALLATION" = true ]; then
    cp -r sourcebans-pp/game/addons/sourcemod/configs doi/addons/sourcemod
fi
rm -rf sourcebans-pp

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

# Enable SQL admin plugins
pushd doi/addons/sourcemod/plugins
mv disabled/admin-sql-threaded.smx .
mv disabled/sql-admin-manager.smx .

# Nextmap is incompatible with DOI
mv nextmap.smx disabled

# SourceBans requires basebans to be off
mv basebans.smx disabled

# Recompile scripts
for plugin in *.smx
do
    scriptfile="${plugin%.*}"
    if [ -f ../scripting/$scriptfile.sp ]; then
        ../scripting/spcomp64 ../scripting/$scriptfile.sp
    fi
done
popd

# Install MOTDs
if [ -n "$2" ]; then
    ln -sf doi-config/texts/server_$2.cfg doi/cfg/server.cfg
    ln -sf cfg/doi-config/texts/motd_$2.txt doi/motd.txt
fi
