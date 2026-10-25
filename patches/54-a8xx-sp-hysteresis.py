#!/usr/bin/env python3
# From: Vauzi-17
"""A8XX: Initialize Shader Processor hysteresis thresholds in context preamble.

Qualcomm proprietary traces on Adreno 8xx GPUs show SP hysteresis registers
configured during shader execution (SP_PS_HYSTERESIS=0x00000c00, SP_VS_HYSTERESIS=0x00000400,
SP_CS_HYSTERESIS=0x00000400).

Upstream Turnip only touched hysteresis inside tu_emit_rt_workaround(), which is
disabled for A8xx (has_rt_workaround=False), leaving hysteresis at 0. This caused
SP ALU clusters to aggressively power-gate between draw calls, adding wake-up
latency in draw-heavy workloads like Switch emulation.

Run from Mesa source root. Idempotent and safe to run multiple times.
"""
import sys

NAME = "54-a8xx-sp-hysteresis.py"
MARKER = "SP_PS_HYSTERESIS(CHIP, .dword = 0x00000c00)"
TARGET = "src/freedreno/vulkan/tu_cmd_buffer.cc"

OLD_CHUNK = (
    "   if (CHIP >= A8XX)\n"
    "      tu_cs_emit_regs(cs, SP_ALPHA_TEST_CNTL(CHIP));\n"
)

NEW_CHUNK = (
    "   if (CHIP >= A8XX) {\n"
    "      tu_cs_emit_regs(cs, SP_ALPHA_TEST_CNTL(CHIP));\n"
    "      tu_cs_emit_regs(cs, SP_PS_HYSTERESIS(CHIP, .dword = 0x00000c00));\n"
    "      tu_cs_emit_regs(cs, SP_VS_HYSTERESIS(CHIP, .dword = 0x00000400));\n"
    "      tu_cs_emit_regs(cs, SP_CS_HYSTERESIS(CHIP, .dword = 0x00000400));\n"
    "   }\n"
)


def main():
    try:
        content = open(TARGET, "r", encoding="utf-8").read()
    except OSError as e:
        print(f"{NAME}: WARNING cannot read {TARGET}: {e}; skipped")
        return 0

    if MARKER in content:
        print(f"{NAME}: already applied ({MARKER} present)")
        return 0

    if OLD_CHUNK not in content:
        print(f"{NAME}: ERROR target anchor not found in {TARGET}", file=sys.stderr)
        return 1

    new_content = content.replace(OLD_CHUNK, NEW_CHUNK, 1)
    try:
        open(TARGET, "w", encoding="utf-8").write(new_content)
    except OSError as e:
        print(f"{NAME}: ERROR cannot write {TARGET}: {e}", file=sys.stderr)
        return 1

    print(f"{NAME}: applied successfully (A8xx SP hysteresis initialized)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
