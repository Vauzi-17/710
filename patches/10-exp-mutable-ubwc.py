#!/usr/bin/env python3
"""Experiment: keep UBWC on MUTABLE_FORMAT images (idea from turnip-sd865-z,
change 1 "Compressed mutable images").

Upstream only keeps UBWC on mutable images when the GPU has
ubwc_all_formats_compatible (A7xx gen3, A750 and up) or the format list is
known to be compatible. The Adreno 710/720/722 are A7xx gen1, so DXVK and
emulator render targets created with MUTABLE_FORMAT lose compression.

This keeps UBWC on those images unless the view-format list names a format
that cannot use UBWC. The tiling decision is untouched (images whose views
swap components or reinterpret R8G8 as R16 still go linear), and is_mutable
is NOT set: that flag is only valid on gen3, where CCU and TP agree on swaps
for tiled images.

Risk: a view in a UBWC-incompatible format (e.g. UNORM data read as SNORM)
reads wrong values. TU_MUTABLE_UBWC=0 (or debug.mesa.tu_mutable_ubwc=0)
restores upstream behaviour.

Run from the Mesa source root.
"""
import sys

PATH = "src/freedreno/vulkan/tu_image.cc"
src = open(PATH).read()

if "tu_mutable_ubwc_forced" in src:
    print("10-exp-mutable-ubwc.py: already applied")
    sys.exit(0)

helper_anchor = "template <chip CHIP>\nVkResult\ntu_image_init("
helper = '''DEBUG_GET_ONCE_BOOL_OPTION(tu_mutable_ubwc, "TU_MUTABLE_UBWC", true)

/* Experiment: keep UBWC on a mutable image on GPUs without
 * ubwc_all_formats_compatible, as long as every listed view format can use
 * UBWC. With no format list the base format decides alone.
 */
static bool
tu_mutable_ubwc_forced(struct tu_device *dev,
                       const VkImageFormatListCreateInfo *fmt_list,
                       const VkImageCreateInfo *create_info)
{
   if (!debug_get_option_tu_mutable_ubwc())
      return false;

   if (!fmt_list || !fmt_list->viewFormatCount)
      return true;

   return format_list_ubwc_possible(dev, fmt_list, create_info);
}

'''
if src.count(helper_anchor) != 1:
    sys.exit("10-exp-mutable-ubwc.py: tu_image_init anchor not found")
src = src.replace(helper_anchor, helper + helper_anchor, 1)

site_old = """         } else if (!mutable_ubwc_fc) {
            if (ubwc_enabled) {"""
site_new = """         } else if (!mutable_ubwc_fc) {
            if (ubwc_enabled &&
                !tu_mutable_ubwc_forced(device, fmt_list, pCreateInfo)) {"""
if src.count(site_old) != 1:
    sys.exit("10-exp-mutable-ubwc.py: mutable UBWC branch not found")
src = src.replace(site_old, site_new, 1)

open(PATH, "w").write(src)
print("10-exp-mutable-ubwc.py: UBWC kept on mutable images (TU_MUTABLE_UBWC=0 to disable)")
