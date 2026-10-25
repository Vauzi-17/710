#!/usr/bin/env python3
# From: Vauzi-17
"""A8xx: Emit GRAS_LRZ_COLOR_COMP_MASK (0x810c) in blend dynamic state.

On Adreno 8xx (a810+), the rasterizer LRZ block tracks per-MRT component write
enables through GRAS_LRZ_COLOR_COMP_MASK (0x810c). Emitting this register along
with SP/RB MRT control packets ensures early-Z LRZ culling remains fully coherent
across multi-MRT and disabled color attachment draws.

Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = "48-a8xx-lrz-color-mask.py"
MARKER = "GRAS_LRZ_COLOR_COMP_MASK"
PIPELINE = "src/freedreno/vulkan/tu_pipeline.cc"

EDITS = [
    (PIPELINE,
     '   unsigned num_rts = alpha_to_coverage_enable ?\n'
     '      MAX2(cb->attachment_count, 1) : cb->attachment_count;\n'
     '   return 8 + 5 * num_rts;\n',
     '   unsigned num_rts = alpha_to_coverage_enable ?\n'
     '      MAX2(cb->attachment_count, 1) : cb->attachment_count;\n'
     '   return 8 + (CHIP >= A8XX ? 2 : 0) + 5 * num_rts;\n',
     1),
    (PIPELINE,
     '   unsigned num_remapped_rts = 0;\n'
     '   for (unsigned i = 0; i < num_rts; i++) {\n',
     '   unsigned num_remapped_rts = 0;\n'
     '   uint32_t lrz_color_comp_mask = 0;\n'
     '   for (unsigned i = 0; i < num_rts; i++) {\n',
     1),
    (PIPELINE,
     '      if ((cb->color_write_enables & (1u << i)) && i < cb->attachment_count) {\n',
     '      if ((cb->color_write_enables & (1u << i)) && i < cb->attachment_count) {\n'
     '         if (CHIP >= A8XX && remapped_idx < 8)\n'
     '            lrz_color_comp_mask |= (att->write_mask & 0xf) << (remapped_idx * 4);\n',
     1),
    (PIPELINE,
     '   tu_cs_emit_regs(cs, A6XX_SP_PS_MRT_CNTL(.mrt = num_remapped_rts));\n'
     '   tu_cs_emit_regs(cs, A6XX_RB_PS_MRT_CNTL(.mrt = num_remapped_rts));\n'
     '}\n',
     '   tu_cs_emit_regs(cs, A6XX_SP_PS_MRT_CNTL(.mrt = num_remapped_rts));\n'
     '   tu_cs_emit_regs(cs, A6XX_RB_PS_MRT_CNTL(.mrt = num_remapped_rts));\n'
     '   if (CHIP >= A8XX) {\n'
     '      tu_cs_emit_regs(cs, GRAS_LRZ_COLOR_COMP_MASK(CHIP, .dword = lrz_color_comp_mask));\n'
     '   }\n'
     '}\n',
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
        files[path] = files[path].replace(old, new)

    for path, s in files.items():
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(s)

    print(f"{NAME}: applied (A8xx GRAS_LRZ_COLOR_COMP_MASK emitted in blend state)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
