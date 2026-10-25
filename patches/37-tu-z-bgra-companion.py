#!/usr/bin/env python3
"""Turnip-Z port: BGRA8 companion changes that go with 33-tu-z-bgra-swap.py.

33 makes B8G8R8A8 views sample with their real swap (WXYZ) even when the
image is tiled. Turnip-Z pairs that with changes on every write path so the
tiled memory of a B8G8R8A8 image really holds B,G,R,A (found by reading the
fork's uses of its BGRA flag):

  * fragment shader: R and B of the outputs written to B8G8R8A8 colour
    attachments are swapped (new 8-bit mask in tu_shader_key, filled from the
    render pass formats, applied by a NIR pass after ir3_nir_lower_io)
  * colour write mask: R and B bits swapped for B8G8R8A8 attachments
  * clears: R and B of the clear colour swapped in r2d_clear_value,
    pack_blit_event_clear_value and tu_clear_sysmem_attachments
  * copies: copy_format() copies B8G8R8A8 as R8G8B8A8 (raw bytes)
  * vkCmdBlitImage: the source swap is flipped when the destination is a
    tiled B8G8R8A8 image, so the 2D/3D engine stores B,G,R,A
  * vkCmdClearColorImage: the destination swap of a B8G8R8A8 image goes back
    to WZYX so the swapped clear colour lands as B,G,R,A on linear images too

Without these, 33 alone samples tiled BGRA8 memory that was written in RGBA
order, which shows up as blue skin / red-yellow screens.

Needs 33-tu-z-bgra-swap.py. Env TU_Z_BGRA_SWAP (default true) switches both.

Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = "37-tu-z-bgra-companion.py"
MARKER = "z_bgra_mask"
SHADER_H = "src/freedreno/vulkan/tu_shader.h"
SHADER_CC = "src/freedreno/vulkan/tu_shader.cc"
PIPELINE = "src/freedreno/vulkan/tu_pipeline.cc"
CLEAR = "src/freedreno/vulkan/tu_clear_blit.cc"

PIPELINE_HELPERS = '''
DEBUG_GET_ONCE_BOOL_OPTION(tu_z_bgra_swap, "TU_Z_BGRA_SWAP", true)

static inline bool
tu_z_is_bgra8(VkFormat format)
{
   return format == VK_FORMAT_B8G8R8A8_UNORM ||
          format == VK_FORMAT_B8G8R8A8_SRGB;
}

static inline uint32_t
tu_z_write_mask(VkFormat format, uint32_t mask)
{
   if (!tu_z_is_bgra8(format) || !debug_get_option_tu_z_bgra_swap())
      return mask;
   return (mask & 0xa) | ((mask & 0x1) << 2) | ((mask >> 2) & 0x1);
}
'''

SHADER_PASS = '''static bool
tu_z_bgra_swap_output(nir_builder *b, nir_intrinsic_instr *intr, void *data)
{
   const struct tu_shader_key *key = (const struct tu_shader_key *)data;

   if (intr->intrinsic != nir_intrinsic_store_output)
      return false;

   nir_io_semantics sem = nir_intrinsic_io_semantics(intr);
   if (sem.location < FRAG_RESULT_DATA0 || sem.location > FRAG_RESULT_DATA7)
      return false;

   unsigned rt = sem.location - FRAG_RESULT_DATA0;
   if (!(key->z_bgra_mask & (1u << rt)))
      return false;

   unsigned comp = nir_intrinsic_component(intr);
   unsigned wrmask = nir_intrinsic_write_mask(intr);
   nir_def *val = intr->src[0].ssa;
   unsigned num_comp = intr->num_components;

   b->cursor = nir_before_instr(&intr->instr);

   nir_def *chans[NIR_MAX_VEC_COMPONENTS];
   for (unsigned i = 0; i < num_comp; i++) {
      unsigned c = comp + i;
      unsigned src_c = (c == 0) ? (2 - comp) : ((c == 2) ? (0 - comp) : i);
      if (src_c < num_comp)
         chans[i] = nir_channel(b, val, src_c);
      else
         chans[i] = nir_channel(b, val, i);
   }
   nir_def *swizzled = nir_vec(b, chans, num_comp);
   nir_src_rewrite(&intr->src[0], swizzled);

   if (comp == 0 && (wrmask & 0x5)) {
      unsigned new_mask = (wrmask & ~0x5) | ((wrmask & 0x1) << 2) | ((wrmask & 0x4) >> 2);
      nir_intrinsic_set_write_mask(intr, new_mask);
   }

   return true;
}


'''

CLEAR_HELPERS = '''#include "util/u_debug.h"

DEBUG_GET_ONCE_BOOL_OPTION(tu_z_bgra_swap, "TU_Z_BGRA_SWAP", true)

static inline bool
tu_z_bgra_pipe(enum pipe_format format)
{
   return (format == PIPE_FORMAT_B8G8R8A8_UNORM ||
           format == PIPE_FORMAT_B8G8R8A8_SRGB) &&
          debug_get_option_tu_z_bgra_swap();
}

static inline const VkClearValue *
tu_z_bgra_clear_value(enum pipe_format format, const VkClearValue *val,
                      VkClearValue *tmp)
{
   if (!tu_z_bgra_pipe(format))
      return val;
   *tmp = *val;
   tmp->color.uint32[0] = val->color.uint32[2];
   tmp->color.uint32[2] = val->color.uint32[0];
   return tmp;
}

template <chip CHIP>
static void
tu_z_flip_src_swap(struct fdl6_view *v)
{
   enum a3xx_color_swap s = (enum a3xx_color_swap)
      pkt_field_get(A6XX_TPL1_A2D_SRC_TEXTURE_INFO_COLOR_SWAP,
                    v->TPL1_A2D_SRC_TEXTURE_INFO);
   if (s != WZYX && s != WXYZ)
      return;
   s = s == WZYX ? WXYZ : WZYX;
   v->TPL1_A2D_SRC_TEXTURE_INFO =
      pkt_field_set(A6XX_TPL1_A2D_SRC_TEXTURE_INFO_COLOR_SWAP,
                    v->TPL1_A2D_SRC_TEXTURE_INFO, s);
   tu_desc_set_swap<CHIP>(v->descriptor, s);
}
'''

EDITS = [
    (SHADER_H,
     '   bool emulate_alpha_to_coverage : 1;\n'
     '   uint32_t padding : 23;\n',
     '   bool emulate_alpha_to_coverage : 1;\n'
     '   uint32_t z_bgra_mask : 8;\n'
     '   uint32_t padding : 15;\n',
     1),
    (SHADER_CC,
     'static bool\n'
     'lower_alpha_to_coverage(nir_shader *shader)\n',
     SHADER_PASS +
     'static bool\n'
     'lower_alpha_to_coverage(nir_shader *shader)\n',
     1),
    (SHADER_CC,
     '   if (key->emulate_alpha_to_coverage)\n'
     '      lower_alpha_to_coverage(nir);\n',
     '   if (key->emulate_alpha_to_coverage)\n'
     '      lower_alpha_to_coverage(nir);\n'
     '\n'
     '   if (nir->info.stage == MESA_SHADER_FRAGMENT && key->z_bgra_mask)\n'
     '      NIR_PASS(_, nir, nir_shader_intrinsics_pass, tu_z_bgra_swap_output,\n'
     '               nir_metadata_control_flow, (void *)key);\n',
     1),
    (PIPELINE,
     '#include "tu_knl.h"\n',
     '#include "tu_knl.h"\n' + PIPELINE_HELPERS,
     1),
    (PIPELINE,
     '      keys[MESA_SHADER_FRAGMENT].custom_resolve =\n'
     '         builder->graphics_state.rp->custom_resolve;\n',
     '      keys[MESA_SHADER_FRAGMENT].custom_resolve =\n'
     '         builder->graphics_state.rp->custom_resolve;\n'
     '\n'
     '      if (debug_get_option_tu_z_bgra_swap() &&\n'
     '          builder->graphics_state.rp->color_attachment_count !=\n'
     '             MESA_VK_COLOR_ATTACHMENT_COUNT_UNKNOWN) {\n'
     '         for (unsigned i = 0;\n'
     '              i < MIN2(builder->graphics_state.rp->color_attachment_count, 8u);\n'
     '              i++) {\n'
     '            if (tu_z_is_bgra8(builder->graphics_state.rp->color_attachment_formats[i]))\n'
     '               keys[MESA_SHADER_FRAGMENT].z_bgra_mask |= 1u << i;\n'
     '         }\n'
     '      }\n',
     1),
    (PIPELINE,
     '.component_enable = att->write_mask),\n',
     '.component_enable = tu_z_write_mask(att_format, att->write_mask)),\n',
     1),
    (PIPELINE,
     '.component_write_mask = att->write_mask));\n',
     '.component_write_mask = tu_z_write_mask(att_format, att->write_mask)));\n',
     1),
    (CLEAR,
     '#include "tu_tracepoints.h"\n',
     '#include "tu_tracepoints.h"\n' + CLEAR_HELPERS,
     1),
    (CLEAR,
     'r2d_clear_value(struct tu_cmd_buffer *cmd,\n'
     '                struct tu_cs *cs,\n'
     '                enum pipe_format format,\n'
     '                const VkClearValue *val)\n'
     '{\n',
     'r2d_clear_value(struct tu_cmd_buffer *cmd,\n'
     '                struct tu_cs *cs,\n'
     '                enum pipe_format format,\n'
     '                const VkClearValue *val)\n'
     '{\n'
     '   VkClearValue z_tmp;\n'
     '   val = tu_z_bgra_clear_value(format, val, &z_tmp);\n',
     1),
    (CLEAR,
     'pack_blit_event_clear_value(const VkClearValue *val, enum pipe_format format, uint32_t clear_value[4])\n'
     '{\n',
     'pack_blit_event_clear_value(const VkClearValue *val, enum pipe_format format, uint32_t clear_value[4])\n'
     '{\n'
     '   VkClearValue z_tmp;\n'
     '   val = tu_z_bgra_clear_value(format, val, &z_tmp);\n',
     1),
    (CLEAR,
     '         memcpy(clear_value[remapped], &attachments[i].clearValue, 4 * sizeof(uint32_t));\n',
     '         memcpy(clear_value[remapped], &attachments[i].clearValue, 4 * sizeof(uint32_t));\n'
     '         if (tu_z_bgra_pipe(vk_format_to_pipe_format(cmd->state.pass->attachments[a].format))) {\n'
     '            uint32_t z_t = clear_value[remapped][0];\n'
     '            clear_value[remapped][0] = clear_value[remapped][2];\n'
     '            clear_value[remapped][2] = z_t;\n'
     '         }\n',
     1),
    (CLEAR,
     '   if (vk_format == VK_FORMAT_R64_SINT || vk_format == VK_FORMAT_R64_UINT) {\n'
     '      return PIPE_FORMAT_R32G32_UINT;\n'
     '   }\n',
     '   if (vk_format == VK_FORMAT_R64_SINT || vk_format == VK_FORMAT_R64_UINT) {\n'
     '      return PIPE_FORMAT_R32G32_UINT;\n'
     '   }\n'
     '\n'
     '   if (tu_z_bgra_pipe(format))\n'
     '      return format == PIPE_FORMAT_B8G8R8A8_SRGB ? PIPE_FORMAT_R8G8B8A8_SRGB\n'
     '                                                 : PIPE_FORMAT_R8G8B8A8_UNORM;\n',
     1),
    (CLEAR,
     '      tu_image_view_copy_blit<CHIP>(&src, src_image, src_format,\n'
     '                                    &info->srcSubresource, 0, true);\n'
     '      ops->src(cmd, cs, &src, 0, filter, dst_format);\n'
     '   } else {\n'
     '      tu_image_view_blit<CHIP>(&src, src_image, &info->srcSubresource, info->srcOffsets[0].z);\n'
     '   }\n',
     '      tu_image_view_copy_blit<CHIP>(&src, src_image, src_format,\n'
     '                                    &info->srcSubresource, 0, true);\n'
     '      if (tu_z_bgra_pipe(dst_format) && dst_image->layout[0].tile_mode)\n'
     '         tu_z_flip_src_swap<CHIP>(&src);\n'
     '      ops->src(cmd, cs, &src, 0, filter, dst_format);\n'
     '   } else {\n'
     '      tu_image_view_blit<CHIP>(&src, src_image, &info->srcSubresource, info->srcOffsets[0].z);\n'
     '      if (tu_z_bgra_pipe(dst_format) && dst_image->layout[0].tile_mode)\n'
     '         tu_z_flip_src_swap<CHIP>(&src);\n'
     '   }\n',
     1),
    (CLEAR,
     '      tu_image_view_copy_blit<CHIP>(&dst, image, format, &subresource, 0, false);\n'
     '\n'
     '      for (uint32_t i = 0; i < layer_count; i++) {\n'
     '         ops->dst(cs, &dst, i, format);\n',
     '      tu_image_view_copy_blit<CHIP>(&dst, image, format, &subresource, 0, false);\n'
     '      if (tu_z_bgra_pipe(format))\n'
     '         dst.RB_A2D_DEST_BUFFER_INFO =\n'
     '            pkt_field_set(A6XX_RB_A2D_DEST_BUFFER_INFO_COLOR_SWAP,\n'
     '                          dst.RB_A2D_DEST_BUFFER_INFO, WZYX);\n'
     '\n'
     '      for (uint32_t i = 0; i < layer_count; i++) {\n'
     '         ops->dst(cs, &dst, i, format);\n',
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
            print(f"{NAME}:   anchor starts: {old.splitlines()[0]!r}")
            return 0
        files[path] = files[path].replace(old, new)
    for path, s in files.items():
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(s)
    print(f"{NAME}: applied (TU_Z_BGRA_SWAP default on)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
