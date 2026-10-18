#!/usr/bin/env python3
"""Turnip-Z port: LRZ rescue on in-render-pass depth clears.

Upstream disables LRZ for the rest of the render pass whenever
vkCmdClearAttachments touches depth. When the clear covers the whole render
area of the current depth attachment (single layer, single rect), this patch
keeps LRZ valid instead: it resets the LRZ state to the new clear value and
emits an LRZ fast clear right there, like a LOAD_OP_CLEAR at pass start.
Unlike Turnip-Z it also clears the LRZ buffer, so stale LRZ data cannot cull
geometry drawn after the clear.

Only active with TU_DEBUG=sysmem, GPU LRZ direction tracking, and an LRZ
fast-clear buffer that covers the whole image; otherwise upstream behavior.

Env TU_Z_LRZ_RESCUE (default true) turns it on/off.

Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = "31-tu-z-lrz-rescue.py"
MARKER = "TU_Z_LRZ_RESCUE"
LRZ_CC = "src/freedreno/vulkan/tu_lrz.cc"
LRZ_H = "src/freedreno/vulkan/tu_lrz.h"
CLEAR = "src/freedreno/vulkan/tu_clear_blit.cc"

RESCUE_FN = r'''
template <chip CHIP>
bool
tu_lrz_z_rescue_clear(struct tu_cmd_buffer *cmd,
                      const VkClearAttachment *att,
                      uint32_t rect_count,
                      const VkClearRect *rects)
{
   struct tu_lrz_state *lrz = &cmd->state.lrz;
   const struct tu_image_view *view = lrz->image_view;

   if (!debug_get_option_tu_z_lrz_rescue() || !TU_DEBUG(SYSMEM) ||
       TU_DEBUG(NOLRZ) || TU_DEBUG(NOLRZFC))
      return false;

   if (!cmd->state.pass || !cmd->state.subpass || !view ||
       !lrz->valid || !lrz->gpu_dir_tracking)
      return false;

   if (cmd->state.suspending || cmd->state.resuming ||
       cmd->state.per_layer_render_area || cmd->state.pass->num_views > 1)
      return false;

   uint32_t a = cmd->state.subpass->depth_stencil_attachment.attachment;
   if (a == VK_ATTACHMENT_UNUSED || cmd->state.attachments[a] != view)
      return false;

   if (view->vk.layer_count != 1 ||
       !view->image->lrz_layout.lrz_fc_size ||
       !fdl6_lrz_fc_fully_covered(&view->image->lrz_layout))
      return false;

   float depth = att->clearValue.depthStencil.depth;
   if (!tu_lrzfc_depth_supported<CHIP>(depth))
      return false;

   const VkRect2D *ra = &cmd->state.render_areas[0];
   if (ra->offset.x != 0 || ra->offset.y != 0 ||
       ra->extent.width != view->vk.extent.width ||
       ra->extent.height != view->vk.extent.height)
      return false;

   if (rect_count != 1 || rects[0].baseArrayLayer != 0 ||
       rects[0].layerCount != 1 ||
       rects[0].rect.offset.x != 0 || rects[0].rect.offset.y != 0 ||
       rects[0].rect.extent.width < ra->extent.width ||
       rects[0].rect.extent.height < ra->extent.height)
      return false;

   struct tu_cs *cs = &cmd->draw_cs;

   lrz->depth_clear_value = att->clearValue;
   lrz->fast_clear = true;
   lrz->reuse_previous_state = false;
   lrz->prev_direction = TU_LRZ_UNKNOWN;

   tu6_write_lrz_cntl<CHIP>(cmd, cs, {
      .enable = true,
      .fc_enable = true,
      .disable_on_wrong_dir = true,
   });
   if (CHIP >= A7XX)
      tu_cs_emit_regs(cs, GRAS_LRZ_DEPTH_CLEAR(CHIP, depth));
   tu_emit_event_write<CHIP>(cmd, cs, FD_LRZ_CLEAR);

   cmd->state.dirty |= TU_CMD_DIRTY_LRZ;
   return true;
}
TU_GENX(tu_lrz_z_rescue_clear);
'''

EDITS = [
    (LRZ_CC,
     '#include "tu_tracepoints.h"\n',
     '#include "tu_tracepoints.h"\n'
     '#include "util/u_debug.h"\n'
     '\n'
     'DEBUG_GET_ONCE_BOOL_OPTION(tu_z_lrz_rescue, "TU_Z_LRZ_RESCUE", true)\n',
     1),
    (LRZ_CC,
     'TU_GENX(tu_lrz_disable_during_renderpass);\n',
     'TU_GENX(tu_lrz_disable_during_renderpass);\n' + RESCUE_FN,
     1),
    (LRZ_H,
     'tu_lrz_disable_during_renderpass(struct tu_cmd_buffer *cmd,\n'
     '                                 const char *reason);\n',
     'tu_lrz_disable_during_renderpass(struct tu_cmd_buffer *cmd,\n'
     '                                 const char *reason);\n'
     '\n'
     'template <chip CHIP>\n'
     'bool\n'
     'tu_lrz_z_rescue_clear(struct tu_cmd_buffer *cmd,\n'
     '                      const VkClearAttachment *att,\n'
     '                      uint32_t rect_count,\n'
     '                      const VkClearRect *rects);\n',
     1),
    (CLEAR,
     '      tu_lrz_disable_during_renderpass<CHIP>(cmd, "CmdClearAttachments");\n',
     '      if (attachmentCount == 1 &&\n'
     '          tu_lrz_z_rescue_clear<CHIP>(cmd, &pAttachments[j], rectCount, pRects))\n'
     '         continue;\n'
     '\n'
     '      tu_lrz_disable_during_renderpass<CHIP>(cmd, "CmdClearAttachments");\n',
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
    print(f"{NAME}: applied (TU_Z_LRZ_RESCUE default on, needs TU_DEBUG=sysmem)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
