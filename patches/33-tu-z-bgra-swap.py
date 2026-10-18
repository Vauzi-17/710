#!/usr/bin/env python3
"""Turnip-Z port: real color swap for B8G8R8A8 on tiled images.

Upstream fd6_pipe2swap returns WZYX for every tiled, non-mutable surface.
With 30-tu-z-mutable.py, MUTABLE_FORMAT BGRA images stay tiled while the game
also views them as RGBA (or the other way round), which shows up as swapped
red/blue (for example blue character skin). Turnip-Z gives
PIPE_FORMAT_B8G8R8A8_UNORM/_SRGB their table swap (WXYZ) on every path,
tiled or not; this patch does the same in fd6_pipe2swap, which feeds the
render target, texture, blit and clear descriptors.

Env TU_Z_BGRA_SWAP (default true) turns it on/off.

Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = "33-tu-z-bgra-swap.py"
MARKER = "TU_Z_BGRA_SWAP"
TABLE = "src/freedreno/fdl/fd6_format_table.c"

EDITS = [
    (TABLE,
     '#include "freedreno_dev_info.h"\n',
     '#include "freedreno_dev_info.h"\n'
     '#include "util/u_debug.h"\n'
     '\n'
     'DEBUG_GET_ONCE_BOOL_OPTION(tu_z_bgra_swap, "TU_Z_BGRA_SWAP", true)\n',
     1),
    (TABLE,
     '   if (tile_mode && !is_mutable)\n'
     '      return WZYX;\n',
     '   if ((format == PIPE_FORMAT_B8G8R8A8_UNORM ||\n'
     '        format == PIPE_FORMAT_B8G8R8A8_SRGB) &&\n'
     '       debug_get_option_tu_z_bgra_swap())\n'
     '      return formats[format].swap;\n'
     '\n'
     '   if (tile_mode && !is_mutable)\n'
     '      return WZYX;\n',
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
    print(f"{NAME}: applied (TU_Z_BGRA_SWAP default on)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
