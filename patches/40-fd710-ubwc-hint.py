#!/usr/bin/env python3
"""FD710: TPL1_DBG_ECO_CNTL1.TP_UBWC_FLAG_HINT off (0x00040700 -> 0x00000700).

Blob 710 (GLES + Vulkan, V@0615) always writes 0x700; the value is a constant in
both blobs. Mesa requires this bit to match every driver in the system
(BLIT_OP_SCALE on UBWC). FD710 inherited True from a7xx_gen1.

Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = "40-fd710-ubwc-hint.py"
DEVICES = "src/freedreno/common/freedreno_devices.py"
ANCHOR = "        raw_magic_regs = a710_raw_magic_regs,\n    ))\n"
LINE = "GPUProps(enable_tp_ubwc_flag_hint = False).apply_props(s.gpu_infos[-1])\n"


def main():
    try:
        src = open(DEVICES, encoding="utf-8").read()
    except OSError as e:
        print(f"{NAME}: WARNING cannot read {DEVICES}: {e}; skipped")
        return 0
    if LINE in src:
        print(f"{NAME}: already applied")
        return 0
    if src.count(ANCHOR) != 1:
        print(f"{NAME}: WARNING anchor matched {src.count(ANCHOR)}x (want 1); patch skipped")
        return 0
    src = src.replace(ANCHOR, ANCHOR + LINE)
    with open(DEVICES, "w", encoding="utf-8", newline="\n") as f:
        f.write(src)
    print(f"{NAME}: applied (FD710 enable_tp_ubwc_flag_hint = False)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
