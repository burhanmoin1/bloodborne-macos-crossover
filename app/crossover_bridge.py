#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Launch Bloodborne through CrossOver's raw Wine loader, as NotProton does.

No CrossOver bottle commands are used. A private Wine prefix is initialized
automatically in compatdata/bloodborne/<runner>/pfx; existing CrossOver and Steam game
environments are never selected or changed.
"""
import argparse
import hashlib
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import threading
import time

from patch_windows_runtime import patch

APP_DIR = Path(__file__).resolve().parent
WORKSPACE = Path(os.environ.get("BB_WORKSPACE", APP_DIR.parent)).expanduser().resolve()


def windows_path(path: Path) -> str:
    return "Z:" + str(path.resolve()).replace("/", "\\")


def stage_vendor_scripts(port: Path):
    """Install the current app scripts where the port's run.py loads them."""
    vendor_scripts = APP_DIR / "vendor_scripts"
    if not vendor_scripts.is_dir():
        return
    runtime_scripts = port / "scripts"
    runtime_scripts.mkdir(parents=True, exist_ok=True)
    for source in vendor_scripts.glob("*.py"):
        target = runtime_scripts / source.name
        if not target.is_file() or target.read_bytes() != source.read_bytes():
            shutil.copy2(source, target)


def process_tree_usage(root_pid: int, target_process: str | None = None):
    try:
        result = subprocess.run(["/bin/ps", "-axo", "pid=,ppid=,time=,rss=,args="],
                                capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None

    processes = {}
    for line in result.stdout.splitlines():
        fields = line.split(maxsplit=4)
        if len(fields) < 4:
            continue
        try:
            pid, parent = int(fields[0]), int(fields[1])
            day_text, separator, clock = fields[2].partition("-")
            day_seconds = int(day_text) * 86400 if separator else 0
            time_value = clock if separator else day_text
            time_parts = [float(part) for part in time_value.split(":")]
            if len(time_parts) == 3:
                cpu_seconds = day_seconds + time_parts[0] * 3600 + time_parts[1] * 60 + time_parts[2]
            elif len(time_parts) == 2:
                cpu_seconds = day_seconds + time_parts[0] * 60 + time_parts[1]
            else:
                cpu_seconds = time_parts[0]
            command = fields[4] if len(fields) == 5 else ""
            processes[pid] = (parent, cpu_seconds, int(fields[3]), command)
        except ValueError:
            continue

    roots = ({pid for pid, process in processes.items() if target_process in process[3]}
             if target_process else set())
    if not roots:
        if root_pid not in processes:
            return None
        roots = {root_pid}
    tree = set(roots)
    while True:
        children = {pid for pid, (parent, _cpu, _rss, _command) in processes.items()
                    if parent in tree}
        if children <= tree:
            break
        tree.update(children)
    return (sum(processes[pid][1] for pid in tree),
            sum(processes[pid][2] for pid in tree), len(tree))


def system_memory_free_percent():
    try:
        result = subprocess.run(["/usr/bin/memory_pressure", "-Q"],
                                capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in result.stdout.splitlines():
        if line.startswith("System-wide memory free percentage:"):
            return line.rsplit(" ", 1)[-1].removesuffix("%")
    return None


def runner_root(override: Path | None) -> Path:
    candidates = [override] if override else [
        Path("/Applications/CrossOver.app/Contents/SharedSupport/CrossOver"),
        Path.home() / "Applications/CrossOver.app/Contents/SharedSupport/CrossOver",
        *[bundle / "Contents/SharedSupport/CrossOver" for bundle in Path("/Applications").glob("CrossOver*.app")],
        *[bundle / "Contents/SharedSupport/CrossOver" for bundle in
          (Path.home() / "Applications").glob("CrossOver*.app")],
        Path.home() / "Library/Application Support/notproton/runners/current",
    ]
    for root in candidates:
        if root and (root / "lib/wine/x86_64-unix/wine").is_file():
            return root.resolve()
    raise FileNotFoundError("CrossOver's Rosetta Wine runner was not found.")


def launch(args) -> int:
    root = runner_root(args.runner)
    port = args.port_dir.resolve()
    runner_id = hashlib.sha256(str(root).encode()).hexdigest()[:8]
    data_dir = (args.data_dir or WORKSPACE).expanduser().resolve()
    compat = data_dir / "compatdata/bloodborne" / runner_id
    compat.mkdir(parents=True, exist_ok=True)
    local_graphics = APP_DIR / "resources/kosmickrisp"
    graphics = args.graphics_dir or Path(os.environ.get("BB_KOSMICKRISP_DIR", local_graphics))
    if not graphics.is_dir():
        graphics = WORKSPACE / "macos-runtime/kosmickrisp"
    graphics = graphics.expanduser().resolve()
    driver_config = graphics / "kosmickrisp_mesa_icd.json"
    if not driver_config.is_file() or not (graphics / "libMoltenVK.dylib").is_file():
        raise FileNotFoundError("The Bloodborne KosmicKrisp runtime is missing from macos-runtime/kosmickrisp.")
    loader = root / "lib/wine/x86_64-unix/wine"
    server = root / "bin/wineserver"
    bootstrap = port / "bin/bb-crossover-bootstrap.dll"
    bootstrap_source = Path(__file__).with_name("crossover_bootstrap.c")
    if not bootstrap.exists() or bootstrap.stat().st_mtime < bootstrap_source.stat().st_mtime:
        compiler = shutil.which("x86_64-w64-mingw32-gcc")
        if compiler:
            subprocess.run([compiler, "-shared", "-nostdlib", "-O2", str(bootstrap_source),
                            "-lkernel32", "-luser32", "-Wl,--entry,DllMain", "-o", str(bootstrap)], check=True)
        else:
            bundled = APP_DIR / "resources/bb-crossover-bootstrap.dll"
            if not bundled.is_file():
                raise FileNotFoundError("The CrossOver TLS adapter is missing from this macOS app build.")
            shutil.copy2(bundled, bootstrap)
    # Use a product name for the patched helper: CrossOver exposes the PE
    # executable basename as the app's Dock tooltip.
    patched = patch(port / "bin/bb-probe.exe", port / "bin/Bloodborne MacOS.exe")
    # The upstream Windows launcher executes PORT/run.py from disk. Ship the
    # macOS-specific wrapper with this app so it can cache the expensive ELF
    # preparation while continuing to use the verified CrossOver runtime.
    mac_run = APP_DIR / "macos_run.py"
    if mac_run.is_file():
        run_script = port / "run.py"
        source_bytes = mac_run.read_bytes()
        if not run_script.is_file() or run_script.read_bytes() != source_bytes:
            temporary = port / ".run.py.macos-tmp"
            temporary.write_bytes(source_bytes)
            temporary.replace(run_script)
    stage_vendor_scripts(port)
    environment = dict(os.environ)
    for key in ("CX_BOTTLE", "CX_INITIALIZED", "WINEPREFIX", "WINELOADER", "WINESERVER", "WINEDLLPATH"):
        environment.pop(key, None)
    environment.update({
        "CX_ROOT": str(root),
        "CX_HOME": str(Path.home() / "Library/Application Support/CrossOver"),
        "WINEPREFIX": str(compat / "pfx"),
        "WINELOADER": str(loader),
        "WINESERVER": str(server),
        "WINEDLLPATH": f"{root}/lib/wine/x86_64-windows:{root}/lib/wine/x86_64-unix",
        "WINEMSYNC": "0",
        "WINEDEBUG": "-all",
        "PATH": f"{root}/bin:" + environment.get("PATH", "/usr/bin:/bin"),
        "BB_PROBE": windows_path(patched),
        "BB_MACOS_CROSSOVER": "1",
        # CrossOver reports VirtualApple without AVX in CPUID, although the
        # Rosetta runner executes AVX (verified by a CrossOver smoke test).
        "BB_SKIP_CPU_CHECK": "1",
        # Wine's macOS backend loads libMoltenVK by name. Here that name routes
        # to the Vulkan loader, which selects KosmicKrisp through its ICD file.
        "DYLD_LIBRARY_PATH": str(graphics) + (":" + environment["DYLD_LIBRARY_PATH"]
                                             if environment.get("DYLD_LIBRARY_PATH") else ""),
        "VK_DRIVER_FILES": str(driver_config),
        "VK_ICD_FILENAMES": str(driver_config),
    })
    # Keep the launcher's settings authoritative. Both the two-stage GPU
    # command pipeline and speculative draw workers stay off by default: the
    # synchronous renderer path is the known working CrossOver configuration.
    # Advanced users can opt in with BB_PREP_WORKERS in the extra environment.
    environment.setdefault("BB_DRAW_PIPE", "0")
    environment.setdefault("BB_PREP_WORKERS", "0")
    environment.setdefault("BB_FPS", "uncap")
    shared = root / "lib64/apple_gptk/external/libd3dshared.dylib"
    if shared.is_file():
        environment["CX_APPLEGPTK_LIBD3DSHARED_PATH"] = str(shared)
    if args.vulkan_only:
        command = [str(loader), str(patched), "--vulkan-only"]
    else:
        game = args.game_dir or (Path(environment["BB_GAME_DIR"]).expanduser()
                                 if environment.get("BB_GAME_DIR") else None)
        if game is None:
            games = sorted((WORKSPACE / "game").glob("*/eboot.bin"))
            if len(games) != 1:
                raise FileNotFoundError("Specify --game-dir containing your eboot.bin.")
            game = games[0].parent
        if not (game / "eboot.bin").is_file():
            raise FileNotFoundError(f"No eboot.bin in {game}")
        config = Path(environment.get("BB_CONFIG", port / "bbport-macos.ini")).expanduser()
        if not config.is_absolute():
            config = port / config
        if not config.exists():
            config.parent.mkdir(parents=True, exist_ok=True)
            original_path = port / "bbport-macos.ini"
            if not original_path.exists():
                original_path = port / "bbport.ini"
            original = original_path.read_text()
            replacements = {"upscaler": "off", "output_res": "1280x720", "live_resolution": "0"}
            config.write_text("\n".join(
                f"{line.split('=', 1)[0]}={replacements[line.split('=', 1)[0]]}"
                if "=" in line and line.split("=", 1)[0] in replacements else line
                for line in original.splitlines()) + "\n")
        # Host paths selected in the macOS UI must be translated to Wine's Z:
        # mapping before run.py/probe.exe receive them.
        gpu_user = environment.get("BB_GPU_USER_DIR")
        if not gpu_user:
            user_dir = environment.get("BB_USER_DIR")
            gpu_user = user_dir or str(Path(environment.get("BB_DATA_DIR", port)) / "user")
        for key in ("BB_GAME_DIR", "BB_DATA_DIR", "BB_CONFIG", "BB_USER_DIR", "BB_MODS_DIR",
                    "BB_MODS_CONFIG", "BB_PATCHES_DIR", "BB_PATCHES_CONFIG", "BB_GPU_USER_DIR",
                    "BB_FSR411_DIR"):
            value = environment.get(key)
            if value and not (len(value) >= 2 and value[1] == ":"):
                environment[key] = windows_path(Path(value).expanduser())
        environment.setdefault("BB_GAME_DIR", windows_path(game))
        environment["BB_CONFIG"] = windows_path(config)
        environment["BB_GPU_USER_DIR"] = (gpu_user if len(gpu_user) >= 2 and gpu_user[1] == ":"
                                            else windows_path(Path(gpu_user).expanduser()))
        extra = ["--cpu-only"] if args.cpu_only else []
        if args.prepared:
            command = [str(loader), str(patched), windows_path(port / "out/boot-linked.bin"),
                       "--content-profile", windows_path(port / "out/content.bin"),
                       "--patches", windows_path(port / "out/patches.bin"),
                       "--app0", windows_path(game), "--user", windows_path(port / "user"), *extra]
        else:
            command = [str(loader), str(port / "Bloodborne.exe"), "--run", *extra]
    log_path = compat / "launch.log"
    print(f"CrossOver runner: {root}", flush=True)
    if environment.get("BB_GC_BUDGET_MB"):
        print(f"Texture-cache budget override: {environment['BB_GC_BUDGET_MB']} MiB", flush=True)
    print(f"Launch log: {log_path}", flush=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log_lock = threading.Lock()
        stop_requested = threading.Event()

        def request_stop(_signum, _frame):
            stop_requested.set()

        # Install handlers before Popen; Stop can be pressed as soon as the
        # process appears in the UI, including during Wine startup.
        old_term = signal.signal(signal.SIGTERM, request_stop)
        old_int = signal.signal(signal.SIGINT, request_stop)
        process = None

        def stop_runtime():
            if process and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            # wineserver owns processes that may have detached from the loader.
            try:
                subprocess.run([str(server), "-k"], env=environment,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            except subprocess.TimeoutExpired:
                pass
            if process and process.poll() is None:
                try:
                    process.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()

        def write_log(line):
            with log_lock:
                log.write(line)
                log.flush()
                sys.stdout.write(line)
                sys.stdout.flush()

        relay = None
        usage_stop = threading.Event()
        usage_thread = None
        try:
            if stop_requested.is_set():
                return 143
            process = subprocess.Popen(command, cwd=port, env=environment, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, start_new_session=True)

            def relay_output():
                for raw in iter(process.stdout.readline, b""):
                    write_log(raw.decode("utf-8", errors="replace"))

            def sample_usage():
                target_process = Path(patched).name
                previous = process_tree_usage(process.pid, target_process)
                previous_at = time.monotonic()
                while not usage_stop.wait(1):
                    current = process_tree_usage(process.pid, target_process)
                    current_at = time.monotonic()
                    if current is None:
                        continue
                    elapsed = current_at - previous_at
                    if previous is None:
                        cpu_percent = 0.0
                    else:
                        cpu_percent = max(0.0, current[0] - previous[0]) * 100 / elapsed
                    free_percent = system_memory_free_percent()
                    memory = (f"system memory free {free_percent}%" if free_percent is not None
                              else "system memory free unavailable")
                    line = (f"Performance ({elapsed:.1f}s): CPU {cpu_percent:.1f}% "
                            f"({cpu_percent / 100:.2f} cores), RSS {current[1] / 1024:.0f} MiB "
                            f"(process-tree sum), processes {current[2]}, {memory}\n")
                    write_log(line)
                    previous, previous_at = current, current_at

            frame_stats = "on" if environment.get("BB_FRAME_STATS") == "1" else "off"
            gpu_profile = "on" if environment.get("BB_GPU_PROFILE") == "1" else "off"
            write_log(f"Performance telemetry: frame statistics {frame_stats}, "
                      f"GPU pass profiling {gpu_profile}; host CPU/RSS/memory pressure sampled every second.\n")
            write_log("GPU utilization, draw-call counts, and per-asset shader/texture load events "
                      "are not exposed by the bundled runtime.\n")
            usage_thread = threading.Thread(target=sample_usage, daemon=True)
            usage_thread.start()

            relay = threading.Thread(target=relay_output, daemon=True)
            relay.start()
            deadline = None if args.limit_seconds is None else time.monotonic() + args.limit_seconds
            while True:
                if stop_requested.is_set():
                    stop_runtime()
                    status = 143
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    stop_runtime()
                    status = 124
                    break
                try:
                    status = process.wait(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            usage_stop.set()
            if usage_thread:
                usage_thread.join(timeout=6)
            signal.signal(signal.SIGTERM, old_term)
            signal.signal(signal.SIGINT, old_int)
        if relay:
            relay.join(timeout=5)
    if status:
        print(f"Launch ended with status {status}. Last log lines:", file=sys.stderr)
        print("\n".join(log_path.read_text(errors="replace").splitlines()[-25:]), file=sys.stderr)
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port-dir", type=Path, default=WORKSPACE / "bbport-windows")
    parser.add_argument("--data-dir", type=Path, help="Writable macOS app data and compatibility data directory")
    parser.add_argument("--graphics-dir", type=Path, help="Directory containing the KosmicKrisp loader and ICD")
    parser.add_argument("--game-dir", type=Path)
    parser.add_argument("--runner", type=Path)
    parser.add_argument("--vulkan-only", action="store_true")
    parser.add_argument("--cpu-only", action="store_true")
    parser.add_argument("--prepared", action="store_true", help="Use already prepared out/ files")
    parser.add_argument("--limit-seconds", type=float, help="Stop this launch after a diagnostic interval")
    try:
        sys.exit(launch(parser.parse_args()))
    except (OSError, ValueError) as error:
        print(f"Cannot launch: {error}", file=sys.stderr)
        sys.exit(1)
