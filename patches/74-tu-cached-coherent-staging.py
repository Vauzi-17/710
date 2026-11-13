#!/usr/bin/env python3
"""Override uncached host-visible allocations with cached-coherent memory.

Under x86 emulation (Winlator, DXVK, vkd3d-proton), staging buffers and host uploads
are frequently allocated with VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT
without VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT.

Upstream Turnip requires VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT in replace_flags_match,
preventing DXVK staging buffers from being promoted to cached memory.

This patch relaxes replace_flags_mask and replace_flags_match in tu_knl.cc to match
any HOST_VISIBLE | HOST_COHERENT allocation lacking HOST_CACHED_BIT, promoting DXVK
staging buffers to cached-coherent memory when preferred_uncached_as_cached_index >= 0.

Additionally, enables tu_override_uncached_as_cache_coherent in 00-turnip-defaults.conf
for the DXVK|vkd3d engine match.

Target: Adreno 7xx / 8xx (a710, a810) under DXVK / vkd3d emulation.
Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = "74-tu-cached-coherent-staging.py"
MARKER = "74-tu-cached-coherent-staging"
KNL_CC = "src/freedreno/vulkan/tu_knl.cc"
DEFAULTS_CONF = "src/freedreno/vulkan/00-turnip-defaults.conf"
DEVICE_CC = "src/freedreno/vulkan/tu_device.cc"

EDITS = [
    (KNL_CC,
     '   const VkMemoryPropertyFlags replace_flags_mask =\n'
     '      VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT |\n'
     '      VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |\n'
     '      VK_MEMORY_PROPERTY_HOST_COHERENT_BIT |\n'
     '      VK_MEMORY_PROPERTY_HOST_CACHED_BIT;\n'
     '\n'
     '   const VkMemoryPropertyFlags replace_flags_match =\n'
     '      VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT |\n'
     '      VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |\n'
     '      VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;\n',
     '   /* 74-tu-cached-coherent-staging: match host-visible coherent without cached bit (including staging buffers) */\n'
     '   const VkMemoryPropertyFlags replace_flags_mask =\n'
     '      VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |\n'
     '      VK_MEMORY_PROPERTY_HOST_COHERENT_BIT |\n'
     '      VK_MEMORY_PROPERTY_HOST_CACHED_BIT;\n'
     '\n'
     '   const VkMemoryPropertyFlags replace_flags_match =\n'
     '      VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |\n'
     '      VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;\n',
     1),
    (DEFAULTS_CONF,
     '        <engine engine_name_match="DXVK|vkd3d">\n'
     '            <!--\n'
     '                DXVK and VKD3D-Proton use customBorderColorWithoutFormat and have most of\n',
     '        <engine engine_name_match="DXVK|vkd3d">\n'
     '            <!-- 74-tu-cached-coherent-staging: override uncached staging allocations to cached -->\n'
     '            <option name="tu_override_uncached_as_cache_coherent" value="true" />\n'
     '            <!--\n'
     '                DXVK and VKD3D-Proton use customBorderColorWithoutFormat and have most of\n',
     1),
    (DEVICE_CC,
     '      if (instance->drirc.misc.override_uncached_as_cache_coherent) {\n'
     '          /* Retain this memory type index to override later. */\n'
     '          device->preferred_uncached_as_cached_index = device->memory.type_count;\n'
     '      }\n',
     '      /* 74-tu-cached-coherent-staging: check drirc option or environment variable override */\n'
     '      if (debug_get_bool_option("tu_override_uncached_as_cache_coherent",\n'
     '              debug_get_bool_option("TU_OVERRIDE_UNCACHED_AS_CACHE_COHERENT",\n'
     '                  instance->drirc.misc.override_uncached_as_cache_coherent))) {\n'
     '          /* Retain this memory type index to override later. */\n'
     '          device->preferred_uncached_as_cached_index = device->memory.type_count;\n'
     '      }\n',
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
        files[path] = files[path].replace(old, new, count)

    for path, s in files.items():
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(s)

    print(f"{NAME}: applied (cached-coherent staging buffer override for DXVK/vkd3d)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
