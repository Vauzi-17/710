#!/usr/bin/env python3
"""Turnip-Z port: keep MUTABLE_FORMAT images tiled (and UBWC) on all GPUs
including A6xx, A7xx (FD710) and A8xx (FD810/A830/A840).

Env TU_Z_MUTABLE (default 2):
  0  upstream behavior (linear + no UBWC when the format list has swaps)
  1  stay tiled, UBWC off
  2  stay tiled, UBWC kept (Turnip-Z default, both for !mutable_ubwc_fc and mutable_ubwc_fc)
R8G8<->R16 reinterpretation always falls back to linear, as upstream.

Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = "30-tu-z-mutable.py"
MARKER = "TU_Z_MUTABLE"
IMAGE = "src/freedreno/vulkan/tu_image.cc"

EDITS = [
    (IMAGE,
     '#include "tu_wsi.h"\n',
     '#include "tu_wsi.h"\n'
     '\n'
     'DEBUG_GET_ONCE_NUM_OPTION(tu_z_mutable, "TU_Z_MUTABLE", 2)\n',
     1),
    (IMAGE,
     '         } else if (!mutable_ubwc_fc) {\n'
     '            if (ubwc_enabled) {\n',
     '         } else if (!mutable_ubwc_fc) {\n'
     '            int64_t z_mutable = debug_get_option_tu_z_mutable();\n'
     '            if (ubwc_enabled && z_mutable < 2) {\n',
     1),
    (IMAGE,
     '            if (r8g8_r16 || fmt_list_has_swaps) {\n',
     '            if (r8g8_r16 || (fmt_list_has_swaps && z_mutable < 1)) {\n',
     1),
    (IMAGE,
     '         } else {\n'
     '            is_mutable = true;\n'
     '            if (!format_list_ubwc_possible(device, fmt_list, pCreateInfo))\n'
     '               ubwc_enabled = false;\n'
     '         }\n',
     '         } else {\n'
     '            is_mutable = true;\n'
     '            int64_t z_mutable = debug_get_option_tu_z_mutable();\n'
     '            if (z_mutable < 2 && !format_list_ubwc_possible(device, fmt_list, pCreateInfo))\n'
     '               ubwc_enabled = false;\n'
     '         }\n',
     1),
]


def main():
    files = {}
    for path, _, _, _ in EDITS:
        if path not in files:
            try:
                files[path] = open(path, encoding="utf-8").read()
            except OSError as e:
                print(f"{NAME}: WARNING cannot read {path}: {e}; skipped")
                return 0
    if any(MARKER in s for s in files.values()):
        print(f"{NAME}: already applied")
        return 0
    for path, old, new, count in EDITS:
        found = files[path].count(old)
        if found != count:
            print(f"{NAME}: WARNING anchor matched {found}x (want {count}) in {path}; "
                  f"upstream changed, patch skipped")
            return 0
        files[path] = files[path].replace(old, new)
    for path, s in files.items():
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(s)
    print(f"{NAME}: applied (TU_Z_MUTABLE, default 2, covers A8xx/A7xx)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
