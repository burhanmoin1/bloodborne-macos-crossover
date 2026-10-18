# Third-party notices

The launcher UI and selected helper code are adapted from the GPL-2.0
`Supermedo/bloodborne_pc` project. Its upstream source and release are at
<https://github.com/Supermedo/bloodborne_pc>. This repository carries the
upstream GPL-2.0 license in `LICENSE`.

The macOS app icon in `app/resources/bloodborne.ico` is the launcher icon from
the same upstream project; the build converts it to an `.icns` file.

On first launch, Bloodborne MacOS can download the Windows port v1.9 release
from the upstream project and the Vulkan loader/KosmicKrisp files from the
official shadPS4 macOS v0.20.0 release. It verifies the published archive
SHA-256 values and extracts only the files it needs into the user's macOS
Application Support folder. These runtime binaries are not checked into this
repository.

KosmicKrisp is Mesa's Vulkan implementation for Apple Silicon and uses Metal 4.
Its source and build project are available at
<https://github.com/shadexternals/mesa-kosmickrisp> and
<https://docs.mesa3d.org/drivers/kosmickrisp.html>. The Vulkan loader source is
at <https://github.com/KhronosGroup/Vulkan-Loader>. The app does not include
either project's runtime binaries in source or GitHub releases.

CrossOver is proprietary software from CodeWeavers. It is detected on the
user's Mac and is not bundled here.
