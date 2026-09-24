Helper data for `../02-winlator-x11-wsi.py`, not applied on its own.

`wsi_common_x11.c` is the Winlator X11 WSI by BrunoSX, taken from
[brunodev85/mesa3d-custom](https://github.com/brunodev85/mesa3d-custom)
(`turnip-26.1.0-devel/src/vulkan/wsi/wsi_common_x11.c`), MIT licensed like
the rest of Mesa. Changes from that copy:

- `vk_foreach_struct` uses the three-argument form current Mesa main has.
- `wsi_x11_use_hwbuf()` accepts `MESA_VK_WSI_NATIVE_MEM_IMPORTED` (Winlator
  app 33+) as well as `MESA_VK_WSI_USE_HWBUF`.
