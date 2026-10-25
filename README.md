# Mesa Turnip Driver

Custom Turnip (Mesa Freedreno Vulkan) builds for Android, with specific hardware tuning for **Adreno 710, 720, 722, and 810**, while retaining broad compatibility across **Adreno 6xx, 7xx, and 8xx**.

## Hardware Coverage
- **Primary Tuning Focus:**
  - **Adreno 710:** Snapdragon 6 Gen 1, 6 Gen 3, 6s Gen 4, 7s Gen 2
  - **Adreno 720:** Snapdragon 7 Gen 3
  - **Adreno 722:** Snapdragon 7 Gen 4
  - **Adreno 810:** Snapdragon 7s Gen 3, 6 Gen 4, 7s Gen 4
- **General Compatibility:** Other Adreno 6xx, 7xx, and 8xx devices supported upstream by Turnip.

## Driver Variants
- `Turnip-*-vX.zip`: Universal baseline build for general use.
- `Turnip-*-vX-sw.zip`: Tuned for Nintendo Switch emulators (Eden, etc.) with sysmem and color pipeline adjustments.
- `Turnip-*-vX-win.zip`: Tuned for Winlator and DirectX emulation (DXVK / VKD3D-Proton).

Latest releases: [GitHub Releases](https://github.com/Vauzi-17/710/releases)

## Runtime Configuration (`default_env.conf`)
Optional environment variables can be overridden at runtime without rebuilding:  
`/sdcard/Android/data/<package_name>/files/default_env.conf`  
*(Recommended baseline: `TU_DEBUG=sysmem` for rendering stability)*

## Building
```bash
BUILD_VERSION=4.5 bash turnip_builder.sh
```

## Credits
Special thanks to **whitebelyash**, **Leb-Sun**, **Max Jividen**, **Alex Sanz**, **Dhruv Mark Collins**, **Hugo223**, and **StevenMX** for their patches, research, and contributions.
