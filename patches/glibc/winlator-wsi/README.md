Helper data for `../01-winlator-wsi.py`, not applied on its own.

These are the Vulkan WSI files by BrunoSX from
[brunodev85/mesa3d-custom](https://github.com/brunodev85/mesa3d-custom)
(`turnip-26.1.0-devel/src/vulkan/wsi/`), MIT licensed like the rest of
Mesa. Changes from that copy, all needed to build against current Mesa main:

- `vk_foreach_struct` / `vk_foreach_struct_const` use the three-argument form.
- `wsi_common.c`/`.h` add `wsi_instance_supports_google_display_timing()`,
  returning false, because Turnip on main calls it.

`wsi_common_x11.c` only recognizes `MESA_VK_WSI_USE_HWBUF`, like the official
Winlator Turnip builds. `MESA_VK_WSI_NATIVE_MEM_IMPORTED` (Winlator app 33
"Direct rendering") is ignored there too, so the DRI3 path is used.
