#!/usr/bin/env python3
"""FD722: penyesuaian nilai register dan properti hardware Adreno 722 dari analisis blob Qualcomm (chip_id 0x43020100).

Perbaikan berdasarkan analisis 116 trace cmdstream .rd dan IOCTL kernel KGSL:
1. Mendefinisikan a722_raw_magic_regs mandiri untuk menggantikan aliasing keliru ke a730_raw_magic_regs.
   Mengoreksi 12 register deviasi:
   - REG_A6XX_TPL1_DBG_ECO_CNTL = 0x03000000 (sebelumnya 0x01000000 dari A730)
   - REG_A6XX_TPL1_DBG_ECO_CNTL1 = 0x00000700 (sebelumnya 0x00040724 dari A730)
   - REG_A6XX_SP_CHICKEN_BITS = 0x00000400 (sebelumnya 0x00001400 dari A730)
   - REG_A7XX_SP_CHICKEN_BITS_1 = 0x01400400 (sebelumnya 0x00402400 dari A730)
   - REG_A7XX_SP_CHICKEN_BITS_2 = 0x00000010 (fitur unik A722, sebelumnya 0x00000000)
   - REG_A6XX_SP_DBG_ECO_CNTL = 0x11000000 (sebelumnya 0x10000000 dari A730)
   - REG_A7XX_SP_HLSQ_DBG_ECO_CNTL = 0x00000000 (sebelumnya 0x00008000 dari A730)
   - REG_A6XX_PC_DBG_ECO_CNTL = 0x20100000 (sebelumnya 0x20080000 dari A730)
   - REG_A7XX_PC_UNKNOWN_9E24 = 0x01fc7f00 (sebelumnya 0x21fc7f00 dari A730)
   - REG_A7XX_RB_CCU_DBG_ECO_CNTL = 0x00080000 (sebelumnya 0x02080000 dari A730)
   - REG_A6XX_UCHE_CACHE_WAYS = 0x00040004 (sebelumnya 0x00840004 dari A730)
   - REG_A7XX_UCHE_UNKNOWN_0E11 = 0x00000000 (sebelumnya 0x00000040 dari A730)
2. Menyetel highest_bank_bit = 15 sesuai properti KGSL (sebelumnya tidak disetel / None).
3. Menyetel has_lpac = False via GPUProps (hardware LPAC dinonaktifkan di silikon A722).

Dijalankan dari root direktori Mesa. Idempoten dan aman dijalankan berulang kali.
"""
import sys

NAME = "56-fd722-blob.py"
SUMMARY = "FD722: a722_raw_magic_regs (TPL1 0x03000000/0x700, SP chicken 0x400/0x01400400/0x10, eco regs), highest_bank_bit=15, has_lpac=False"

DEVICES = "src/freedreno/common/freedreno_devices.py"

MAGIC_BLOCK = """a722_raw_magic_regs = [
        [A6XXRegs.REG_A6XX_UCHE_CACHE_WAYS, 0x00040004],
        [A6XXRegs.REG_A6XX_TPL1_DBG_ECO_CNTL, 0x03000000],
        [A6XXRegs.REG_A6XX_TPL1_DBG_ECO_CNTL1, 0x00000700],

        [A6XXRegs.REG_A6XX_SP_CHICKEN_BITS, 0x00000400],
        [A6XXRegs.REG_A7XX_SP_CHICKEN_BITS_1, 0x01400400],
        [A6XXRegs.REG_A7XX_SP_CHICKEN_BITS_2, 0x00000010],
        [A6XXRegs.REG_A7XX_SP_CHICKEN_BITS_3, 0x00000000],

        [A6XXRegs.REG_A7XX_UCHE_UNKNOWN_0E10, 0x00000000],
        [A6XXRegs.REG_A7XX_UCHE_UNKNOWN_0E11, 0x00000000],
        [A6XXRegs.REG_A7XX_SP_HLSQ_DBG_ECO_CNTL, 0x00000000],
        [A6XXRegs.REG_A6XX_SP_DBG_ECO_CNTL, 0x11000000],

        [A6XXRegs.REG_A6XX_PC_MODE_CNTL, 0x00001f1f],
        [A6XXRegs.REG_A6XX_PC_DBG_ECO_CNTL, 0x20100000],
        [A6XXRegs.REG_A7XX_PC_UNKNOWN_9E24, 0x01fc7f00],

        [A6XXRegs.REG_A7XX_VFD_DBG_ECO_CNTL, 0x00000000],
        [A6XXRegs.REG_A7XX_SP_ISDB_CNTL, 0x00000000],
        [A6XXRegs.REG_A7XX_SP_UNKNOWN_AE6A, 0x00000000],
        [A6XXRegs.REG_A7XX_SP_HLSQ_TIMEOUT_THRESHOLD_DP, 0x00000080],
        [A6XXRegs.REG_A7XX_SP_HLSQ_DBG_ECO_CNTL_1, 0x00000000],
        [A6XXRegs.REG_A7XX_SP_HLSQ_MODE_CNTL, 0x00000000],

        [A6XXRegs.REG_A7XX_SP_UNKNOWN_AB01, 0x00000000],
        [A6XXRegs.REG_A7XX_SP_UNKNOWN_AB22, 0x00000000],
        [A6XXRegs.REG_A7XX_SP_UNKNOWN_B310, 0x00000000],

        [A6XXRegs.REG_A7XX_SP_UNKNOWN_0CE2,   0x00000000],
        [A6XXRegs.REG_A7XX_SP_UNKNOWN_0CE2+1, 0x00000000],
        [A6XXRegs.REG_A7XX_SP_UNKNOWN_0CE4,   0x00000000],
        [A6XXRegs.REG_A7XX_SP_UNKNOWN_0CE4+1, 0x00000000],
        [A6XXRegs.REG_A7XX_SP_UNKNOWN_0CE6,   0x00000000],
        [A6XXRegs.REG_A7XX_SP_UNKNOWN_0CE6+1, 0x00000000],

        [A6XXRegs.REG_A7XX_GRAS_ROTATION_CNTL, 0x00000000],
        [A6XXRegs.REG_A6XX_GRAS_DBG_ECO_CNTL,  0x00000800],

        [A6XXRegs.REG_A7XX_RB_UNKNOWN_8E79, 0x00000000],
        [A6XXRegs.REG_A7XX_RB_LRZ_CNTL2, 0x00000000],
        [A6XXRegs.REG_A7XX_RB_CCU_DBG_ECO_CNTL, 0x00080000],
        [A6XXRegs.REG_A6XX_VPC_DBG_ECO_CNTL, 0x02000000],
        [A6XXRegs.REG_A6XX_UCHE_UNKNOWN_0E12, 0x03200000],
        [A6XXRegs.REG_A6XX_RB_DBG_ECO_CNTL,   0x00000000],
]

"""

NEW_A722_BLOCK = """add_gpus([
        GPUId(chip_id=0x43020100, name="Adreno (TM) 722"),
        GPUId(chip_id=0xffff43020100, name="Adreno (TM) 722"),
    ], A6xxGPUInfo(
        CHIP.A7XX,
        [a7xx_base, a7xx_gen1, GPUProps(has_lpac = False)],
        num_ccu = 1,
        tile_align_w = 64,
        tile_align_h = 16,
        tile_max_w = 1024,
        tile_max_h = 1024,
        num_vsc_pipes = 32,
        cs_shared_mem_size = 32 * 1024,
        wave_granularity = 2,
        fibers_per_sp = 128 * 2 * 16,
        highest_bank_bit = 15,
        raw_magic_regs = a722_raw_magic_regs,
    ))"""


def apply_devices(s):
    if "a722_raw_magic_regs" in s and "raw_magic_regs = a722_raw_magic_regs" in s:
        return s, None

    # Hapus a722_raw_magic_regs jika sempat terinjeksi parsial
    if "a722_raw_magic_regs = [\n" in s:
        m_start = s.find("a722_raw_magic_regs = [\n")
        m_end = s.find("]\n\n", m_start)
        if m_start != -1 and m_end != -1:
            s = s[:m_start] + s[m_end + 3:]

    idx = s.find('Adreno (TM) 722')
    if idx == -1:
        return None, "Adreno (TM) 722 entry not found in freedreno_devices.py"

    start = s.rfind('add_gpus(', 0, idx)
    end = s.find('    ))', idx)
    if start == -1 or end == -1:
        return None, "Could not delineate Adreno 722 add_gpus block in freedreno_devices.py"
    end += 6  # include '    ))'

    # Ganti blok A722 lama dengan a722_raw_magic_regs + NEW_A722_BLOCK
    replacement = MAGIC_BLOCK + NEW_A722_BLOCK
    s = s[:start] + replacement + s[end:]
    return s, None


def main():
    try:
        s = open(DEVICES, encoding="utf-8").read()
    except OSError as e:
        print(f"{NAME}: WARNING cannot read {DEVICES}: {e}; skipped")
        return 0

    if "a722_raw_magic_regs" in s and "raw_magic_regs = a722_raw_magic_regs" in s:
        print(f"{NAME}: already applied")
        return 0

    new_s, err = apply_devices(s)
    if err:
        print(f"{NAME}: WARNING {err}; skipped")
        return 0

    with open(DEVICES, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_s)

    print(f"{NAME}: applied ({SUMMARY})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
