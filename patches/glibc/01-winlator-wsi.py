#!/usr/bin/env python3
"""Winlator WSI: BrunoSX's Vulkan WSI from brunodev85/mesa3d-custom.

Replaces the WSI files in src/vulkan/wsi/ with the Winlator versions from
turnip-26.1.0-devel. Taking the whole set, and not just wsi_common_x11.c, keeps
the X11 code and the WSI core it was written against consistent. That
combination is what the official Winlator Turnip builds use:
- presentation through DRI3 PixmapFromBuffer (dma-buf), or through the
  window's hardware buffer when MESA_VK_WSI_USE_HWBUF=1;
- no dma-buf sync files; MESA_VK_WSI_FORCE_WAIT_FOR_FENCES=1 waits for the
  rendering fence before presenting.

Needs libdrm in the build (-Dfreedreno-kmds=kgsl,msm): without it
wsi_common_drm.c is not compiled and the DRM image path is undefined.

Adapted to current Mesa main: three-argument vk_foreach_struct, and a
wsi_instance_supports_google_display_timing() stub (this WSI has no
VK_GOOGLE_display_timing). Run from the Mesa source root.
"""
import shutil
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "winlator-wsi"
DST = Path("src/vulkan/wsi")
FILES = [
    "wsi_common.c",
    "wsi_common.h",
    "wsi_common_private.h",
    "wsi_common_drm.c",
    "wsi_common_x11.c",
    "wsi_common_headless.c",
    "wsi_common_display.c",
]

if not DST.is_dir():
    sys.exit(f"{DST} not found, run from the Mesa source root")

changed = 0
for name in FILES:
    src, dst = SRC / name, DST / name
    if not dst.exists():
        sys.exit(f"{dst} does not exist in this Mesa tree; the WSI layout changed")
    if dst.read_bytes() != src.read_bytes():
        shutil.copyfile(src, dst)
        changed += 1
print(f"{DST}: {changed} of {len(FILES)} files replaced with the Winlator WSI")
