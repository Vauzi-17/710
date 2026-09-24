#!/usr/bin/env python3
"""Winlator X11 WSI: present through the window's hardware buffer.

Replaces src/vulkan/wsi/wsi_common_x11.c with the Winlator X11 WSI from
brunodev85/mesa3d-custom (turnip-26.1.0-devel), adapted to current Mesa main
(three-argument vk_foreach_struct) and extended to accept both
MESA_VK_WSI_USE_HWBUF (Winlator app <= 32) and MESA_VK_WSI_NATIVE_MEM_IMPORTED
(app 33+, "Direct rendering"). Without either variable it presents through
MIT-SHM / PutImage.

Needs 01-winlator-wsi-common.patch (hwbuf_fd, wsi_init_pthread_cond_monotonic).
Run from the Mesa source root.
"""
import shutil
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "winlator-wsi" / "wsi_common_x11.c"
DST = Path("src/vulkan/wsi/wsi_common_x11.c")

if not DST.exists():
    sys.exit(f"{DST} not found, run from the Mesa source root")

private_h = Path("src/vulkan/wsi/wsi_common_private.h").read_text()
if "hwbuf_fd" not in private_h:
    sys.exit("hwbuf_fd missing from wsi_common_private.h; apply 01-winlator-wsi-common.patch first")

if DST.read_bytes() == SRC.read_bytes():
    print(f"{DST}: already the Winlator version")
else:
    shutil.copyfile(SRC, DST)
    print(f"{DST}: replaced with the Winlator X11 WSI")
