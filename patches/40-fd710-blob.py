#!/usr/bin/env python3
"""FD710: consolidated hardware property and register tuning from Adreno 710 blob analysis (V@0615).

Consolidates blob-matching properties for Adreno 710 (chip_id 0x07010000):
1. TPL1_DBG_ECO_CNTL1.TP_UBWC_FLAG_HINT off (0x00040700 -> 0x00000700):
   Matches system drivers constant for UBWC handling (enable_tp_ubwc_flag_hint = False).
2. tile_align_w/h 64x32 -> 32x16:
   Matches blob binning granularity for 1-CCU hardware (tile_align_w = 32, tile_align_h = 16).
3. SP_UNKNOWN_AB01 1 -> 0:
   Vulkan blob writes 0x0 consistently across all captures (matches a730/a740/a750 in Mesa).
4. supports_linear_mipmap_threshold_in_blocks off:
   Reverts linear mipmap fallback threshold to texels (per-chip feature off in 710 blob).
5. VSC_UNKNOWN_0D08 0 -> 1:
   Blob writes 1 in binning setup; adds props.vsc_unknown_0d08 emission.
6. RB_UNKNOWN_8E09 0x7 -> 0x4:
   Blob writes 0x4; adds props.rb_unknown_8e09 emission.
7. has_eolm_eogm off:
   Blob keeps SP_CHICKEN_BITS at 0x400 without enabling EOLM/EOGM bits.

Run from the Mesa source root. All edits are applied or none. Idempotent and safe to rerun.
"""
import sys

NAME = "40-fd710-blob.py"
SUMMARY = "FD710 blob: ubwc_hint=False, tile_align 32x16, ab01=0, linmip=False, vsc_0d08=1, rb_8e09=0x4, no_eolm"

DEV_INFO = "src/freedreno/common/freedreno_dev_info.h"
CMD_BUF = "src/freedreno/vulkan/tu_cmd_buffer.cc"
DEVICES = "src/freedreno/common/freedreno_devices.py"


def apply_dev_info(s):
    hint_line = "      bool enable_tp_ubwc_flag_hint;\n"
    if hint_line not in s:
        return None, "cannot find enable_tp_ubwc_flag_hint in dev_info"

    additions = ""
    if "uint32_t rb_unknown_8e09;" not in s:
        additions += "\n      uint32_t rb_unknown_8e09;\n"
    if "uint32_t vsc_unknown_0d08;" not in s:
        additions += "\n      uint32_t vsc_unknown_0d08;\n"

    if additions:
        s = s.replace(hint_line, hint_line + additions, 1)
    return s, None


def apply_cmd_buffer(s):
    old_8e09 = "         tu_cs_emit_regs(cs, RB_UNKNOWN_8E09(CHIP, 0x7));\n"
    new_8e09 = (
        "         tu_cs_emit_regs(cs, RB_UNKNOWN_8E09(CHIP,\n"
        "            phys_dev->info->props.rb_unknown_8e09 ?\n"
        "            phys_dev->info->props.rb_unknown_8e09 : 0x7));\n"
    )
    if "phys_dev->info->props.rb_unknown_8e09" not in s:
        if s.count(old_8e09) != 1:
            return None, "RB_UNKNOWN_8E09 anchor not found/unique in tu_cmd_buffer.cc"
        s = s.replace(old_8e09, new_8e09, 1)

    old_0d08 = "      tu_cs_emit_regs(cs, VSC_UNKNOWN_0D08(CHIP, 0));\n"
    new_0d08 = (
        "      tu_cs_emit_regs(cs, VSC_UNKNOWN_0D08(CHIP,\n"
        "         cmd->device->physical_device->info->props.vsc_unknown_0d08));\n"
    )
    if "props.vsc_unknown_0d08" not in s:
        if s.count(old_0d08) != 1:
            return None, "VSC_UNKNOWN_0D08 anchor not found/unique in tu_cmd_buffer.cc"
        s = s.replace(old_0d08, new_0d08, 1)

    return s, None


def apply_devices(s):
    scope_magic = "a710_raw_magic_regs = [\n"
    if scope_magic not in s:
        return None, "a710_raw_magic_regs anchor not found in freedreno_devices.py"
    magic_start = s.index(scope_magic)
    magic_end = s.find("add_gpus", magic_start)
    if magic_end < 0:
        return None, "add_gpus after a710_raw_magic_regs not found"

    magic_block = s[magic_start:magic_end]
    old_ab01 = "        [A6XXRegs.REG_A7XX_SP_UNKNOWN_AB01, 0x00000001],\n"
    new_ab01 = "        [A6XXRegs.REG_A7XX_SP_UNKNOWN_AB01, 0x00000000],\n"
    if old_ab01 in magic_block:
        magic_block = magic_block.replace(old_ab01, new_ab01, 1)
        s = s[:magic_start] + magic_block + s[magic_end:]
    elif new_ab01 not in magic_block:
        return None, "SP_UNKNOWN_AB01 anchor not found in a710_raw_magic_regs"

    old_tile = (
        'name="FD710"), # Default no-speedbin fallback\n'
        '    ], A6xxGPUInfo(\n'
        '        CHIP.A7XX,\n'
        '        [a7xx_base, a7xx_gen1],\n'
        '        num_ccu = 1,\n'
        '        tile_align_w = 64,\n'
        '        tile_align_h = 32,\n'
    )
    new_tile = (
        'name="FD710"), # Default no-speedbin fallback\n'
        '    ], A6xxGPUInfo(\n'
        '        CHIP.A7XX,\n'
        '        [a7xx_base, a7xx_gen1],\n'
        '        num_ccu = 1,\n'
        '        tile_align_w = 32,\n'
        '        tile_align_h = 16,\n'
    )
    if old_tile in s:
        s = s.replace(old_tile, new_tile, 1)
    elif new_tile not in s:
        return None, "FD710 tile_align anchor not found in freedreno_devices.py"

    anchor_710 = "        raw_magic_regs = a710_raw_magic_regs,\n    ))\n"
    props_710 = (
        "GPUProps(enable_tp_ubwc_flag_hint = False, "
        "supports_linear_mipmap_threshold_in_blocks = False, "
        "vsc_unknown_0d08 = 1, "
        "rb_unknown_8e09 = 0x4, "
        "has_eolm_eogm = False).apply_props(s.gpu_infos[-1])\n"
    )
    if props_710 not in s:
        if s.count(anchor_710) != 1:
            return None, "FD710 raw_magic_regs anchor not unique/found"
        s = s.replace(anchor_710, anchor_710 + props_710, 1)

    return s, None


def main():
    try:
        dev_info_src = open(DEV_INFO, encoding="utf-8").read()
        cmd_buf_src = open(CMD_BUF, encoding="utf-8").read()
        devices_src = open(DEVICES, encoding="utf-8").read()
    except OSError as e:
        print(f"{NAME}: WARNING cannot read source files: {e}; skipped")
        return 0

    props_710 = (
        "GPUProps(enable_tp_ubwc_flag_hint = False, "
        "supports_linear_mipmap_threshold_in_blocks = False, "
        "vsc_unknown_0d08 = 1, "
        "rb_unknown_8e09 = 0x4, "
        "has_eolm_eogm = False).apply_props(s.gpu_infos[-1])"
    )
    has_props = props_710 in devices_src
    has_tile = "tile_align_w = 32,\n        tile_align_h = 16," in devices_src
    has_ab01 = (
        "[A6XXRegs.REG_A7XX_SP_UNKNOWN_AB01, 0x00000000]," in devices_src
        and "a710_raw_magic_regs = [" in devices_src
    )
    if has_props and has_tile and has_ab01:
        print(f"{NAME}: already applied")
        return 0

    new_dev_info, err = apply_dev_info(dev_info_src)
    if err:
        print(f"{NAME}: WARNING {err}; patch skipped")
        return 0

    new_cmd_buf, err = apply_cmd_buffer(cmd_buf_src)
    if err:
        print(f"{NAME}: WARNING {err}; patch skipped")
        return 0

    new_devices, err = apply_devices(devices_src)
    if err:
        print(f"{NAME}: WARNING {err}; patch skipped")
        return 0

    with open(DEV_INFO, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_dev_info)
    with open(CMD_BUF, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_cmd_buf)
    with open(DEVICES, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_devices)

    print(f"{NAME}: applied ({SUMMARY})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
