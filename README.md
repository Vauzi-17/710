# Mesa Turnip for Adreno 710 / 720 / 722

Custom Turnip/Freedreno Vulkan driver package for Android emulators and games, with experimental support for unsupported Adreno variants.

### Supported GPU (Experimental Driver)
- **Adreno 710**
- **Adreno 720**
- **Adreno 722**

### Recommended Usage
- Use **sysmem** mode for better stability on these GPUs.
- Performance and compatibility may vary by game/emulator and firmware.

### Available Builds
- **[Mesa 26.x builds](https://github.com/Vauzi-17/710/releases)** (main branch based)
- **[Mesa 25.x builds](https://github.com/Vauzi-17/710/releases/tag/m25_710-720-722)** (multiple 25.x variants)
- **Mesa 24.3.4 builds** (legacy/lower branch option)
  - **[r1](https://github.com/Vauzi-17/710/releases/tag/m24.3.4_710-720-722)**
  - **[r2](https://github.com/Vauzi-17/710/releases/tag/m24.3.4_710-720-722_r2)**

### Mesa 24.3.4 build may have lower FPS than Mesa 26.x in some workloads.

### Credits
- **[whitebelyash](https://github.com/whitebelyash/mesa-tu8)** — Original A8XX Mesa patchset (gen8 branch)
- **[Mesa Project](https://gitlab.freedesktop.org/mesa/mesa)** — Upstream Turnip/Freedreno Vulkan driver

Old README:
<details>
  This is a bash script to build freedreno/turnip for android as a magisk module and an Adreno Tools driver package.

### Scheduled Releases
- Automated releases at 06:00 UTC on the 1st and 15th of each month.

### Notes;

#### Magisk build:
- Root must be visible to target app/game.
- Tested with these apps/games listed [here](list.md).

#### Adreno Tools build:
- Follow application specific instructions to install the driver package.

### To Build Locally
- Obtain the script [turnip_builder.sh](https://raw.githubusercontent.com/ilhan-athn7/freedreno_turnip-CI/main/turnip_builder.sh) on your linux environment. (visit the link and use ```CTRL + S``` keys)
- Execute script on linux terminal ```bash ./turnip_builder.sh```
- To build experimental branchs, change [this](https://github.com/ilhan-athn7/freedreno_turnip-CI/blob/6ef9860e7b755b8b7a83e4ecd398b355a56f9d49/turnip_builder.sh#L11) line, and add one more line to rename unzipped folder to mesa-main.

### References

- https://forum.xda-developers.com/t/getting-freedreno-turnip-mesa-vulkan-driver-on-a-poco-f3.4323871/

- https://gitlab.freedesktop.org/mesa/mesa/-/issues/6802

- https://github.com/bylaws/libadrenotools

</details>
