#!/usr/bin/env python3
"""FD810: perbaikan terpadu Adreno 810 dari analisis blob A810 (V@0800.74).

Memperbaiki masalah fatal layar hitam (black screen dengan suara game):
1. Fix Sysmem CCU Buffer Underflow: GMEM A810 hanya 576 KB (0x90000). Nilai default
   a8xx_gen1 meminta total 608 KB (bv 32K + attr 128K + pos 64K + color 128K + depth 256K),
   menyebabkan depth_ccu_offset underflow ke 0xFFFF8000 (-32K) dan merusak flush frame.
   Disesuaikan dengan ukuran blob sysmem: attr 32K, pos 12K, bv 20K (total 448 KB < 576 KB).
2. Hapus disable_gmem = True: blob 810 terbukti memakai GMEM binning (test-lrz, test-query, test-tf).
3. SP_UNKNOWN_AB01: setel ke 0x00000001 (100% capture blob 810 menulis 0x1 di amble1 preamble).
4. VSC_UNKNOWN_0D08: setel ke 1 saat binning setup (sesuai blob 810).
5. KGSL chip_id 0x44010000: pastikan terdaftar bersama fallback 0xffff44010000.

Dijalankan dari root direktori Mesa. Idempoten dan aman dijalankan berulang kali.
"""
import sys

NAME = "51-fd810-blob.py"
SUMMARY = "FD810 blob: fix sysmem underflow, remove disable_gmem, ab01=1, vsc_0d08=1, chip_id=0x44010000"

DEV_INFO = "src/freedreno/common/freedreno_dev_info.h"
CMD_BUF  = "src/freedreno/vulkan/tu_cmd_buffer.cc"
DEVICES  = "src/freedreno/common/freedreno_devices.py"


def apply_dev_info(s):
    if "uint32_t vsc_unknown_0d08;" in s:
        return s, None

    # Cari anchor untuk menyisipkan vsc_unknown_0d08
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

    # Cek format alternatif jika ada
    alt_0d08 = "tu_cs_emit_regs(cs, VSC_UNKNOWN_0D08(CHIP, 0));"
    if alt_0d08 in s:
        s = s.replace(alt_0d08, "tu_cs_emit_regs(cs, VSC_UNKNOWN_0D08(CHIP, cmd->device->physical_device->info->props.vsc_unknown_0d08));", 1)
        return s, None

    return None, "VSC_UNKNOWN_0D08 anchor not found in tu_cmd_buffer.cc"


def apply_devices(s):
    # 1. Definisikan a810_raw_magic_regs jika belum ada
    magic_anchor = "a8xx_base_raw_magic_regs = [\n"
    a810_magic_def = """a810_raw_magic_regs = [
        [A6XXRegs.REG_A8XX_GRAS_BIN_FOVEAT_XY_FDM_OFFSET + 0, 0x00000000],
        [A6XXRegs.REG_A8XX_GRAS_BIN_FOVEAT_XY_FDM_OFFSET + 1, 0x00000000],
        [A6XXRegs.REG_A8XX_GRAS_BIN_FOVEAT_XY_FDM_OFFSET + 2, 0x00000000],
        [A6XXRegs.REG_A8XX_GRAS_BIN_FOVEAT_XY_FDM_OFFSET + 3, 0x00000000],
        [A6XXRegs.REG_A8XX_GRAS_BIN_FOVEAT_XY_FDM_OFFSET + 4, 0x00000000],
        [A6XXRegs.REG_A8XX_GRAS_BIN_FOVEAT_XY_FDM_OFFSET + 5, 0x00000000],

        [A6XXRegs.REG_A6XX_RB_UNKNOWN_8818,   0x00000000],
        [A6XXRegs.REG_A6XX_RB_UNKNOWN_8819,   0x00000000],
        [A6XXRegs.REG_A6XX_RB_UNKNOWN_881A,   0x00000000],
        [A6XXRegs.REG_A6XX_RB_UNKNOWN_881B,   0x00000000],
        [A6XXRegs.REG_A6XX_RB_UNKNOWN_881C,   0x00000000],
        [A6XXRegs.REG_A6XX_RB_UNKNOWN_881D,   0x00000000],
        [A6XXRegs.REG_A6XX_RB_UNKNOWN_881E,   0x00000000],
        [A6XXRegs.REG_A7XX_RB_LRZ_CNTL2,      0x00000000],
        [A6XXRegs.REG_A8XX_RB_RESOLVE_CNTL_5, 0x00000001],

        [A6XXRegs.REG_A7XX_SP_UNKNOWN_AB01,   0x00000001], # Blob 810 V@0800: 0x1 in 100% captures
        [A6XXRegs.REG_A7XX_SP_HLSQ_MODE_CNTL, 0x00000000],
        [A6XXRegs.REG_A8XX_SP_UNKNOWN_AB23,   0x00000000],

        [A6XXRegs.REG_A6XX_TPL1_PS_ROTATION_CNTL, 0x00000004],
        [A6XXRegs.REG_A6XX_TPL1_PS_SWIZZLE_CNTL, 0x00000000],

        [A6XXRegs.REG_A8XX_PC_UNKNOWN_980B, 0x00800280],
        [A6XXRegs.REG_A8XX_PC_MODE_CNTL,    0x00003f00],
    ]

"""
    if "a810_raw_magic_regs" not in s:
        if magic_anchor not in s:
            return None, "a8xx_base_raw_magic_regs anchor not found in freedreno_devices.py"
        s = s.replace(magic_anchor, a810_magic_def + magic_anchor, 1)

    # 2. Cari blok add_gpus untuk A810 dan ganti sepenuhnya dengan entri yang benar
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
            # GMEM VPC buffer sizes (sesuai blob 810):
            gmem_vpc_attr_buf_size = 16384,
            gmem_vpc_pos_buf_size = 12288,
            gmem_vpc_bv_pos_buf_size = 20480,
            # Sysmem VPC buffer sizes (Mencegah underflow GMEM 576 KB: total 448 KB < 576 KB):
            sysmem_vpc_attr_buf_size = 32768,
            sysmem_vpc_pos_buf_size = 12288,
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
        raw_magic_regs = a810_raw_magic_regs,
    ))"""

    s = s[:start] + a810_clean_block + s[end:]
    return s, None


def main():
    try:
        dev_info_src = open(DEV_INFO, encoding="utf-8").read()
        cmd_buf_src  = open(CMD_BUF, encoding="utf-8").read()
        devices_src  = open(DEVICES, encoding="utf-8").read()
    except OSError as e:
        print(f"{NAME}: WARNING cannot read source files: {e}; skipped")
        return 0

    has_a810_magic = "a810_raw_magic_regs" in devices_src
    has_a810_sysmem = "sysmem_vpc_attr_buf_size = 32768" in devices_src
    has_a810_chip = "GPUId(chip_id=0x44010000" in devices_src
    has_no_disable_gmem = "disable_gmem = True" not in devices_src[devices_src.find("Adreno (TM) 810"):devices_src.find("Adreno (TM) 810") + 800]
    has_vsc = "vsc_unknown_0d08 = 1" in devices_src
    already_done = has_a810_magic and has_a810_sysmem and has_a810_chip and has_no_disable_gmem and has_vsc

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
