#!/bin/zsh
set -euo pipefail

bb_root="${0:A:h}"
bb_build="$bb_root/.build"
bb_dist="${BB_DIST_PATH:-$bb_root/dist}"
bb_venv="$bb_build/venv"
bb_python="${BB_PYTHON:-/Library/Frameworks/Python.framework/Versions/3.13/bin/python3}"
bb_app_name='Bloodborne MacOS'
bb_app_version="${BB_APP_VERSION:-1.0}"
bb_mingw="$(command -v x86_64-w64-mingw32-gcc || true)"
bb_iconset="$bb_build/Bloodborne.iconset"
bb_icon_source="$bb_build/Bloodborne.png"
bb_icon="$bb_build/Bloodborne.icns"

if [[ ! -x "$bb_python" ]]; then
    print -u2 'Set BB_PYTHON to an Apple Silicon Python 3.13 installation with Tk support.'
    exit 1
fi
if ! "$bb_python" -c 'import _tkinter, tkinter; tkinter.Tcl().eval("info patchlevel")' >/dev/null 2>&1; then
    print -u2 'The selected Python does not have working Tcl/Tk support; choose a Tk-enabled Python 3.13 interpreter.'
    exit 1
fi
if [[ -z "$bb_mingw" ]]; then
    print -u2 'Install the MinGW-w64 cross compiler before building: brew install mingw-w64.'
    exit 1
fi

mkdir -p "$bb_build"
if [[ ! -x "$bb_venv/bin/python" ]]; then
    "$bb_python" -m venv "$bb_venv"
fi
"$bb_venv/bin/python" -m pip install -r "$bb_root/requirements-build.txt"

bb_adapter="$bb_build/bb-crossover-bootstrap.dll"
"$bb_mingw" -shared -nostdlib -O2 "$bb_root/app/crossover_bootstrap.c" \
    -lkernel32 -luser32 -Wl,--entry,DllMain -o "$bb_adapter"

rm -rf "$bb_iconset"
mkdir -p "$bb_iconset"
sips -s format png "$bb_root/app/resources/bloodborne.ico" --out "$bb_icon_source" >/dev/null
bb_make_icon() {
    sips -z "$2" "$2" "$bb_icon_source" --out "$bb_iconset/$1" >/dev/null
}
bb_make_icon icon_16x16.png 16
bb_make_icon icon_16x16@2x.png 32
bb_make_icon icon_32x32.png 32
bb_make_icon icon_32x32@2x.png 64
bb_make_icon icon_128x128.png 128
bb_make_icon icon_128x128@2x.png 256
bb_make_icon icon_256x256.png 256
bb_make_icon icon_256x256@2x.png 512
bb_make_icon icon_512x512.png 512
bb_make_icon icon_512x512@2x.png 1024
iconutil --convert icns "$bb_iconset" --output "$bb_icon"

"$bb_venv/bin/pyinstaller" \
    --noconfirm --clean --windowed --onedir \
    --name "$bb_app_name" \
    --osx-bundle-identifier 'com.burhanmoin1.bloodborne-macos' \
    --icon "$bb_icon" \
    --target-architecture arm64 \
    --add-data="${bb_root}/app:app" \
    --add-binary="${bb_adapter}:app/resources" \
    --workpath "$bb_build/pyinstaller" \
    --distpath "$bb_dist" \
    --specpath "$bb_build" \
    "$bb_root/app/launcher.py"

bb_app="$bb_dist/$bb_app_name.app"
bb_info="$bb_app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $bb_app_version" "$bb_info"
/usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $bb_app_version" "$bb_info"
/usr/bin/codesign --force --deep --sign - "$bb_app"

print "Built: $bb_app"
