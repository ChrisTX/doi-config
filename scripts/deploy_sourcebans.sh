#!/bin/bash -x

sudo -u sb-builder /opt/prepare_sourcebans.sh

cd /var/lib/sb-builder || exit

rm -rf staging/install
rm -rf staging/updater
rm -f staging/{bin,.gitignore,composer.json,composer.lock,config.php.template,sb_debug_connection.php,version.txt}
rm -rf staging/{phpstan*,phpunit.xml,tests,package-lock.json,package.json}
cp /var/lib/sb-builder/config.php staging

chown -R root:http staging
mkdir staging/{cache,templates_c}
chown http:http staging/{cache,demos,templates_c,images/games,images/maps}
find staging -type f -exec chmod 0640 {} \;
find staging -type d -exec chmod 0750 {} \;

rm -rf /srv/http/sourcebans.rev-crew.info/{templates_c,includes,pages,scripts}
ln -sf /var/lib/GeoIP/GeoLite2-Country.mmdb staging/data/GeoLite2-Country.mmdb

cp -a staging/. /srv/http/sourcebans.rev-crew.info/
rm -rf staging
