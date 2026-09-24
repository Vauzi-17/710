# Mesa Turnip for Adreno 710 / 720 / 722

Custom-built Turnip (Mesa Freedreno Vulkan driver) for Android, targeting three Adreno A7-series GPUs that upstream Mesa does not officially list as supported. Built for use with Android emulators and native games via driver-swap frontends (e.g. Winlator, GameHub-style loaders).

## Supported GPUs and Their Host Chipsets

Adreno GPU model numbers are shared across multiple Snapdragon chipset tiers, each with a different CPU. This driver targets the **GPU silicon**, not a specific phone, so it should work across all chipsets below — but CPU performance (and therefore real framerate) will vary by device.

| Adreno GPU | Snapdragon chipsets using it |
|---|---|
| **710** | 7s Gen 2, 6 Gen 1, 6 Gen 3, 6s Gen 4 |
| **720** | 7 Gen 3 |
| **722** | 7 Gen 4 |

## Before You Use

- Read the release notes for the specific build you're downloading — behavior differs meaningfully between Mesa 24.x, 25.x, and 26.x branches.
- Check the "known issues" section on each release page before reporting a bug.

## Recommended Usage

- Use **sysmem** mode for better stability on all three GPUs — GMEM mode is more prone to rendering artifacts on this unsupported configuration. Enable it by setting the environment variable `TU_DEBUG=sysmem` before launching the game/emulator.

## Testing

<p align="center">
  <img src="eden-emulator.jpg" width="48%" />
  <img src="winlator-ludashi.png" width="48%" />
</p>

## Available Builds

**Mesa 26.x** (main branch)
[Releases →](https://github.com/Vauzi-17/710/releases)

**Mesa 25.x** (multiple variant builds)
[Releases →](https://github.com/Vauzi-17/710/releases/tag/m25_710-720-722)

**Mesa 24.3.4** (legacy branch)
- [r1](https://github.com/Vauzi-17/710/releases/tag/m24.3.4_710-720-722)
- [r2](https://github.com/Vauzi-17/710/releases/tag/m24.3.4_710-720-722_r2)

Note: in our testing, Mesa 24.3.4 tends to run lower FPS than Mesa 26.x on the same workloads. Try 26.x first unless you have a specific compatibility reason to use the legacy branch.

## Building

Builds come from upstream Mesa `main` ([gitlab.freedesktop.org/mesa/mesa](https://gitlab.freedesktop.org/mesa/mesa)), plus whatever is in [`patches/`](patches/README.md). An empty `patches/` folder means a plain upstream build.

- **GitHub Actions**: run the *Build "turnip"* workflow. Leave the version empty to use the previous release + 1 (3.8 → 3.9, 3.9 → 4.0), or type one yourself. The workflow creates the release, generates the notes, and attaches `Turnip-710-720-722-v<version>.zip`, plus one extra zip for each folder under `patches/variants/`.
- **Weekly build**: the same workflow runs every Sunday at 00:00 UTC with an automatic version and releases the Android build. It is skipped when neither Mesa `main` nor this repo changed since the previous release.
- **Patch check**: every push that touches `patches/` runs the *Check patches* workflow. It applies the patches to the current Mesa `main` without compiling, so a patch that no longer fits upstream shows up in a few minutes.
- **glibc build (experimental, off by default)**: tick the `glibc` input to also build `Turnip-710-720-722-v<version>-glibc.tzst` on a native arm64 runner. This is a Linux glibc build with X11 presentation for Winlator; extract it into the rootfs. The weekly build never includes it. If `ubuntu-24.04-arm` is not available to the repository, set the repository variable `GLIBC_RUNNER` to another arm64 runner label. `patches/glibc/` carries BrunoSX's Winlator changes ported to current Mesa. `TU_OVERRIDE_HEAP_SIZE` is enabled; the "Direct rendering" WSI patches are disabled for now, see [patches/glibc/STATUS.md](patches/glibc/STATUS.md).
- **Locally**: `BUILD_VERSION=3.9 bash turnip_builder.sh`. Output goes to `out/`. The glibc build needs an arm64 Linux machine: `BUILD_VERSION=3.9 BUILD_TARGET=glibc bash turnip_builder.sh`.
- **Check patches only** (no NDK, no compile): `BUILD_VERSION=test PATCH_ONLY=1 bash turnip_builder.sh`.

For a longer "Changes" section, put the text in `release_notes/v<version>.md` before running the workflow.

## Support

Questions or issues: **[t.me/vauzi_17](https://t.me/vauzi_17)**

## Credits

- [whitebelyash](https://github.com/whitebelyash/mesa-tu8) — original A8XX Mesa patchset (gen8 branch) this work is based on
- [Mesa Project](https://gitlab.freedesktop.org/mesa/mesa) — upstream Turnip/Freedreno Vulkan driver
