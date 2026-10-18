#!/bin/zsh
set -euo pipefail

bb_root="${0:A:h}"
bb_dist="${BB_DIST_PATH:-$bb_root/dist}"
bb_app_name='Bloodborne MacOS'
bb_version="${BB_APP_VERSION:-1.0}"
bb_app="$bb_dist/$bb_app_name.app"
bb_stage="$bb_root/.build/dmg-root"
bb_dmg="$bb_dist/Bloodborne-MacOS-$bb_version.dmg"

if [[ ! -d "$bb_app" ]]; then
    print -u2 "Build the app first; not found: $bb_app"
    exit 1
fi
if ! command -v hdiutil >/dev/null 2>&1; then
    print -u2 'hdiutil is required to package the macOS disk image.'
    exit 1
fi

mkdir -p "$bb_dist"
rm -rf "$bb_stage"
mkdir -p "$bb_stage"
ditto "$bb_app" "$bb_stage/$bb_app_name.app"
ln -s /Applications "$bb_stage/Applications"
hdiutil create -volname "$bb_app_name $bb_version" \
    -srcfolder "$bb_stage" -ov -format UDZO "$bb_dmg"
print "Packaged: $bb_dmg"
