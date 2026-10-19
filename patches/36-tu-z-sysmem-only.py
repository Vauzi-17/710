#!/usr/bin/env python3
"""Turnip-Z port: force sysmem rendering, and keep the bin-restore preamble
consistent with it.

Turnip-Z renders everything in system memory on every GPU (TU_SD865_SYSMEM_ONLY,
default on): use_sysmem_rendering() returns true after the upstream GMEM-blocking
checks pass, instead of asking autotune. Because every pass is then sysmem, the
bin restore preamble must be fixed up too, since upstream builds it once at
startup for GMEM render passes:

  - emit_rb_ccu_cntl() is called with gmem = true, so the CCU is reprogrammed
    with the GMEM carveout layout even when every pass renders in sysmem. With
    tiled + UBWC surfaces that mismatch corrupts individual pixels.
  - tu6_init_static_regs() ends with two per-draw packets (SP_PS_CNTL_0 and
    SP_VS_CONST_CONFIG) which the restore preamble must not touch.

Turnip-Z flips the CCU to the sysmem layout (gmem = !safe) and stops
tu6_init_static_regs before its last two packets, where
safe = TU_SD865_SAFE_AMBLE && TU_SD865_SYSMEM_ONLY.

Knobs:
  TU_Z_SYSMEM_ONLY (default true)  force sysmem for every render pass
  TU_Z_SAFE_AMBLE  (default true)  fix the bin-restore preamble for sysmem
safe is TU_Z_SAFE_AMBLE && (TU_DEBUG=sysmem || TU_Z_SYSMEM_ONLY), so with the
default sysmem-only the amble fix is active on every GPU.

Needs nothing else; independent of 30/33. Applies to all GPUs.

Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = "36-tu-z-sysmem-only.py"
MARKER = "TU_Z_SYSMEM_ONLY"
FILE = "src/freedreno/vulkan/tu_cmd_buffer.cc"

EDITS = [
    (FILE,
     '#include "tu_cmd_buffer.h"\n'
     '\n'
     '#include "vk_common_entrypoints.h"\n',
     '#include "tu_cmd_buffer.h"\n'
     '\n'
     '#include "util/u_debug.h"\n'
     '#include "vk_common_entrypoints.h"\n',
     1),
    (FILE,
     'static bool\n'
     'use_sysmem_rendering(struct tu_cmd_buffer *cmd,\n'
     '                     tu_autotune::rp_ctx_t *rp_ctx,\n'
     '                     tu_autotune::rp_key_opt rp_key)\n'
     '{\n'
     '   if (TU_DEBUG(SYSMEM)) {\n',
     'DEBUG_GET_ONCE_BOOL_OPTION(tu_z_sysmem_only, "TU_Z_SYSMEM_ONLY", true)\n'
     'DEBUG_GET_ONCE_BOOL_OPTION(tu_z_safe_amble, "TU_Z_SAFE_AMBLE", true)\n'
     '\n'
     'static bool\n'
     'tu_z_is_safe_amble(void)\n'
     '{\n'
     '   return debug_get_option_tu_z_safe_amble() &&\n'
     '          (TU_DEBUG(SYSMEM) || debug_get_option_tu_z_sysmem_only());\n'
     '}\n'
     '\n'
     'static bool\n'
     'use_sysmem_rendering(struct tu_cmd_buffer *cmd,\n'
     '                     tu_autotune::rp_ctx_t *rp_ctx,\n'
     '                     tu_autotune::rp_key_opt rp_key)\n'
     '{\n'
     '   if (TU_DEBUG(SYSMEM)) {\n',
     1),
    (FILE,
     '   tu_autotune::render_mode optimal_mode =\n'
     '      cmd->device->autotune->get_optimal_mode(cmd, rp_ctx, rp_key);\n'
     '\n'
     '   return optimal_mode == tu_autotune::render_mode::SYSMEM;\n',
     '   if (debug_get_option_tu_z_sysmem_only()) {\n'
     '      cmd->state.rp.force_render_mode_reason = "Turnip-Z: sysmem only";\n'
     '      return true;\n'
     '   }\n'
     '\n'
     '   tu_autotune::render_mode optimal_mode =\n'
     '      cmd->device->autotune->get_optimal_mode(cmd, rp_ctx, rp_key);\n'
     '\n'
     '   return optimal_mode == tu_autotune::render_mode::SYSMEM;\n',
     1),
    (FILE,
     'template <chip CHIP>\n'
     'static void\n'
     'tu6_init_static_regs(struct tu_device *dev, struct tu_cs *cs)\n'
     '{\n'
     '   const struct tu_physical_device *phys_dev = dev->physical_device;\n',
     'template <chip CHIP>\n'
     'static void\n'
     'tu6_init_static_regs(struct tu_device *dev, struct tu_cs *cs,\n'
     '                     bool bin_preamble = false)\n'
     '{\n'
     '   const struct tu_physical_device *phys_dev = dev->physical_device;\n',
     1),
    (FILE,
     '   if (phys_dev->info->props.has_early_preamble) {\n'
     '      tu_cs_emit_regs(cs, A6XX_SP_PS_CNTL_0());\n'
     '   }\n',
     '   if (phys_dev->info->props.has_early_preamble &&\n'
     '       !(bin_preamble && tu_z_is_safe_amble())) {\n'
     '      tu_cs_emit_regs(cs, A6XX_SP_PS_CNTL_0());\n'
     '   }\n',
     1),
    (FILE,
     '   /* Workaround for draw state with constlen not being applied for\n'
     '    * zero-instance draw calls. See IR3_CONST_ALLOC_DRIVER_PARAMS allocation\n'
     '    * for more info.\n'
     '    */\n'
     '   tu_cs_emit_regs(cs, SP_VS_CONST_CONFIG(CHIP,\n'
     '      .constlen = 8,\n'
     '      .enabled = true,\n'
     '   ));\n',
     '   /* Workaround for draw state with constlen not being applied for\n'
     '    * zero-instance draw calls. See IR3_CONST_ALLOC_DRIVER_PARAMS allocation\n'
     '    * for more info.\n'
     '    */\n'
     '   if (!(bin_preamble && tu_z_is_safe_amble())) {\n'
     '      tu_cs_emit_regs(cs, SP_VS_CONST_CONFIG(CHIP,\n'
     '         .constlen = 8,\n'
     '         .enabled = true,\n'
     '      ));\n'
     '   }\n',
     1),
    (FILE,
     '   tu6_init_static_regs<CHIP>(dev, cs);\n'
     '\n'
     '   if (!bv)\n'
     '      emit_rb_ccu_cntl<CHIP>(cs, dev, true);\n',
     '   tu6_init_static_regs<CHIP>(dev, cs, true);\n'
     '\n'
     '   if (!bv)\n'
     '      emit_rb_ccu_cntl<CHIP>(cs, dev, !tu_z_is_safe_amble());\n',
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
    for path, old, new, count in EDITS:
        files[path] = files[path].replace(old, new)
    for path, s in files.items():
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(s)
    print(f"{NAME}: applied (TU_Z_SYSMEM_ONLY default on, TU_Z_SAFE_AMBLE default on)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
