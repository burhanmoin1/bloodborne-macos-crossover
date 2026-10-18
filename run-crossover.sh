#!/bin/bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
APP_DATA=${BB_DATA_DIR:-${BB_APP_DATA_DIR:-"$HOME/Library/Application Support/Bloodborne macOS"}}
CONFIG_DIR=${BB_LAUNCHER_CONFIG_DIR:-"$APP_DATA/Launcher"}
SETTINGS_FILE="$CONFIG_DIR/settings.json"
LOGS_DIR=${BB_RUN_LOGS_DIR:-"$PWD/logs"}
DEFAULT_GAME="$HOME/Downloads/Bloodborne.Game.of.the.Year.Edition.PS4-PRELUDE/Bloodborne.v1.09/EP9000-CUSA03173_00-BLOODBORNE0000EU"
PYTHON=${BB_PYTHON:-$(command -v python3 || true)}

usage() {
    printf 'Usage: %s [--check] [CrossOver bridge options]\n' "${0##*/}"
    printf 'Uses the launcher settings and existing saves in %s/user.\n' "$APP_DATA"
    printf 'Logs are written to %s/<timestamp>/run.log.\n' "$LOGS_DIR"
    printf 'Override paths with BB_GAME_DIR, BB_USER_DIR, BB_PORT_DIR, BB_KOSMICKRISP_DIR, or BB_CROSSOVER_ROOT.\n'
}

if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    usage
    exit 0
fi

if [[ -z $PYTHON ]]; then
    printf 'Python 3 is required to read the launcher settings and start CrossOver.\n' >&2
    exit 1
fi

setting() {
    "$PYTHON" - "$SETTINGS_FILE" "$1" "$2" <<'PY'
import json
import os
import sys

path, key, fallback = sys.argv[1:]
try:
    with open(path, encoding='utf-8') as settings_file:
        value = json.load(settings_file).get(key)
except (OSError, ValueError, AttributeError):
    value = None
if value is None or value == '':
    value = fallback
if isinstance(value, bool):
    value = '1' if value else '0'
print(os.path.expanduser(str(value)))
PY
}

GAME=${BB_GAME_DIR:-$(setting game_dir "$DEFAULT_GAME")}
if [[ -z ${BB_GAME_DIR:-} && ! -f $GAME/eboot.bin && -f $DEFAULT_GAME/eboot.bin ]]; then
    printf 'Saved game path is unavailable; using the Downloads copy: %s\n' "$DEFAULT_GAME" >&2
    GAME=$DEFAULT_GAME
fi
USER_DIR=${BB_USER_DIR:-$(setting user_dir "$APP_DATA/user")}
CONFIG=${BB_CONFIG:-"$APP_DATA/bbport-macos.ini"}
PORT_DIR=${BB_PORT_DIR:-"$APP_DATA/port-v1.9"}
if [[ ! -f $PORT_DIR/Bloodborne.exe && -f $ROOT/bbport-windows/Bloodborne.exe ]]; then
    PORT_DIR="$ROOT/bbport-windows"
fi
GRAPHICS_DIR=${BB_KOSMICKRISP_DIR:-"$APP_DATA/kosmickrisp"}
if [[ -d $ROOT/app/resources/kosmickrisp ]]; then
    GRAPHICS_DIR=${BB_KOSMICKRISP_DIR:-"$ROOT/app/resources/kosmickrisp"}
fi
CROSSOVER_ROOT=${BB_CROSSOVER_ROOT:-$(setting crossover_root '')}
if [[ -z $CROSSOVER_ROOT ]]; then
    for candidate in \
        "/Applications/CrossOver.app/Contents/SharedSupport/CrossOver" \
        "$HOME/Applications/CrossOver.app/Contents/SharedSupport/CrossOver"; do
        if [[ -f $candidate/lib/wine/x86_64-unix/wine ]]; then
            CROSSOVER_ROOT=$candidate
            break
        fi
    done
fi

if [[ ! -f $GAME/eboot.bin ]]; then
    printf 'Game eboot.bin not found in: %s\nSet BB_GAME_DIR to the game directory.\n' "$GAME" >&2
    exit 1
fi
if [[ ! -f $PORT_DIR/Bloodborne.exe || ! -f $PORT_DIR/bin/bb-probe.exe ]]; then
    printf 'Bloodborne PC v1.9 runtime not found: %s\nLaunch the app once to install it or set BB_PORT_DIR.\n' "$PORT_DIR" >&2
    exit 1
fi
if [[ ! -f $GRAPHICS_DIR/libMoltenVK.dylib || ! -f $GRAPHICS_DIR/kosmickrisp_mesa_icd.json ]]; then
    printf 'KosmicKrisp runtime not found: %s\nLaunch the app once to install it or set BB_KOSMICKRISP_DIR.\n' "$GRAPHICS_DIR" >&2
    exit 1
fi
if [[ ! -f $CROSSOVER_ROOT/lib/wine/x86_64-unix/wine ]]; then
    printf 'CrossOver Wine runner not found: %s\nSet BB_CROSSOVER_ROOT to its CrossOver support directory.\n' "$CROSSOVER_ROOT" >&2
    exit 1
fi
if [[ ${1:-} == --check ]]; then
    printf 'Game: %s\nSave data: %s\nConfig: %s\nCrossOver: %s\nRuntime: %s\nGraphics: %s\nLogs: %s\n' \
        "$GAME" "$USER_DIR" "$CONFIG" "$CROSSOVER_ROOT" "$PORT_DIR" "$GRAPHICS_DIR" "$LOGS_DIR"
    exit 0
fi

mkdir -p "$USER_DIR" "$LOGS_DIR"
RUN_ID=$(date '+%Y%m%d_%H%M%S')
RUN_DIR="$LOGS_DIR/$RUN_ID"
if [[ -e $RUN_DIR ]]; then RUN_DIR="${RUN_DIR}_$$"; fi
mkdir -p "$RUN_DIR"
ln -sfn "${RUN_DIR##*/}" "$APP_DATA/logs/latest"
LOG_FILE="$RUN_DIR/run.log"

export BB_DATA_DIR="$APP_DATA"
export BB_CONFIG="$CONFIG"
export BB_USER_DIR="$USER_DIR"
export BB_GPU_USER_DIR=${BB_GPU_USER_DIR:-"$USER_DIR"}
export BB_GAME_DIR="$GAME"
export BB_KOSMICKRISP_DIR="$GRAPHICS_DIR"
export BB_MODS_DIR=${BB_MODS_DIR:-$(setting mods_dir "$APP_DATA/mods")}
export BB_MODS_CONFIG=${BB_MODS_CONFIG:-"$APP_DATA/mods.json"}
export BB_MODS_ENABLED=${BB_MODS_ENABLED:-$(setting mods_enabled 1)}
export BB_PATCHES_DIR=${BB_PATCHES_DIR:-$(setting patches_dir "$APP_DATA/patches")}
export BB_PATCHES_CONFIG=${BB_PATCHES_CONFIG:-"$APP_DATA/patches.json"}
export BB_FPS=uncap
export BB_UPSCALER=off
export BB_RENDER_RES=1280x720
export BB_OBJECT_MOTION=0
export BB_PRESENT_MODE=${BB_PRESENT_MODE:-$(setting present_mode Mailbox)}
export BB_FULLSCREEN=${BB_FULLSCREEN:-$(setting fullscreen 0)}
export BB_LANGUAGE=${BB_LANGUAGE:-$(setting language 1)}
export BB_FRAME_STATS=${BB_FRAME_STATS:-1}
if [[ ${BB_GPU_PROFILE:-0} == 1 ]]; then
    export BB_GPU_PROFILE=1
else
    unset BB_GPU_PROFILE
fi

printf 'Game: %s\nSave data: %s\nConfig: %s\nCrossOver: %s\nRuntime: %s\nRun log: %s\n' \
    "$GAME" "$USER_DIR" "$CONFIG" "$CROSSOVER_ROOT" "$PORT_DIR" "$LOG_FILE"

BRIDGE_ARGS=(--port-dir "$PORT_DIR" --data-dir "$APP_DATA" --graphics-dir "$GRAPHICS_DIR" \
    --runner "$CROSSOVER_ROOT" --game-dir "$GAME")
if [[ -n ${BB_LIMIT_SECONDS:-} ]]; then
    BRIDGE_ARGS+=(--limit-seconds "$BB_LIMIT_SECONDS")
fi

if "$PYTHON" "$ROOT/app/crossover_bridge.py" "${BRIDGE_ARGS[@]}" "$@" 2>&1 | tee "$LOG_FILE"; then
    exit_code=0
else
    exit_code=$?
fi
printf 'CrossOver exited with code %s. Full log: %s\n' "$exit_code" "$LOG_FILE"
exit "$exit_code"
