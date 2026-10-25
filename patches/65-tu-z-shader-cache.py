#!/usr/bin/env python3
"""Turnip-Z port: automatic persistent disk shader cache for Android emulators.

On Android, $XDG_CACHE_HOME and $HOME are not configured for application processes,
causing Mesa's disk cache initialization to fail or fall back to memory-only cache.
This causes shader compilation stuttering on every gameplay launch.

Turnip-Z v0.3.0 detects the application package name via /proc/self/cmdline
(falling back to 'dev.eden.eden_emulator') and redirects the shader cache to:
/data/data/<package>/cache/mesa_shader_cache

Env TU_SHADER_CACHE_AUTO (default true):
  true   auto-detect package and configure on-disk shader cache on Android
  false  rely on default Mesa environment variables

Target: Android / Eden emulator on Adreno GPUs.
Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = "65-tu-z-shader-cache.py"
MARKER = "TU_SHADER_CACHE_AUTO"
TARGET = "src/freedreno/vulkan/tu_device.cc"

HELPER = '''DEBUG_GET_ONCE_BOOL_OPTION(tu_shader_cache_auto, "TU_SHADER_CACHE_AUTO", true)

#if DETECT_OS_ANDROID
static void
tu_init_android_shader_cache_dir(void)
{
   if (!debug_get_option_tu_shader_cache_auto())
      return;

   if (getenv("MESA_SHADER_CACHE_DIR") || getenv("MESA_GLSL_CACHE_DIR"))
      return;

   char pkg[128] = {0};
   FILE *f = fopen("/proc/self/cmdline", "r");
   if (f) {
      if (fgets(pkg, sizeof(pkg), f)) {
         char *colon = strchr(pkg, ':');
         if (colon)
            *colon = '\\0';
      }
      fclose(f);
   }
   if (pkg[0] == '\\0')
      snprintf(pkg, sizeof(pkg), "dev.eden.eden_emulator");

   char cache_dir[256];
   snprintf(cache_dir, sizeof(cache_dir), "/data/data/%s/cache", pkg);
   setenv("MESA_SHADER_CACHE_DIR", cache_dir, 0);
}
#endif

'''

EDITS = [
    (TARGET,
     'VkResult\n'
     'tu_physical_device_init(struct tu_physical_device *device,\n'
     '                        struct tu_instance *instance)\n',
     HELPER +
     'VkResult\n'
     'tu_physical_device_init(struct tu_physical_device *device,\n'
     '                        struct tu_instance *instance)\n',
     1),
    (TARGET,
     '   char buf[VK_UUID_SIZE * 2 + 1];\n'
     '   mesa_bytes_to_hex(buf, device->cache_uuid, VK_UUID_SIZE);\n'
     '   device->vk.disk_cache = disk_cache_create(device->name, buf, 0);\n',
     '#if DETECT_OS_ANDROID\n'
     '   tu_init_android_shader_cache_dir();\n'
     '#endif\n'
     '   char buf[VK_UUID_SIZE * 2 + 1];\n'
     '   mesa_bytes_to_hex(buf, device->cache_uuid, VK_UUID_SIZE);\n'
     '   device->vk.disk_cache = disk_cache_create(device->name, buf, 0);\n',
     1),
]


def main():
    files = {}
    for path, _, _, _ in EDITS:
        if path not in files:
            try:
                files[path] = open(path, "r", encoding="utf-8").read()
            except OSError as e:
                print(f"{NAME}: WARNING cannot read {path}: {e}; skipped")
                return 0

    if any(MARKER in s for s in files.values()):
        print(f"{NAME}: already applied ({MARKER} present)")
        return 0

    for path, old, new, count in EDITS:
        found = files[path].count(old)
        if found != count:
            print(f"{NAME}: WARNING anchor matched {found}x (want {count}) in {path}; "
                  f"upstream changed, patch skipped", file=sys.stderr)
            return 1
        files[path] = files[path].replace(old, new, count)

    for path, s in files.items():
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(s)

    print(f"{NAME}: applied successfully (TU_SHADER_CACHE_AUTO default on)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
