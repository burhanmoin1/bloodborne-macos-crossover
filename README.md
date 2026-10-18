# Bloodborne MacOS

Hey, I’m Burhan Moin, a full-stack developer and software engineer from
Pakistan. I got into Mac gaming after buying my first Mac, an M1 Pro, last
year. I tried Bloodborne through shadPS4, but on my machine it was too slow to
enjoy. The work on the Bloodborne PC port by
[Supermedo](https://github.com/Supermedo/bloodborne_pc) and
[deadinside28](https://github.com/deadinside28/bloodborne_pc) gave me a way to
try a different route.

This project keeps the port’s familiar launcher and runs it through the
CrossOver Wine runner, with Mesa KosmicKrisp translating Vulkan to Metal. I’ve
reached gameplay on my M1 Pro with 16 GB of memory. This is an early community
build, and I’m hoping other Mac users can help me improve it over time. The
app is unofficial and is not affiliated with Sony, FromSoftware, CodeWeavers,
or the port’s authors.

## Version 0.2.3

This is an early community release, not a promise of consistent performance yet. On my
M1 Pro, gameplay has ranged from around 15 to 30 FPS depending on the area and
settings. Low frame rates can make the game feel like slow motion, and I’ve
noticed occasional audio crackling. A full playthrough and 60 FPS at 1080p have
not been verified. Reports from other Macs will help show what works and what
needs attention.

## What it does

The app uses the existing Tkinter interface and detects installed CrossOver
versions in `/Applications` and `~/Applications`, including stable and preview
installations. Choose a detected CrossOver runner in the app and select your
own Bloodborne game folder. You don’t need to create a bottle or add the EXE
to CrossOver by hand; the launcher starts CrossOver’s Wine runner directly and
keeps its compatibility data in the app’s own support folder.

```text
Bloodborne MacOS launcher
        ↓
CrossOver Wine runner (x86-64 under Rosetta)
        ↓
Vulkan loader + Mesa KosmicKrisp
        ↓
Apple Metal on Apple Silicon
```

The Mac interface offers FSR 3.1, TAA, and Off. NVIDIA DLSS and FSR 4 options
from the Windows launcher are not shown because they are not suitable for the
Apple Silicon graphics path used here.

## Requirements

- Apple Silicon Mac with Rosetta 2.
- macOS 26 or newer for the Metal 4 features used by KosmicKrisp.
- CrossOver. CrossOver 26.3 is the version I used for the gameplay report.
- Your own legally obtained Bloodborne CUSA03173 game dump, with `eboot.bin`.

## Download and launch

Download **Bloodborne-MacOS-0.2.3.dmg** from the
[GitHub Releases](https://github.com/burhanmoin1/bloodborne-macos/releases)
page. Open the DMG and drag **Bloodborne MacOS.app** to Applications. Start
the app, select the folder containing `eboot.bin` under **Game & effects**,
choose a detected CrossOver version on the Play page, and press **PLAY**.

On first launch, the app asks before downloading the verified Bloodborne PC
port runtime and the Vulkan/KosmicKrisp components (about 150 MB total). It
does not include or download the game itself. The launcher, runtime, saves,
settings, and compatibility data are kept separately from your game folder at:

```text
~/Library/Application Support/Bloodborne macOS/
```

This release is ad-hoc signed and not notarized. If Gatekeeper blocks it,
Control-click the app in Finder, choose **Open**, then confirm once.

## Current limitations

- Performance varies by scene, settings, CrossOver version, and Mac. My M1 Pro
  has reached about 30 FPS in some areas and dropped to about 15 FPS in others.
- Low FPS can make gameplay feel slow. I’ve also heard slight audio crackling.
- A complete playthrough and stable 1080p/60 FPS have not been confirmed.
- Online play, mods, and optional patches come from the Windows port and have
  not been fully checked through CrossOver.
- This release uses the pinned Bloodborne PC port v1.9 runtime and shadPS4
  macOS v0.20.0 graphics components. The CrossOver adapter accepts only the
  verified v1.6 and v1.9 probe executables; unknown builds are rejected.
- The v1.9 CrossOver patch reserves 4 GiB rather than 8 GiB for the system on
  integrated GPUs. The launcher leaves `BB_GC_BUDGET_MB` unset so the runtime
  uses its own texture-cache policy. Setting `BB_GC_BUDGET_MB` applies an
  explicit cache budget in MiB; larger budgets may increase macOS memory
  pressure and swap, especially with other memory-heavy apps open.
- CrossOver reports AVX as unavailable in CPUID on Apple Silicon even though
  its Rosetta runner executes AVX. The Mac launcher skips that CPU feature gate
  and enables the port's experimental legacy-instruction translations.
- Frame generation is not exposed on macOS. The Mac UI keeps to the graphics
  modes validated for the Apple Silicon CrossOver path.

The app downloads the Windows runtime and graphics components on first use,
checks their published SHA-256 values, and extracts the needed files locally.
They are not committed to this repository. The launcher log is under the
Application Support folder shown above, inside `compatdata/bloodborne/`.

## Help and contribute

If you try the app, please join the
[Bloodborne MacOS Discord](https://discord.gg/zTPg9kH4h), share how it runs on
your Mac, and let me know what breaks. Include your Mac chip and memory,
macOS and CrossOver versions, game area, graphics settings, and approximate
FPS when reporting a problem. Please don’t post game files or your game dump.

If the project is useful to you, a GitHub star helps other Mac players find
it. Donations are optional and help me save toward a more capable Mac and a
monitor so I can keep working on the project. For USDT on BNB Smart Chain
(BEP-20):

```text
0xd719a01f3fdfddd1dc5927756159229e486d6bbe
```

## Build from source

You’ll need an Apple Silicon Mac, Python 3.13 with Tk support, and MinGW-w64.
Then run:

```sh
brew install mingw-w64
./build_macos.sh
./package_dmg.sh
```

The app is built at `dist/Bloodborne MacOS.app`; the DMG is
`dist/Bloodborne-MacOS-0.2.3.dmg`. `BB_APP_VERSION` can be set when building a
different version. For source development, double-click
`Launch Bloodborne.command` to open the same launcher.

For a direct CrossOver launch from a terminal, run `bash ./run-crossover.sh`.
It reads the game, CrossOver runner, and save folder from the launcher settings,
so it uses the same saves as the app. Each run is logged under `./logs/` in the
current working directory; the `latest` link points to the newest run. Set
`BB_RUN_LOGS_DIR` to choose another log directory.
