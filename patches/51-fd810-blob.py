#!/usr/bin/env python3
"""FD810: unified Adreno 810 hardware tuning from Vulkan blob trace analysis (V@0800.74).

Resolves fatal black screen issues and optimizes Turnip Vulkan architecture for A810:
1. Fix Sysmem CCU Buffer Underflow: A810 GMEM size is 576 KB (0x90000). Upstream
   a8xx_gen1 defaults requested 608 KB (bv 32K + attr 128K + pos 64K + color 128K + depth 256K),
   causing depth_ccu_offset to underflow to 0xFFFF8000 (-32K) and breaking frame flushes.
   Aligned with Vulkan blob sizes: attr 48K, pos 16K, bv 20K (total 468 KB < 576 KB).
2. Clean Sysmem & GMEM VPC Alignment: Native __calc_gmem_cache_offsets() formula produces
   offsets matching official Vulkan blob hardware traces (Sysmem: attr 0x7f000, pos 0x7b000,
   color 0x5b000, depth 0x1b000; GMEM: attr 0x7f000, pos 0x79000, color 0x75000).
   Requires no manual hardcoding in fd6_gmem_cache.h.
3. GMEM VPC Buffer Sizes: Match Vulkan blob binning buffer sizes:
   attr 48K, pos 24K, bv 20K (previously 16K/12K/20K from GLES).
4. Remove disable_gmem = True: A810 blob actively utilizes GMEM binning (verified across 39+ dEQP tests).
5. SP_UNKNOWN_AB01 = 0: Vulkan blob consistently writes 0x0 across 312 writes (value 1 is GLES-only).
   Consistently utilizes upstream a8xx_base_raw_magic_regs.
6. VSC_UNKNOWN_0D08 = 1: Enabled in binning setup (matches A810 Vulkan & GLES traces).
7. KGSL chip_id 0x44010000: Registered alongside fallback 0xffff44010000.
8. cs_shared_mem_size: Retains 32 KB baseline for 1 CCU.

Run from the Mesa source root. Idempotent and safe to rerun.
"""
import sys

NAME = "51-fd810-blob.py"
SUMMARY = "FD810 Vulkan blob: fix sysmem VPC 48/16/20K, GMEM VPC 48/24/20K, clean offsets, remove disable_gmem, ab01=0, vsc_0d08=1, chip_id=0x44010000"

DEV_INFO   = "src/freedreno/common/freedreno_dev_info.h"
CMD_BUF    = "src/freedreno/vulkan/tu_cmd_buffer.cc"
DEVICES    = "src/freedreno/common/freedreno_devices.py"
GMEM_CACHE = "src/freedreno/common/fd6_gmem_cache.h"


def apply_dev_info(s):
    if "uint32_t vsc_unknown_0d08;" in s:
        return s, None

    # Find anchor to insert vsc_unknown_0d08
    anchor = None
    for cand in ("      bool enable_tp_ubwc_flag_hint;\n",
                 "      bool has_image_processing;\n",
                 "      bool disable_gmem;\n",
                 "      bool has_salu_int_narrowing_quirk;\n"):
        if cand in s:
            anchor = cand
            break

    if not anchor:
        return None, "cannot find suitable anchor in freedreno_dev_info.h"

    insert = "      uint32_t vsc_unknown_0d08;\n"
    s = s.replace(anchor, anchor + insert, 1)
    return s, None


def apply_cmd_buffer(s):
    if "props.vsc_unknown_0d08" in s:
        return s, None

    old_0d08 = "      tu_cs_emit_regs(cs, VSC_UNKNOWN_0D08(CHIP, 0));\n"
    new_0d08 = (
        "      tu_cs_emit_regs(cs, VSC_UNKNOWN_0D08(CHIP,\n"
        "         cmd->device->physical_device->info->props.vsc_unknown_0d08));\n"
    )
    if s.count(old_0d08) == 1:
        s = s.replace(old_0d08, new_0d08, 1)
        return s, None

    # Check alternative format if present
    alt_0d08 = "tu_cs_emit_regs(cs, VSC_UNKNOWN_0D08(CHIP, 0));"
    if alt_0d08 in s:
        s = s.replace(alt_0d08, "tu_cs_emit_regs(cs, VSC_UNKNOWN_0D08(CHIP, cmd->device->physical_device->info->props.vsc_unknown_0d08));", 1)
        return s, None

    return None, "VSC_UNKNOWN_0D08 anchor not found in tu_cmd_buffer.cc"


def apply_devices(s):
    # Remove a810_raw_magic_regs if partially injected (Vulkan uses upstream a8xx_base_raw_magic_regs)
    if "a810_raw_magic_regs = [\n" in s:
        m_start = s.find("a810_raw_magic_regs = [\n")
        m_end = s.find("]\n\n", m_start)
        if m_start != -1 and m_end != -1:
            s = s[:m_start] + s[m_end + 3:]

    # Locate add_gpus block for A810 and replace with clean entry
    idx = s.find('Adreno (TM) 810')
    if idx == -1:
        return None, "Adreno (TM) 810 entry not found in freedreno_devices.py"

    start = s.rfind('add_gpus(', 0, idx)
    end = s.find('    ))', idx)
    if start == -1 or end == -1:
        return None, "Could not delineate A810 add_gpus block in freedreno_devices.py"
    end += 6  # include '    ))'

    a810_clean_block = """add_gpus([
        GPUId(chip_id=0x44010000, name="Adreno (TM) 810"),     # KGSL firmware ID
        GPUId(chip_id=0xffff44010000, name="Adreno (TM) 810"), # Fallback DRM
    ], A6xxGPUInfo(
        CHIP.A8XX,
        [a7xx_base, a7xx_gen3, a8xx_base, a8xx_gen1, GPUProps(
            # GMEM VPC buffer sizes (matches Vulkan blob A810 trace 48/24/20 KB):
            gmem_vpc_attr_buf_size = 49152,
            gmem_vpc_pos_buf_size = 24576,
            gmem_vpc_bv_pos_buf_size = 20480,
            # Sysmem VPC buffer sizes (matches Vulkan blob A810 trace 48/16/20 KB -> total 468 KB < 576 KB, no underflow):
            sysmem_vpc_attr_buf_size = 49152,
            sysmem_vpc_pos_buf_size = 16384,
            sysmem_vpc_bv_pos_buf_size = 20480,
            vsc_unknown_0d08 = 1,
            has_fs_tex_prefetch = False,
        )],
        num_ccu = 1,
        num_slices = 1,
        tile_align_w = 32,
        tile_align_h = 16,
        tile_max_w = 16384,
        tile_max_h = 16384,
        num_vsc_pipes = 32,
        cs_shared_mem_size = 32 * 1024,
        wave_granularity = 2,
        fibers_per_sp = 128 * 2 * 16,
        raw_magic_regs = a8xx_base_raw_magic_regs,
    ))"""

    s = s[:start] + a810_clean_block + s[end:]
    return s, None


def apply_gmem_cache(s):
    # Ensure no stale hardcode in fd6_gmem_cache.h (upstream __calc_gmem_cache_offsets is accurate)
    marker = "/* Adreno 810: align sysmem VPC and CCU layout with blob hardware trace */"
    if marker in s:
        start = s.find("      if (info->num_ccu == 1 && gmemsize_bytes == 576 * 1024) {")
        end = s.find("      }\n", start)
        if start != -1 and end != -1:
            s = s[:start] + s[end + 8:]
    return s, None


def main():
    try:
        dev_info_src   = open(DEV_INFO, encoding="utf-8").read()
        cmd_buf_src    = open(CMD_BUF, encoding="utf-8").read()
        devices_src    = open(DEVICES, encoding="utf-8").read()
        gmem_cache_src = open(GMEM_CACHE, encoding="utf-8").read()
    except OSError as e:
        print(f"{NAME}: WARNING cannot read source files: {e}; skipped")
        return 0

    has_a810_sysmem = "sysmem_vpc_attr_buf_size = 49152" in devices_src
    has_a810_gmem = "gmem_vpc_attr_buf_size = 49152" in devices_src
    has_a810_chip = "GPUId(chip_id=0x44010000" in devices_src
    a810_scope = devices_src[devices_src.find("Adreno (TM) 810"):devices_src.find("Adreno (TM) 810") + 800]
    has_no_disable_gmem = "disable_gmem = True" not in a810_scope
    has_vsc = "vsc_unknown_0d08 = 1" in devices_src
    has_upstream_magic = "raw_magic_regs = a8xx_base_raw_magic_regs" in a810_scope
    no_a810_magic = "a810_raw_magic_regs" not in devices_src
    no_gmem_cache_hack = "/* Adreno 810: align sysmem VPC and CCU layout with blob hardware trace */" not in gmem_cache_src

    already_done = (has_a810_sysmem and has_a810_gmem and has_a810_chip and
                    has_no_disable_gmem and has_vsc and has_upstream_magic and
                    no_a810_magic and no_gmem_cache_hack)

    if already_done:
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

    new_gmem_cache, err = apply_gmem_cache(gmem_cache_src)
    if err:
        print(f"{NAME}: WARNING {err}; patch skipped")
        return 0

    with open(DEV_INFO, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_dev_info)
    with open(CMD_BUF, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_cmd_buf)
    with open(DEVICES, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_devices)
    if new_gmem_cache != gmem_cache_src:
        with open(GMEM_CACHE, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_gmem_cache)

    print(f"{NAME}: applied ({SUMMARY})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
