#!/usr/bin/env python3
# From: Vauzi-17
"""Built-in default environment variables for Turnip with app override support.

Reads default_env.conf (next to this script) and adds a constructor to
src/freedreno/vulkan/tu_util.cc that runs when libvulkan_freedreno.so is
loaded.

Priority order:
  1. Custom configuration file from application storage:
     - $TU_ENV_CONFIG (if set)
     - /storage/emulated/0/Android/data/<package>/files/default_env.conf
     - /sdcard/Android/data/<package>/files/default_env.conf
     - /data/data/<package>/files/default_env.conf
     - /storage/emulated/0/default_env.conf
     - /sdcard/default_env.conf
  2. The real environment (emulator / launcher setting)
  3. Android property debug.mesa.* / vendor.mesa.*
  4. The built-in defaults from default_env.conf

Also outputs a status log to turnip_env.log in the application files directory.

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
#include <stdarg.h>
#include <stdbool.h>
#include "util/log.h"
#include "util/os_misc.h"

static const struct {{
   const char *name;
   const char *value;
}} tu_default_env[] = {{
{table}
}};

static FILE *g_tu_env_log = NULL;

static void
tu_log_env(const char *fmt, ...)
{{
   if (!g_tu_env_log)
      return;
   va_list args;
   va_start(args, fmt);
   vfprintf(g_tu_env_log, fmt, args);
   va_end(args);
   fflush(g_tu_env_log);
}}

static bool
tu_load_env_file(const char *path)
{{
   FILE *f = fopen(path, "r");
   if (!f)
      return false;

   tu_log_env("Loading configuration from: %s\\n", path);
   mesa_logi("Loading custom env from: %s", path);

   char line[512];
   int count = 0;
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
         tu_log_env("  [override] %s=%s\\n", key, val);
         mesa_logi("custom env override (%s): %s=%s", path, key, val);
         count++;
      }}
   }}
   fclose(f);
   tu_log_env("Successfully applied %d variable(s) from %s\\n", count, path);
   return true;
}}

static void
tu_load_app_custom_env(void)
{{
   char pkg[128] = {{0}};
   FILE *f = fopen("/proc/self/cmdline", "r");
   if (f) {{
      size_t n = fread(pkg, 1, sizeof(pkg) - 1, f);
      fclose(f);
      if (n > 0) {{
         pkg[n] = '\\0';
         char *colon = strchr(pkg, ':');
         if (colon)
            *colon = '\\0';
      }}
   }}

   /* Create turnip_env.log in the application's files directory */
   char log_path[256];
   if (pkg[0]) {{
      snprintf(log_path, sizeof(log_path), "/storage/emulated/0/Android/data/%s/files/turnip_env.log", pkg);
      g_tu_env_log = fopen(log_path, "w");
      if (!g_tu_env_log) {{
         snprintf(log_path, sizeof(log_path), "/sdcard/Android/data/%s/files/turnip_env.log", pkg);
         g_tu_env_log = fopen(log_path, "w");
      }}
      if (!g_tu_env_log) {{
         snprintf(log_path, sizeof(log_path), "/data/data/%s/files/turnip_env.log", pkg);
         g_tu_env_log = fopen(log_path, "w");
      }}
   }}

   tu_log_env("=== Turnip Environment Initialization ===\\n");
   tu_log_env("Process / Package name: '%s'\\n", pkg[0] ? pkg : "(unknown)");

   bool loaded = false;
   const char *custom_path = getenv("TU_ENV_CONFIG");
   if (custom_path && custom_path[0]) {{
      loaded = tu_load_env_file(custom_path);
   }}

   const char *candidate_pkgs[] = {{
      pkg[0] ? pkg : NULL,
      "com.antutu.benchmark.full",
      "org.yuzu.yuzu_emu",
      "dev.eden.eden_emu",
      "com.winlator",
   }};

   char path[256];
   for (unsigned i = 0; !loaded && i < sizeof(candidate_pkgs) / sizeof(candidate_pkgs[0]); i++) {{
      const char *p = candidate_pkgs[i];
      if (!p || (i > 0 && pkg[0] && strcmp(p, pkg) == 0))
         continue;

      /* 1. Canonical Android external storage */
      snprintf(path, sizeof(path), "/storage/emulated/0/Android/data/%s/files/default_env.conf", p);
      if (tu_load_env_file(path)) {{
         loaded = true;
         break;
      }}

      /* 2. Standard /sdcard path */
      snprintf(path, sizeof(path), "/sdcard/Android/data/%s/files/default_env.conf", p);
      if (tu_load_env_file(path)) {{
         loaded = true;
         break;
      }}

      /* 3. Internal app data path */
      snprintf(path, sizeof(path), "/data/data/%s/files/default_env.conf", p);
      if (tu_load_env_file(path)) {{
         loaded = true;
         break;
      }}
   }}

   if (!loaded) {{
      if (tu_load_env_file("/storage/emulated/0/default_env.conf"))
         loaded = true;
      else if (tu_load_env_file("/sdcard/default_env.conf"))
         loaded = true;
   }}

   if (!loaded) {{
      tu_log_env("Notice: No default_env.conf found in search paths. Using built-in driver defaults.\\n");
   }}
}}

__attribute__((constructor)) static void
tu_apply_default_env(void)
{{
   tu_load_app_custom_env();

   for (unsigned i = 0; i < sizeof(tu_default_env) / sizeof(tu_default_env[0]); i++) {{
      if (!tu_default_env[i].name || os_get_option(tu_default_env[i].name))
         continue;
      if (setenv(tu_default_env[i].name, tu_default_env[i].value, 0) == 0) {{
         tu_log_env("  [built-in] %s=%s\\n", tu_default_env[i].name, tu_default_env[i].value);
         mesa_logi("default env: %s=%s", tu_default_env[i].name,
                   tu_default_env[i].value);
      }}
   }}

   tu_log_env("=========================================\\n");
   if (g_tu_env_log) {{
      fclose(g_tu_env_log);
      g_tu_env_log = NULL;
   }}
}}
"""

open(TARGET, "a").write(code)
for n, v in entries:
    print(f"20-default-env.py: default {n}={v}")
