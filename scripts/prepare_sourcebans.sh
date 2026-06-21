#!/bin/bash -x

cd ~
if [ -d "repo" ]; then
    rm -rf repo
fi
git clone https://github.com/sbpp/sourcebans-pp.git repo

cp -r repo/web staging
pushd staging || exit
composer install --no-dev --apcu-autoloader --optimize-autoloader
popd || exit
rm -rf repo
