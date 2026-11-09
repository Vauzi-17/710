#!/usr/bin/env python3
"""Prevent sticky LRZ disable on stencil fragment kill.

Upstream Turnip calls tu_lrz_disable_write_for_rp() when
frag_may_be_killed_by_stencil is true, permanently disabling LRZ writes for the
remainder of the entire renderpass.

This patch changes the behavior so that gras_lrz_cntl.lrz_write is set to false
for the current draw call only, allowing subsequent draw calls in the renderpass
to continue using and updating LRZ.

Env TU_LRZ_NO_STICKY_STENCIL_DISABLE (default true):
  true   disable LRZ writes for current draw call only
  false  permanently disable LRZ writes for renderpass (upstream behavior)

Target: Adreno 7xx / 8xx (a710, a810 [Snapdragon 6 Gen 4, 7s Gen 3, 7s Gen 4]).
Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = "71-tu-lrz-no-sticky-stencil-disable.py"
MARKER = "TU_LRZ_NO_STICKY_STENCIL_DISABLE"
LRZ_CC = "src/freedreno/vulkan/tu_lrz.cc"

EDITS = [
    (LRZ_CC,
     'template <chip CHIP>\n'
     'static struct __GRAS_LRZ_CNTL\n'
     'tu6_calculate_lrz_state(struct tu_cmd_buffer *cmd,\n'
     '                        const uint32_t a)\n',
     '#include "util/u_debug.h"\n'
     '\n'
     'DEBUG_GET_ONCE_BOOL_OPTION(tu_lrz_no_sticky_stencil_disable, "TU_LRZ_NO_STICKY_STENCIL_DISABLE", true)\n'
     '\n'
     'template <chip CHIP>\n'
     'static struct __GRAS_LRZ_CNTL\n'
     'tu6_calculate_lrz_state(struct tu_cmd_buffer *cmd,\n'
     '                        const uint32_t a)\n',
     1),
    (LRZ_CC,
     '      /* Stencil test happens after LRZ is written, so if stencil could kill\n'
     '       * the fragment - we cannot write LRZ.\n'
     '       */\n'
     '      if (frag_may_be_killed_by_stencil) {\n'
     '         tu_lrz_disable_write_for_rp(cmd, "Stencil may kill fragments");\n'
     '      }\n',
     '      /* Stencil test happens after LRZ is written, so if stencil could kill\n'
     '       * the fragment - we cannot write LRZ.\n'
     '       */\n'
     '      if (frag_may_be_killed_by_stencil) {\n'
     '         if (debug_get_option_tu_lrz_no_sticky_stencil_disable()) {\n'
     '            gras_lrz_cntl.lrz_write = false;\n'
     '         } else {\n'
     '            tu_lrz_disable_write_for_rp(cmd, "Stencil may kill fragments");\n'
     '         }\n'
     '      }\n',
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
    print(f"{NAME}: applied (TU_LRZ_NO_STICKY_STENCIL_DISABLE, default true)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
