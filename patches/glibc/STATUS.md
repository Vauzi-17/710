# Status of the Winlator patches

## History

The first port (September 2026) copied only `wsi_common_x11.c` from
brunodev85/mesa3d-custom into Mesa main. On Adreno 710 with Winlator 11.2 it
gave a black Test Direct3D window with Direct rendering on and a crash with it
off. Two causes, found in the source:

1. The glibc build used `-Dfreedreno-kmds=kgsl`. Mesa then drops libdrm
   (`system_has_kms_drm = false`), so `wsi_common_drm.c` was not compiled,
   and `WSI_IMAGE_TYPE_DRM` images, which the Winlator WSI always uses, hit
   `UNREACHABLE("Invalid image type")` in `wsi_configure_image()`.
2. `MESA_VK_WSI_NATIVE_MEM_IMPORTED` was aliased to the old hardware-buffer
   path. The official Winlator Turnip builds do not do that.

## Current setup

- `01-winlator-wsi.py`: the whole Winlator WSI (core + DRM + X11), not only
  the X11 file.
- The glibc build uses `-Dfreedreno-kmds=kgsl,msm`, like BrunoSX's builds, so
  libdrm and `wsi_common_drm.c` are included. The driver then needs
  `libdrm.so.2`, which the official builds also need.
- `03-tu-override-heap-size.py` and `04-tu-linear-rgba8-msaa.patch`: the
  Turnip changes of the official builds.

Compiled against Mesa main 9315107; not yet tested on device.
