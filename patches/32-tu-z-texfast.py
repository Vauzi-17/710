#!/usr/bin/env python3
"""Turnip-Z port: cheaper texture sampling.

For samplers without compare, YCbCr conversion or unnormalized coordinates:
anisotropic filtering off, nearest mip filter, LOD bias + TU_Z_LODBIAS/100.

Env TU_Z_TEXFAST (default true) turns it on/off.
Env TU_Z_LODBIAS (default 45, i.e. +0.45) sets the extra bias in 1/100 units.
Lower image quality (blurrier distant textures) for less texture bandwidth.

Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = "32-tu-z-texfast.py"
MARKER = "TU_Z_TEXFAST"
SAMPLER = "src/freedreno/vulkan/tu_sampler.cc"

EDITS = [
    (SAMPLER,
     '#include "tu_util.h"\n',
     '#include "tu_util.h"\n'
     '#include "util/u_debug.h"\n'
     '\n'
     'DEBUG_GET_ONCE_BOOL_OPTION(tu_z_texfast, "TU_Z_TEXFAST", true)\n'
     'DEBUG_GET_ONCE_NUM_OPTION(tu_z_lodbias, "TU_Z_LODBIAS", 45)\n',
     1),
    (SAMPLER,
     '   float max_lod = CLAMP(pCreateInfo->maxLod, 0.0f, 4095.0f / 256.0f);\n',
     '   float max_lod = CLAMP(pCreateInfo->maxLod, 0.0f, 4095.0f / 256.0f);\n'
     '   float lod_bias = pCreateInfo->mipLodBias;\n'
     '\n'
     '   if (debug_get_option_tu_z_texfast() && !pCreateInfo->compareEnable &&\n'
     '       !ycbcr_conversion && !pCreateInfo->unnormalizedCoordinates) {\n'
     '      aniso = 0;\n'
     '      miplinear = false;\n'
     '      lod_bias = CLAMP(lod_bias + debug_get_option_tu_z_lodbias() / 100.0f,\n'
     '                       -16.0f, 15.99f);\n'
     '   }\n',
     1),
    (SAMPLER,
     '_TEX_SAMP_0_LOD_BIAS(pCreateInfo->mipLodBias)',
     '_TEX_SAMP_0_LOD_BIAS(lod_bias)',
     2),
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
    print(f"{NAME}: applied (TU_Z_TEXFAST default on, TU_Z_LODBIAS default 45)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
