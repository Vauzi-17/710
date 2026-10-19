#!/usr/bin/env python3
"""Mark swapped mutable images kept tiled by 30-tu-z-mutable.py as is_mutable.

30-tu-z-mutable.py keeps MUTABLE_FORMAT images tiled even when their format
list mixes swapped and unswapped formats (B8G8R8A8 with R8G8B8A8, B5G6R5 with
R5G6B5, ...). Tiled surfaces without is_mutable use WZYX for every view, so a
view with the other swap reads red and blue exchanged. With is_mutable set,
fdl uses the real swap for each view and sets MUTABLEEN in the texture,
render target, 2D blit and resolve descriptors, which is how upstream handles
mutable tiled images on a7xx gen3. This applies the same path on a7xx GPUs
without ubwc_all_formats_compatible (FD710/720/722), for every swapped format.

Needs 30-tu-z-mutable.py applied first (it anchors on its code).
Env TU_Z_MUTABLE_SWAP (default true) turns it on/off.

Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = "34-tu-z-mutable-swap.py"
MARKER = "TU_Z_MUTABLE_SWAP"
IMAGE = "src/freedreno/vulkan/tu_image.cc"

EDITS = [
    (IMAGE,
     'DEBUG_GET_ONCE_NUM_OPTION(tu_z_mutable, "TU_Z_MUTABLE", ',
     'DEBUG_GET_ONCE_BOOL_OPTION(tu_z_mutable_swap, "TU_Z_MUTABLE_SWAP", true)\n'
     'DEBUG_GET_ONCE_NUM_OPTION(tu_z_mutable, "TU_Z_MUTABLE", ',
     1),
    (IMAGE,
     '            if (r8g8_r16 || (fmt_list_has_swaps && z_mutable < 1)) {\n'
     '               ubwc_enabled = false;\n'
     '               force_linear_tile = true;\n'
     '            }\n',
     '            if (r8g8_r16 || (fmt_list_has_swaps && z_mutable < 1)) {\n'
     '               ubwc_enabled = false;\n'
     '               force_linear_tile = true;\n'
     '            } else if (fmt_list_has_swaps &&\n'
     '                       device->physical_device->info->chip >= 7 &&\n'
     '                       debug_get_option_tu_z_mutable_swap()) {\n'
     '               is_mutable = true;\n'
     '            }\n',
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
                  f"needs 30-tu-z-mutable.py first, patch skipped")
            return 0
        files[path] = files[path].replace(old, new)
    for path, s in files.items():
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(s)
    print(f"{NAME}: applied (TU_Z_MUTABLE_SWAP default on)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
