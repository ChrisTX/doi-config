#!/bin/bash

steamcmd +force_install_dir $1 +login anonymous +app_update 462310 validate +quit

cd $1
git -C doi/cfg/doi-config pull

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
    ln -sf ../cfg/doi-config/mods/$modfolder_name doi/custom/$modfolder_name
done

# Create config symlinks
for gameconfig in doi/cfg/doi-config/configs/gamemodes/*.cfg
do
    gameconfig_file="${gameconfig##*/}"
    ln -sf doi-config/configs/gamemodes/$gameconfig doi/cfg/$gameconfig_file
done

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
tar -xf sourcemod.tgz -C doi --exclude="configs" --exclude="cfg"

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
rm -rf sourcebans-pp

# Update sm-advertisements
git clone https://github.com/ErikMinekus/sm-advertisements.git
cp -r sm-advertisements/addons/sourcemod/scripting doi/addons/sourcemod
rm -rf sm-advertisements

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
