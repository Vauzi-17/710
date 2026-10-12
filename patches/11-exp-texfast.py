#!/usr/bin/env python3
"""Experiment: cheaper texture filtering (idea from turnip-sd865-z, change 2).

For every sampler: anisotropic filtering off, mipmapMode LINEAR becomes
NEAREST (trilinear -> bilinear), and +0.5 added to the LOD bias. Distant and
steeply angled textures get slightly blurrier; texture fetches and memory
bandwidth go down.

On by default. TU_TEXFAST=0 (or debug.mesa.tu_texfast=0) turns it off.

Run from the Mesa source root.
"""
import sys

PATH = "src/freedreno/vulkan/tu_sampler.cc"
src = open(PATH).read()

if "tu_texfast" in src:
    print("11-exp-texfast.py: already applied")
    sys.exit(0)

def replace_once(old, new, what):
    global src
    if src.count(old) != 1:
        sys.exit(f"11-exp-texfast.py: {what} not found ({src.count(old)} matches)")
    src = src.replace(old, new, 1)

replace_once('#include "tu_util.h"\n',
             '#include "tu_util.h"\n#include "util/u_debug.h"\n\n'
             'DEBUG_GET_ONCE_BOOL_OPTION(tu_texfast, "TU_TEXFAST", true)\n',
             "tu_util.h include")

replace_once("""   unsigned aniso = pCreateInfo->anisotropyEnable ?
      util_last_bit(MIN2((uint32_t)pCreateInfo->maxAnisotropy >> 1, 8)) : 0;
   bool miplinear = (pCreateInfo->mipmapMode == VK_SAMPLER_MIPMAP_MODE_LINEAR);""",
"""   /* Experiment: no anisotropy, bilinear instead of trilinear, +0.5 LOD
    * bias. TU_TEXFAST=0 restores the requested filtering.
    */
   const bool texfast = debug_get_option_tu_texfast();
   const float lod_bias = pCreateInfo->mipLodBias + (texfast ? 0.5f : 0.0f);
   unsigned aniso = (pCreateInfo->anisotropyEnable && !texfast) ?
      util_last_bit(MIN2((uint32_t)pCreateInfo->maxAnisotropy >> 1, 8)) : 0;
   bool miplinear = (pCreateInfo->mipmapMode == VK_SAMPLER_MIPMAP_MODE_LINEAR) &&
                    !texfast;""", "aniso/miplinear setup")

replace_once("A8XX_TEX_SAMP_0_LOD_BIAS(pCreateInfo->mipLodBias)",
             "A8XX_TEX_SAMP_0_LOD_BIAS(lod_bias)", "A8XX LOD bias")
replace_once("A6XX_TEX_SAMP_0_LOD_BIAS(pCreateInfo->mipLodBias)",
             "A6XX_TEX_SAMP_0_LOD_BIAS(lod_bias)", "A6XX LOD bias")

open(PATH, "w").write(src)
print("11-exp-texfast.py: cheap filtering on (TU_TEXFAST=0 to disable)")
