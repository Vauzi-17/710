#!/usr/bin/env python3
# From: Vauzi-17
"""A8XX: Emit REG_A8XX_RB_RESOLVE_CR_CNTL=1 in preamble magic registers.

Qualcomm proprietary Vulkan traces on A8xx GPUs (including Adreno 810) emit
RB_RESOLVE_CR_CNTL (0x8816) = 1 in 100% of command stream preambles (amble1)
to initialize the hardware Color/Clear Resolve block.

This register is defined in a6xx.xml for A8XX- but was omitted from
a8xx_base_raw_magic_regs in freedreno_devices.py.

Run from Mesa source root. Idempotent and safe to run multiple times.
"""
import sys

NAME = "52-a8xx-resolve-cr-cntl.py"
MARKER = "REG_A8XX_RB_RESOLVE_CR_CNTL"
DEVICES = "src/freedreno/common/freedreno_devices.py"

OLD_CHUNK = (
    "        [A6XXRegs.REG_A7XX_RB_LRZ_CNTL2,      0x00000000],\n"
    "        [A6XXRegs.REG_A8XX_RB_RESOLVE_CNTL_5, 0x00000001],\n"
)

NEW_CHUNK = (
    "        [A6XXRegs.REG_A7XX_RB_LRZ_CNTL2,      0x00000000],\n"
    "        [A6XXRegs.REG_A8XX_RB_RESOLVE_CR_CNTL, 0x00000001],\n"
    "        [A6XXRegs.REG_A8XX_RB_RESOLVE_CNTL_5, 0x00000001],\n"
)


def main():
    try:
        content = open(DEVICES, "r", encoding="utf-8").read()
    except OSError as e:
        print(f"{NAME}: WARNING cannot read {DEVICES}: {e}; skipped")
        return 0

    if MARKER in content:
        print(f"{NAME}: already applied ({MARKER} present)")
        return 0

    if OLD_CHUNK not in content:
        print(f"{NAME}: ERROR target anchor not found in {DEVICES}", file=sys.stderr)
        return 1

    new_content = content.replace(OLD_CHUNK, NEW_CHUNK, 1)
    try:
        open(DEVICES, "w", encoding="utf-8").write(new_content)
    except OSError as e:
        print(f"{NAME}: ERROR cannot write {DEVICES}: {e}", file=sys.stderr)
        return 1

    print(f"{NAME}: applied successfully (added {MARKER}=1 to a8xx_base_raw_magic_regs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
