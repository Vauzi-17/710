#!/usr/bin/env python3
"""Turnip-Z port: BGRA8 companion changes with multi-mode color swap support.

Includes 3 selectable modes via TU_Z_BGRA_MODE:
  0 = sw default (compile-time z_bgra_mask in tu_shader_key, per-channel scalar stores, proven Switch baseline)
  1 = turnipz3 port (dynamic sysval load_rt_swap_mask_ir3 via IR3_DP_FS, fixes Unreal Engine games)
  2 = perbaikan / optimized (compile-time z_bgra_mask, safe in-place vec4 SSA swizzle, zero FPS regression)

Pairs with 33-tu-z-bgra-swap.py. Env TU_Z_BGRA_SWAP (default true) enables BGRA handling.
Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = "37-tu-z-bgra-companion.py"
MARKER = "z_bgra_mask"
INTRINSICS_PY = "src/compiler/nir/nir_intrinsics.py"
DIVERGENCE_C = "src/compiler/nir/nir_divergence_analysis.c"
IR3_SHADER_H = "src/freedreno/ir3/ir3_shader.h"
IR3_NIR_C = "src/freedreno/ir3/ir3_nir.c"
IR3_COMPILER_C = "src/freedreno/ir3/ir3_compiler_nir.c"
TU_CMD = "src/freedreno/vulkan/tu_cmd_buffer.cc"
SHADER_H = "src/freedreno/vulkan/tu_shader.h"
SHADER_CC = "src/freedreno/vulkan/tu_shader.cc"
PIPELINE = "src/freedreno/vulkan/tu_pipeline.cc"
CLEAR = "src/freedreno/vulkan/tu_clear_blit.cc"

CMD_HELPERS = '''
DEBUG_GET_ONCE_BOOL_OPTION(tu_z_bgra_swap, "TU_Z_BGRA_SWAP", true)
DEBUG_GET_ONCE_NUM_OPTION(tu_z_bgra_mode, "TU_Z_BGRA_MODE", 0)

static inline bool
tu_z_cmd_is_bgra8(VkFormat format)
{
   return format == VK_FORMAT_B8G8R8A8_UNORM ||
          format == VK_FORMAT_B8G8R8A8_SRGB;
}

static inline uint32_t
tu_z_get_rt_swap_mask(struct tu_cmd_buffer *cmd)
{
   if (!debug_get_option_tu_z_bgra_swap() || debug_get_option_tu_z_bgra_mode() != 1)
      return 0;

   uint32_t mask = 0;
   if (cmd->state.subpass && cmd->state.pass) {
      for (unsigned i = 0; i < cmd->state.subpass->color_count; i++) {
         uint32_t a = cmd->state.subpass->color_attachments[i].attachment;
         if (a != VK_ATTACHMENT_UNUSED &&
             tu_z_cmd_is_bgra8(cmd->state.pass->attachments[a].format))
            mask |= (1u << i);
      }
   }
   return mask;
}
'''

PIPELINE_HELPERS = '''
DEBUG_GET_ONCE_BOOL_OPTION(tu_z_bgra_swap, "TU_Z_BGRA_SWAP", true)
DEBUG_GET_ONCE_NUM_OPTION(tu_z_bgra_mode, "TU_Z_BGRA_MODE", 0)

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

SHADER_PASS = '''#include "util/u_debug.h"

DEBUG_GET_ONCE_BOOL_OPTION(tu_z_bgra_swap, "TU_Z_BGRA_SWAP", true)
DEBUG_GET_ONCE_NUM_OPTION(tu_z_bgra_mode, "TU_Z_BGRA_MODE", 0)

static bool
tu_z_bgra_swap_output(nir_builder *b, nir_intrinsic_instr *intr, void *data)
{
   const struct tu_shader_key *key = (const struct tu_shader_key *)data;

   if (intr->intrinsic != nir_intrinsic_store_output)
      return false;

   nir_io_semantics sem = nir_intrinsic_io_semantics(intr);
   if (sem.location < FRAG_RESULT_DATA0 || sem.location > FRAG_RESULT_DATA7)
      return false;

   unsigned rt = sem.location - FRAG_RESULT_DATA0;
   int64_t mode = debug_get_option_tu_z_bgra_mode();

   /* In Mode 0 and Mode 2: compile-time key check */
   if (mode != 1 && !(key->z_bgra_mask & (1u << rt)))
      return false;

   unsigned comp = nir_intrinsic_component(intr);
   unsigned wrmask = nir_intrinsic_write_mask(intr);
   nir_def *val = intr->src[0].ssa;

   b->cursor = nir_before_instr(&intr->instr);

   /* Mode 1: TurnipZ 0.3.0 direct port (dynamic sysval load_rt_swap_mask_ir3) */
   if (mode == 1) {
      nir_def *mask = nir_load_rt_swap_mask_ir3(b);
      nir_def *bit = nir_iand_imm(b, nir_ushr_imm(b, mask, rt), 1);
      nir_def *cond = nir_ine_imm(b, bit, 0);

      if (comp == 0 && intr->num_components == 4 && wrmask == 0xf) {
         nir_def *r = nir_channel(b, val, 0);
         nir_def *g = nir_channel(b, val, 1);
         nir_def *b_chan = nir_channel(b, val, 2);
         nir_def *a = nir_channel(b, val, 3);
         nir_def *chans[4] = {
            nir_bcsel(b, cond, b_chan, r),
            g,
            nir_bcsel(b, cond, r, b_chan),
            a,
         };
         nir_src_rewrite(&intr->src[0], nir_vec(b, chans, 4));
         return true;
      }

      u_foreach_bit (i, wrmask) {
         unsigned c = comp + i;
         nir_def *chan = nir_channel(b, val, i);
         if (c == 0 || c == 2) {
            unsigned other_c = (c == 0 ? 2 : 0);
            nir_def *other = (other_c < intr->num_components) ?
                             nir_channel(b, val, other_c) : chan;
            chan = nir_bcsel(b, cond, other, chan);
         }
         nir_intrinsic_instr *st =
            nir_instr_as_intrinsic(nir_instr_clone(b->shader, &intr->instr));
         st->src[0] = nir_src_for_ssa(chan);
         st->num_components = 1;
         nir_intrinsic_set_component(st, c);
         nir_intrinsic_set_write_mask(st, 0x1);
         nir_builder_instr_insert(b, &st->instr);
      }
      nir_instr_remove(&intr->instr);
      return true;
   }

   /* Mode 2: Perbaikan / optimized in-place vector swizzle (zero FPS regression) */
   if (mode == 2 && comp == 0 && intr->num_components == 4 && wrmask == 0xf) {
      nir_def *chans[4] = {
         nir_channel(b, val, 2),
         nir_channel(b, val, 1),
         nir_channel(b, val, 0),
         nir_channel(b, val, 3),
      };
      nir_src_rewrite(&intr->src[0], nir_vec(b, chans, 4));
      return true;
   }

   /* Mode 0: sw default baseline (compile-time key, per-channel scalar split) */
   u_foreach_bit (i, wrmask) {
      unsigned c = comp + i;
      unsigned t = c == 0 ? 2 : (c == 2 ? 0 : c);
      nir_def *chan = nir_channel(b, val, i);
      nir_intrinsic_instr *st =
         nir_instr_as_intrinsic(nir_instr_clone(b->shader, &intr->instr));
      st->src[0] = nir_src_for_ssa(chan);
      st->num_components = 1;
      nir_intrinsic_set_component(st, t);
      nir_intrinsic_set_write_mask(st, 0x1);
      nir_builder_instr_insert(b, &st->instr);
   }

   nir_instr_remove(&intr->instr);
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
    # 1. NIR intrinsics definition for dynamic rt_swap_mask_ir3
    (INTRINSICS_PY,
     'system_value("alpha_to_coverage_enable_ir3", 1)\n',
     'system_value("alpha_to_coverage_enable_ir3", 1)\n'
     'system_value("rt_swap_mask_ir3", 1)\n',
     1),
    # 2. NIR divergence analysis
    (DIVERGENCE_C,
     '   case nir_intrinsic_load_alpha_to_coverage_enable_ir3:\n',
     '   case nir_intrinsic_load_alpha_to_coverage_enable_ir3:\n'
     '   case nir_intrinsic_load_rt_swap_mask_ir3:\n',
     1),
    # 3. IR3 shader header driver params
    (IR3_SHADER_H,
     '   uint32_t alpha_to_coverage_enable;\n'
     '   uint32_t __pad_06_07[2];\n',
     '   uint32_t alpha_to_coverage_enable;\n'
     '   uint32_t rt_swap_mask;\n'
     '   uint32_t __pad_07;\n',
     1),
    # 4. IR3 NIR get driver param info
    (IR3_NIR_C,
     '   case nir_intrinsic_load_alpha_to_coverage_enable_ir3:\n'
     '      param_info->offset = IR3_DP_FS(alpha_to_coverage_enable);\n'
     '      break;\n',
     '   case nir_intrinsic_load_alpha_to_coverage_enable_ir3:\n'
     '      param_info->offset = IR3_DP_FS(alpha_to_coverage_enable);\n'
     '      break;\n'
     '   case nir_intrinsic_load_rt_swap_mask_ir3:\n'
     '      param_info->offset = IR3_DP_FS(rt_swap_mask);\n'
     '      break;\n',
     1),
    # 5. IR3 compiler NIR driver param creation
    (IR3_COMPILER_C,
     '   case nir_intrinsic_load_alpha_to_coverage_enable_ir3:\n'
     '      dst[0] = create_driver_param(ctx, IR3_DP_FS(alpha_to_coverage_enable));\n'
     '      break;\n',
     '   case nir_intrinsic_load_alpha_to_coverage_enable_ir3:\n'
     '      dst[0] = create_driver_param(ctx, IR3_DP_FS(alpha_to_coverage_enable));\n'
     '      break;\n'
     '   case nir_intrinsic_load_rt_swap_mask_ir3:\n'
     '      dst[0] = create_driver_param(ctx, IR3_DP_FS(rt_swap_mask));\n'
     '      break;\n',
     1),
    # 6. tu_cmd_buffer: dynamic RT swap mask emission
    (TU_CMD,
     'static void\n'
     'tu_emit_fdm_params(struct tu_cmd_buffer *cmd,\n',
     CMD_HELPERS +
     'static void\n'
     'tu_emit_fdm_params(struct tu_cmd_buffer *cmd,\n',
     1),
    (TU_CMD,
     '   STATIC_ASSERT(IR3_DP_FS(frag_invocation_count) == IR3_DP_FS_DYNAMIC);\n'
     '   tu_cs_emit(cs, fs->fs.sample_shading ?\n'
     '              cmd->vk.dynamic_graphics_state.ms.rasterization_samples : 1);\n'
     '   tu_cs_emit(cs, cmd->vk.dynamic_graphics_state.ms.alpha_to_coverage_enable);\n'
     '   tu_cs_emit(cs, 0);\n'
     '   tu_cs_emit(cs, 0);\n',
     '   STATIC_ASSERT(IR3_DP_FS(frag_invocation_count) == IR3_DP_FS_DYNAMIC);\n'
     '   tu_cs_emit(cs, fs->fs.sample_shading ?\n'
     '              cmd->vk.dynamic_graphics_state.ms.rasterization_samples : 1);\n'
     '   tu_cs_emit(cs, cmd->vk.dynamic_graphics_state.ms.alpha_to_coverage_enable);\n'
     '   tu_cs_emit(cs, tu_z_get_rt_swap_mask(cmd));\n'
     '   tu_cs_emit(cs, 0);\n',
     1),
    # 7. Shader header: z_bgra_mask in tu_shader_key
    (SHADER_H,
     '   bool emulate_alpha_to_coverage : 1;\n'
     '   uint32_t padding : 23;\n',
     '   bool emulate_alpha_to_coverage : 1;\n'
     '   uint32_t z_bgra_mask : 8;\n'
     '   uint32_t padding : 15;\n',
     1),
    # 8. Shader CC: multi-mode lowering pass
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
     '   if (nir->info.stage == MESA_SHADER_FRAGMENT && (key->z_bgra_mask || debug_get_option_tu_z_bgra_mode() == 1))\n'
     '      NIR_PASS(_, nir, nir_shader_intrinsics_pass, tu_z_bgra_swap_output,\n'
     '               nir_metadata_control_flow, (void *)key);\n',
     1),
    # 9. Pipeline: helpers and key initialization
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
    # 10. Clear/blit: color channel swap helpers
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
            return 1
        files[path] = files[path].replace(old, new)
    for path, s in files.items():
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(s)
    print(f"{NAME}: applied successfully (TU_Z_BGRA_MODE supported: 0=sw, 1=turnipz3, 2=optimized)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
