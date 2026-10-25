#!/usr/bin/env python3
"""Preserve LRZ state across draws when fragment shader has side effects.

Upstream Turnip permanently invalidates LRZ for the remaining render pass when
a fragment shader writes depth or contains side-effects while depth direction
is still TU_LRZ_UNKNOWN under GPU direction tracking. This drops early depth
testing for all subsequent draws in the pass.

Instead of permanent invalidation, this patch sets temporary_disable_lrz for
the current draw only, allowing subsequent draws to use LRZ once direction is
established.

Env TU_LRZ_PRESERVE_FS_SIDEEFFECTS (default true):
  true   temporarily disable LRZ for the current draw only
  false  permanently invalidate LRZ for the render pass (upstream behavior)

Target: Adreno 7xx / a710 LRZ fast-clear and depth culling.
Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = "61-tu-lrz-fs-sideeffects-no-invalidate.py"
MARKER = "TU_LRZ_PRESERVE_FS_SIDEEFFECTS"
LRZ_CC = "src/freedreno/vulkan/tu_lrz.cc"

EDITS = [
    (LRZ_CC,
     '#include "tu_image.h"\n',
     '#include "tu_image.h"\n'
     '#include "util/u_debug.h"\n'
     '\n'
     'DEBUG_GET_ONCE_BOOL_OPTION(tu_lrz_preserve_fs_sideeffects, "TU_LRZ_PRESERVE_FS_SIDEEFFECTS", false)\n',
     1),
    (LRZ_CC,
     '   if (disable_lrz_due_to_fs) {\n'
     '      if (cmd->state.lrz.prev_direction != TU_LRZ_UNKNOWN || !cmd->state.lrz.gpu_dir_tracking) {\n'
     '         perf_debug(cmd->device, "Skipping LRZ due to FS");\n'
     '         temporary_disable_lrz = true;\n'
     '      } else {\n'
     '         tu_lrz_invalidate(cmd, "FS writes depth or has side-effects (TODO: fix for gpu-direction-tracking case)");\n'
     '      }\n'
     '   }\n',
     '   if (disable_lrz_due_to_fs) {\n'
     '      if (debug_get_option_tu_lrz_preserve_fs_sideeffects() ||\n'
     '          cmd->state.lrz.prev_direction != TU_LRZ_UNKNOWN || !cmd->state.lrz.gpu_dir_tracking) {\n'
     '         perf_debug(cmd->device, "Skipping LRZ due to FS");\n'
     '         temporary_disable_lrz = true;\n'
     '      } else {\n'
     '         tu_lrz_invalidate(cmd, "FS writes depth or has side-effects (TODO: fix for gpu-direction-tracking case)");\n'
     '      }\n'
     '   }\n',
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
    print(f"{NAME}: applied (TU_LRZ_PRESERVE_FS_SIDEEFFECTS, default true)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
