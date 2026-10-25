#!/usr/bin/env python3
"""Built-in default environment variables for Turnip with app override support.

Reads default_env.conf (next to this script) and adds a constructor to
src/freedreno/vulkan/tu_util.cc that runs when libvulkan_freedreno.so is
loaded.

Priority order:
  1. Custom configuration file from application storage:
     - $TU_ENV_CONFIG (if set)
     - /sdcard/Android/data/<package>/files/default_env.conf
     - /data/data/<package>/files/default_env.conf
     - /sdcard/default_env.conf
  2. The real environment (emulator / launcher setting)
  3. Android property debug.mesa.* / vendor.mesa.*
  4. The built-in defaults from default_env.conf

Run from the Mesa source root.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(HERE, "default_env.conf")
TARGET = "src/freedreno/vulkan/tu_util.cc"
MARKER = "tu_apply_default_env"

entries = []
if os.path.exists(CONF):
    for lineno, raw in enumerate(open(CONF, encoding="utf-8"), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            sys.exit(f"20-default-env.py: {CONF}:{lineno}: expected NAME=VALUE")
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            sys.exit(f"20-default-env.py: {CONF}:{lineno}: bad variable name '{name}'")
        entries.append((name, value))

src = open(TARGET).read()
if MARKER in src:
    print("20-default-env.py: already applied")
    sys.exit(0)


def c_string(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


if entries:
    table = "\n".join(f"   {{ {c_string(n)}, {c_string(v)} }}," for n, v in entries)
else:
    table = "   { NULL, NULL },"


code = f"""

/* Built-in default environment (patches/default_env.conf) with app override support.
 * Runs when the driver is loaded into the process.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include "util/log.h"
#include "util/os_misc.h"

static const struct {{
   const char *name;
   const char *value;
}} tu_default_env[] = {{
{table}
}};

static void
tu_load_env_file(const char *path)
{{
   FILE *f = fopen(path, "r");
   if (!f)
      return;

   char line[512];
   while (fgets(line, sizeof(line), f)) {{
      char *p = line;
      while (*p == ' ' || *p == '\\t')
         p++;
      if (*p == '#' || *p == '\\0' || *p == '\\r' || *p == '\\n')
         continue;

      char *eq = strchr(p, '=');
      if (!eq)
         continue;

      *eq = '\\0';
      char *key = p;
      char *val = eq + 1;

      /* Trim trailing whitespace from key */
      char *end = eq - 1;
      while (end > key && (*end == ' ' || *end == '\\t')) {{
         *end = '\\0';
         end--;
      }}

      /* Trim leading whitespace from val */
      while (*val == ' ' || *val == '\\t')
         val++;

      /* Trim trailing \\r, \\n, and whitespace from val */
      end = val + strlen(val) - 1;
      while (end >= val && (*end == '\\r' || *end == '\\n' || *end == ' ' || *end == '\\t')) {{
         *end = '\\0';
         end--;
      }}

      if (*key != '\\0') {{
         setenv(key, val, 1);
         mesa_logi("custom env override (%s): %s=%s", path, key, val);
      }}
   }}
   fclose(f);
}}

static void
tu_load_app_custom_env(void)
{{
   const char *custom_path = getenv("TU_ENV_CONFIG");
   if (custom_path && custom_path[0])
      tu_load_env_file(custom_path);

   char pkg[128] = {{0}};
   FILE *f = fopen("/proc/self/cmdline", "r");
   if (f) {{
      if (fgets(pkg, sizeof(pkg), f)) {{
         char *colon = strchr(pkg, ':');
         if (colon)
            *colon = '\\0';
      }}
      fclose(f);
   }}

   char path[256];
   if (pkg[0]) {{
      snprintf(path, sizeof(path), "/sdcard/Android/data/%s/files/default_env.conf", pkg);
      tu_load_env_file(path);

      snprintf(path, sizeof(path), "/data/data/%s/files/default_env.conf", pkg);
      tu_load_env_file(path);
   }}

   tu_load_env_file("/sdcard/default_env.conf");
}}

__attribute__((constructor)) static void
{MARKER}(void)
{{
   for (unsigned i = 0; i < sizeof(tu_default_env) / sizeof(tu_default_env[0]); i++) {{
      if (!tu_default_env[i].name || os_get_option(tu_default_env[i].name))
         continue;
      if (setenv(tu_default_env[i].name, tu_default_env[i].value, 0) == 0)
         mesa_logi("default env: %s=%s", tu_default_env[i].name,
                   tu_default_env[i].value);
   }}

   tu_load_app_custom_env();
}}
"""

open(TARGET, "a").write(code)
for n, v in entries:
    print(f"20-default-env.py: default {n}={v}")
