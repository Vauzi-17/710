#!/usr/bin/env python3
"""tu: TU_OVERRIDE_HEAP_SIZE sets the Vulkan heap size in MiB.

Winlator sets this variable from the container's video memory setting.
Ported from brunodev85/mesa3d-custom. Run from the Mesa source root.
"""
import sys
from pathlib import Path

PATH = Path("src/freedreno/vulkan/tu_device.cc")
ANCHOR = "tu_get_system_heap_size(struct tu_physical_device *physical_device)\n{\n"
CODE = """   /* Winlator: heap size in MiB, from the container's video memory setting. */
   const char *override_heap_size = getenv("TU_OVERRIDE_HEAP_SIZE");
   if (override_heap_size)
      return (uint64_t) strtoull(override_heap_size, NULL, 10) << 20;

"""

text = PATH.read_text()
if "TU_OVERRIDE_HEAP_SIZE" in text:
    print(f"{PATH}: TU_OVERRIDE_HEAP_SIZE already present")
elif text.count(ANCHOR) != 1:
    sys.exit(f"{PATH}: tu_get_system_heap_size() not found, upstream changed it")
else:
    PATH.write_text(text.replace(ANCHOR, ANCHOR + CODE, 1))
    print(f"{PATH}: added TU_OVERRIDE_HEAP_SIZE")
