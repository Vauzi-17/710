#!/usr/bin/env python3
"""Bypass redundant COLOR_ATTACHMENT_OUTPUT -> FRAGMENT_SHADER barriers.

In subpasses where raster_order_attachment_access is enabled, fragment order is
guaranteed by hardware rasterization order (NO_FLUSH or FLUSH_PER_OVERLAP).
Upstream Turnip emits pipeline barriers and subpass fences for
COLOR_ATTACHMENT_OUTPUT -> FRAGMENT_SHADER with by_region intra-subpass barriers,
causing unnecessary stalls and cache flushes between draws.

This patch bypasses these redundant barriers when raster order attachment access
is active on the current subpass.

Env TU_SKIP_RAST_ORDER_BARRIERS (default true):
  true   bypass redundant intra-subpass color-to-FS barriers
  false  emit barriers normally (upstream behavior)

Target: Adreno 7xx / 8xx (a710, a810 [Snapdragon 6 Gen 4, 7s Gen 3, 7s Gen 4]).
Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = "70-tu-skip-rast-order-barriers.py"
MARKER = "TU_SKIP_RAST_ORDER_BARRIERS"
CMD_BUFFER = "src/freedreno/vulkan/tu_cmd_buffer.cc"

EDITS = [
    (CMD_BUFFER,
     'void\n'
     'tu_barrier(struct tu_cmd_buffer *cmd,\n'
     '           uint32_t dep_count,\n'
     '           const VkDependencyInfo *dep_infos,\n'
     '           bool no_sync)\n',
     '#include "util/u_debug.h"\n'
     '\n'
     'DEBUG_GET_ONCE_BOOL_OPTION(tu_skip_rast_order_barriers, "TU_SKIP_RAST_ORDER_BARRIERS", true)\n'
     '\n'
     'void\n'
     'tu_barrier(struct tu_cmd_buffer *cmd,\n'
     '           uint32_t dep_count,\n'
     '           const VkDependencyInfo *dep_infos,\n'
     '           bool no_sync)\n',
     1),
    (CMD_BUFFER,
     '      if ((srcStage & ~framebuffer_space_stages) ||\n'
     '          (dstStage & ~framebuffer_space_stages)) {\n'
     '         cmd->state.rp.disable_gmem = true;\n'
     '         cmd->state.rp.force_render_mode_reason = "Non-framebuffer-space barrier";\n'
     '         by_region = false;\n'
     '      } else {\n'
     '         by_region = true;\n'
     '      }\n'
     '   }\n',
     '      if ((srcStage & ~framebuffer_space_stages) ||\n'
     '          (dstStage & ~framebuffer_space_stages)) {\n'
     '         cmd->state.rp.disable_gmem = true;\n'
     '         cmd->state.rp.force_render_mode_reason = "Non-framebuffer-space barrier";\n'
     '         by_region = false;\n'
     '      } else {\n'
     '         by_region = true;\n'
     '      }\n'
     '   }\n'
     '\n'
     '   if (debug_get_option_tu_skip_rast_order_barriers() && by_region &&\n'
     '       ((cmd->state.subpass && cmd->state.subpass->raster_order_attachment_access) ||\n'
     '        cmd->state.raster_order_attachment_access) &&\n'
     '       srcStage == VK_PIPELINE_STAGE_2_COLOR_ATTACHMENT_OUTPUT_BIT &&\n'
     '       dstStage == VK_PIPELINE_STAGE_2_FRAGMENT_SHADER_BIT) {\n'
     '      return;\n'
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
    print(f"{NAME}: applied (TU_SKIP_RAST_ORDER_BARRIERS, default true)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
