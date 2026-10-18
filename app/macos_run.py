#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""CrossOver launch script: prepares the game image and starts bb-probe.exe.

Same environment variables as run.sh (BB_GAME_DIR, BB_DATA_DIR, BB_FPS, BB_RENDER_RES,
BB_LIVE_RES, BB_PATCHES, BB_MODS_*, BB_USER_DIR, ...). Extra arguments go to bb-probe.
The in-game "Apply and restart" runs this script again through BB_RESTART_COMMAND;
`--after PID` waits for the previous game process to end first (its GPU device and memory).
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

PORT = Path(__file__).resolve().parent


# Co-op: the community service that answers Bloodborne's own game-server requests
# (messages, bloodstains, sign-in); summon requests go to the shadNet server instead.
COMMUNITY_SERVER = 'https://thehuntersdream.com'
GAME_SERVER = 'https://ss4.scej-network.jp:20443'
# The server's ss.info sends the game to this port for its API (summons among them).
COMMUNITY_API_PORT = 18671
LANCE_60FPS_IMAGE = 'bbc91f4dff6bc3118b039464289e39878a8fdfc802a07fab9d5fe84d935a676f'


def image_sha256(game):
    """Hash the loaded eboot image, independent of its SELF container."""
    sys.path.insert(0, str(PORT / 'scripts'))
    from prepare import parse_self, span
    elf, _header, program_headers, _segments, _missing = parse_self((Path(game) / 'eboot.bin').read_bytes())
    loads = [header for header in program_headers if header['type'] in (1, 0x61000010)]
    image = bytearray(max(header['vaddr'] + header['memsz'] for header in loads))
    for header in loads:
        image[header['vaddr']:header['vaddr'] + header['filesz']] = span(elf, header['offset'], header['filesz'])
    return hashlib.sha256(image).hexdigest()


def summon_service(webapi):
    """True when a shadNet WebAPI answers Bloodborne's summon calls: the route exists there
    (an empty request is refused with 400), where other servers answer 404."""
    import urllib.error
    import urllib.request
    request = urllib.request.Request(webapi.rstrip('/') + '/summon_messenger/create', data=b'',
                                     method='POST')
    try:
        urllib.request.urlopen(request, timeout=4).close()
        return True
    except urllib.error.HTTPError as error:
        return error.code != 404
    except (OSError, ValueError):
        return False


def online_overrides(env, user_dir):
    """Writes user/host_overrides.json for this launch. A player who needs other addresses
    puts them in user/host_overrides.custom.json, which is then used as it is."""
    custom = user_dir / 'host_overrides.custom.json'
    path = custom if custom.exists() else user_dir / 'host_overrides.json'
    if path != custom:
        community = (env.get('BB_COMMUNITY_SERVER') or COMMUNITY_SERVER).rstrip('/')
        if '://' not in community:
            community = 'https://' + community
        host = community.split('://', 1)[1]
        webapi = env.get('BB_SHADNET_WEBAPI') or 'http://127.0.0.1:31315'
        # Game server -> community server (same port, 20443). Summon signs -> the shadNet
        # WebAPI when that server has the Bloodborne summon service (the shadp2p server),
        # otherwise they stay with the community server.
        overrides = {GAME_SERVER: community}
        if summon_service(webapi):
            overrides.update({f'{scheme}://{host}:{COMMUNITY_API_PORT}/summon_messenger': webapi
                              for scheme in ('https', 'http')})
            print(f'Co-op: summon signs through {webapi}')
        else:
            print(f'Co-op: {webapi} has no summon service; summon signs through {community}')
        path.write_text(json.dumps(overrides, indent=2) + '\n', encoding='utf-8')
    env['SHADPS4_HTTP_HOST_OVERRIDES_JSON'] = str(path)


def fail(message):
    print(message, file=sys.stderr)
    sys.exit(1)


def wait_for(pid):
    kernel32 = ctypes.windll.kernel32
    SYNCHRONIZE = 0x00100000
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if handle:
        kernel32.WaitForSingleObject(handle, 30000)
        kernel32.CloseHandle(handle)


def no_console():
    """Started without a console (the launcher): console programs must not open their own."""
    return 0 if ctypes.windll.kernel32.GetConsoleWindow() else subprocess.CREATE_NO_WINDOW


def run_script(name, *args, capture=False):
    # Inside the packaged Bloodborne.exe (PyInstaller) the executable runs scripts itself.
    script = ['--script'] if getattr(sys, 'frozen', False) else []
    command = [sys.executable, *script, str(PORT / 'scripts' / name), *map(str, args)]
    if capture:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True,
                                creationflags=no_console())
        if result.returncode:
            sys.exit(result.returncode)
        return result.stdout
    # stdin given: the output handles are passed explicitly (a windowed Bloodborne.exe child would
    # get none otherwise).
    result = subprocess.run(command, stdin=subprocess.DEVNULL, creationflags=no_console())
    if result.returncode:
        sys.exit(result.returncode)
    return None


def ini_value(path, key):
    try:
        for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
            match = re.fullmatch(rf'{re.escape(key)}=(.*)', line.strip())
            if match:
                return match.group(1)
    except OSError:
        pass
    return None


def find_executable(name):
    """bin/ (packaged), else out/ (built with build.sh)."""
    for candidate in (PORT / 'bin' / name, PORT / 'out' / name):
        if candidate.is_file():
            return candidate
    return None


PREPARATION_CACHE_VERSION = 1
PREPARATION_OUTPUTS = ('boot.bin', 'eboot.elf', 'entry.bin', 'analysis.json',
                       'boot-linked.bin', 'link.json', 'content.bin', 'content-profile.json')


def preparation_key(game, sku):
    """Cheaply identify files that affect the prepared executable image."""
    game = Path(game).resolve()
    inputs = (game / 'eboot.bin', game / 'sce_module/libc.prx',
              game / 'sce_module/libSceFios2.prx', game / 'sce_sys/param.sfo')
    signature = []
    for path in inputs:
        stat = path.stat()
        signature.append((path.relative_to(game).as_posix(), stat.st_size, stat.st_mtime_ns))
    script_dir = PORT / 'scripts'
    scripts = (Path(__file__).resolve(), script_dir / 'prepare.py',
               script_dir / 'link_modules.py', script_dir / 'link_libc.py',
               script_dir / 'content_profile.py')
    script_hashes = [(path.name, hashlib.sha256(path.read_bytes()).hexdigest()) for path in scripts]
    payload = json.dumps({'version': PREPARATION_CACHE_VERSION, 'game': str(game), 'sku': sku,
                          'inputs': signature, 'scripts': script_hashes}, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def prepared_image_is_current(game, out, sku):
    cache = out / '.macos-preparation.json'
    try:
        stored = json.loads(cache.read_text(encoding='utf-8'))
        return (stored.get('key') == preparation_key(game, sku) and
                all((out / name).is_file() and (out / name).stat().st_size > 0
                    for name in PREPARATION_OUTPUTS))
    except (OSError, ValueError, TypeError):
        return False


def save_preparation_cache(game, out, sku):
    cache = out / '.macos-preparation.json'
    temporary = out / '.macos-preparation.json.tmp'
    temporary.write_text(json.dumps({'key': preparation_key(game, sku)}, indent=2) + '\n',
                         encoding='utf-8')
    temporary.replace(cache)


def configure_cpu_compatibility(environment, link_file):
    try:
        compatibility = json.loads(Path(link_file).read_text(encoding='utf-8')).get('cpu_compat', {})
    except (OSError, ValueError):
        compatibility = {}
    if compatibility.get('enabled'):
        environment['BB_CPU_COMPAT'] = '1'
    else:
        environment.pop('BB_CPU_COMPAT', None)


def main():
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == '--after':
        wait_for(int(args[1]))
        args = args[2:]
    # As run.sh: relative paths (BB_GAME_DIR, BB_DATA_DIR, fsr4_shaders/) are from the port.
    os.chdir(PORT)
    env = os.environ
    data = Path(env.get('BB_DATA_DIR', PORT))
    out = data / 'out'
    out.mkdir(parents=True, exist_ok=True)
    env.setdefault('BB_CONFIG', str(data / 'bbport.ini'))
    config = env['BB_CONFIG']
    print('Graphics settings: upscaler {}, preset {}, output {}, live resolution {}'.format(
        ini_value(config, 'upscaler') or 'fsr3', ini_value(config, 'preset') or '0',
        ini_value(config, 'output_res') or '1920x1080',
        ini_value(config, 'live_resolution') or '0'))
    if not env.get('BB_FSR411_DIR') and not (PORT / 'fsr4_411').is_dir() and (data / 'fsr4_411').is_dir():
        env['BB_FSR411_DIR'] = str(data / 'fsr4_411')

    probe = Path(env['BB_PROBE']) if env.get('BB_PROBE') else find_executable('bb-probe.exe')
    if not probe or not probe.is_file():
        fail('bb-probe.exe not found: build it with build.sh (MSYS2 CLANG64) or use a packaged build.')
    # Development builds run from the MSYS2 tree: its CLANG64 DLLs (SDL3, FFmpeg, ...).
    if not (probe.parent / 'SDL3.dll').is_file():
        clang64 = Path(env.get('MSYS2_ROOT', r'C:\msys64')) / 'clang64' / 'bin'
        if clang64.is_dir():
            env['PATH'] = f'{clang64}{os.pathsep}{env.get("PATH", "")}'

    game = Path(env.get('BB_GAME_DIR', PORT.parent / 'CUSA03173'))
    if not (game / 'eboot.bin').is_file():
        fail(f'No eboot.bin in {game} (set BB_GAME_DIR).')
    original_game = game.resolve()
    if env.get('BB_SKIP_GAME_CHECK') != '1':
        try:
            prepatched = image_sha256(game) == LANCE_60FPS_IMAGE
        except (OSError, ValueError, KeyError, IndexError):
            prepatched = False
        if prepatched:
            fail('This eboot.bin has an incompatible 60 FPS patch. Use a clean 1.09 eboot.bin; '
                 'the port applies its own frame-rate patches.')
    game = Path(run_script('mods.py', game, '--out', out,
                           '--mods-dir', env.get('BB_MODS_DIR', data / 'mods'),
                           '--config', env.get('BB_MODS_CONFIG', data / 'mods.json'),
                           '--enabled', env.get('BB_MODS_ENABLED', '1'), capture=True).strip())
    mod_view = game if game.resolve() != original_game else None
    try:
        sku = env.get('BB_CONTENT_SKU', 'full')
        if prepared_image_is_current(game, out, sku):
            print('Prepared game image: cached; skipping ELF scan and module linking')
        else:
            (out / '.macos-preparation.json').unlink(missing_ok=True)
            run_script('prepare.py', game, '--out', out)
            # link_modules.py imports link_libc.py for its symbol-ID helper, so
            # running link_libc.py as a separate preparation step is redundant.
            run_script('link_modules.py', game, '--out', out)
            run_script('content_profile.py', game, '--out', out, '--sku', sku)
            save_preparation_cache(game, out, sku)

        configure_cpu_compatibility(env, out / 'link.json')
        # Patches exist for game version 01.09 only (patches.py applies none to others): other
        # versions keep the game's 30 FPS timing and change resolutions live.
        sys.path.insert(0, str(PORT / 'scripts'))
        from patches import eboot_matches_patches, game_app_version
        version = game_app_version(game)
        patched = version in (None, '01.09') or bool(env.get('BB_FORCE_PATCHES'))
        if patched and not env.get('BB_FORCE_PATCHES') and not eboot_matches_patches(out / 'eboot.elf'):
            patched = False
            print('Game files: eboot.bin does not match the 01.09 patch fingerprint; '
                  'running at 30 FPS without game patches')
        if not patched:
            print(f'Game version {version}: community patches need 01.09; 30 FPS, no effect patches')
        # Sizes chosen below for the previous launch are recomputed after an in-game restart.
        if env.get('BB_AUTO_RENDER_RES') == '1':
            for key in ('BB_RENDER_RES', 'BB_OUTPUT_RES', 'BB_AUTO_RENDER_RES'):
                env.pop(key, None)
        fps = env.get('BB_FPS', 'uncap') if patched else '30'
        scaled_render = scaled_output = None
        if not env.get('BB_RENDER_RES'):
            printed = run_script('patches.py', '--print-scaled', '--settings', config, capture=True).split()
            if len(printed) == 2:
                scaled_render, scaled_output = printed
        live = '0'
        if scaled_output:
            live = env.get('BB_LIVE_RES') or ini_value(config, 'live_resolution') or '0'
            if live == 'auto':
                caps = probe.parent / 'bb-gpu-capabilities.exe'
                result = subprocess.run([str(caps), '--live-resolution'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        text=True, creationflags=no_console())
                live = result.stdout.strip() if result.returncode == 0 else '0'
            live = '1' if live == '1' or not patched else '0'
        if live == '1':
            print(f'Output {scaled_output}: live resolution changes (live_resolution=0: startup patch)')
        elif scaled_output:
            env.update(BB_RENDER_RES=scaled_render, BB_OUTPUT_RES=scaled_output, BB_AUTO_RENDER_RES='1')
            env.setdefault('BB_DMEM_MB', '9152')
            print(f'Output {scaled_output}: scene {scaled_render}, direct memory {env["BB_DMEM_MB"]} MiB '
                  '(live_resolution=1: live changes)')
        run_script('patches.py', '--out', out, '--fps', fps, '--extra', env.get('BB_PATCHES', ''),
                   '--settings', config, '--game-dir', game, '--render-res', env.get('BB_RENDER_RES', ''),
                   '--output-res', env.get('BB_OUTPUT_RES', ''),
                   '--patches-dir', env.get('BB_PATCHES_DIR', data / 'patches'),
                   '--patches-config', env.get('BB_PATCHES_CONFIG', data / 'patches.json'))
        if not env.get('BB_VBLANK_HZ'):
            env['BB_VBLANK_HZ'] = {'uncap': '0', '90': '90'}.get(fps, '60')

        # The in-game restart starts this script again once this process is gone.
        # GPU caches (shaders, pipelines) beside the saves; read before main(), so set here.
        user_dir = Path(env.get('BB_USER_DIR', data / 'user')).resolve()
        user_dir.mkdir(parents=True, exist_ok=True)
        env.setdefault('BB_GPU_USER_DIR', str(user_dir))
        if env.get('BB_ONLINE') == '1':
            online_overrides(env, user_dir)
        this = ['--run'] if getattr(sys, 'frozen', False) else [str(Path(__file__).resolve())]
        restart = [sys.executable, *this, '--after', str(os.getpid()), *args]
        env['BB_RESTART_COMMAND'] = subprocess.list2cmdline(restart)
        command = [str(probe), str(out / 'boot-linked.bin'), '--content-profile', str(out / 'content.bin'),
                   '--patches', str(out / 'patches.bin'), '--app0', str(game),
                   '--user', str(user_dir),
                   '--timeout', env.get('BB_TIMEOUT', '0'), *args]
        # No stdin: an inherited pipe (shells such as Git Bash) cost the game its console output.
        return subprocess.run(command, stdin=subprocess.DEVNULL, creationflags=no_console()).returncode
    finally:
        if mod_view:
            shutil.rmtree(mod_view, ignore_errors=True)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
