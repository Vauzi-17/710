#!/usr/bin/env python3
"""Allow configurable relaxation of single_prim_mode for raster order attachment access.

When raster_order_attachment_access is enabled, upstream Turnip forces
gmem_prim_mode = FLUSH_PER_OVERLAP in tu_pipeline_builder_parse_rasterization_order.
On single-CCU architectures like Adreno 710 and Adreno 810 (present in Snapdragon
6 Gen 4, 7s Gen 3, and 7s Gen 4), cross-CCU incoherency does not exist in GMEM mode,
and primitive overlap flushing adds unnecessary pipeline stalls.

This patch makes single_prim_mode configurable via TU_RAST_ORDER_PRIM_MODE:
  0 = NO_FLUSH (relaxed fast-path, ideal for single-CCU a710 / a810)
  1 = FLUSH_PER_OVERLAP (upstream default)

Env TU_RAST_ORDER_PRIM_MODE (default 0):
  0      NO_FLUSH
  1      FLUSH_PER_OVERLAP

Target: Adreno 7xx / 8xx (a710, a810 [Snapdragon 6 Gen 4, 7s Gen 3, 7s Gen 4]).
Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = "72-tu-rast-order-prim-mode.py"
MARKER = "TU_RAST_ORDER_PRIM_MODE"
PIPELINE_CC = "src/freedreno/vulkan/tu_pipeline.cc"

EDITS = [
    (PIPELINE_CC,
     'template <chip CHIP>\n'
     'static void\n'
     'tu_pipeline_builder_parse_rasterization_order(\n'
     '   struct tu_pipeline_builder *builder, struct tu_pipeline *pipeline)\n',
     '#include "util/u_debug.h"\n'
     '\n'
     'DEBUG_GET_ONCE_NUM_OPTION(tu_rast_order_prim_mode, "TU_RAST_ORDER_PRIM_MODE", 0)\n'
     '\n'
     'template <chip CHIP>\n'
     'static void\n'
     'tu_pipeline_builder_parse_rasterization_order(\n'
     '   struct tu_pipeline_builder *builder, struct tu_pipeline *pipeline)\n',
     1),
    (PIPELINE_CC,
     '   if (raster_order_attachment_access) {\n'
     '      /* VK_EXT_rasterization_order_attachment_access:\n'
     '       *\n'
     '       * This extension allow access to framebuffer attachments when used as\n'
     '       * both input and color attachments from one fragment to the next,\n'
     '       * in rasterization order, without explicit synchronization.\n'
     '       */\n'
     '      gmem_prim_mode = FLUSH_PER_OVERLAP;\n'
     '   }\n',
     '   if (raster_order_attachment_access) {\n'
     '      /* VK_EXT_rasterization_order_attachment_access:\n'
     '       *\n'
     '       * This extension allow access to framebuffer attachments when used as\n'
     '       * both input and color attachments from one fragment to the next,\n'
     '       * in rasterization order, without explicit synchronization.\n'
     '       */\n'
     '      gmem_prim_mode = debug_get_option_tu_rast_order_prim_mode() == 1\n'
     '                          ? FLUSH_PER_OVERLAP\n'
     '                          : NO_FLUSH;\n'
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
    print(f"{NAME}: applied (TU_RAST_ORDER_PRIM_MODE, default 0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
