#!/usr/bin/env python3
"""Built-in default environment variables for Turnip.

Reads default_env.conf (next to this script) and adds a constructor to
src/freedreno/vulkan/tu_util.cc that runs when libvulkan_freedreno.so is
loaded. For each NAME=VALUE it calls setenv() only if os_get_option(NAME)
finds nothing, so the priority is:

  1. the real environment (emulator / launcher setting)
  2. Android property debug.mesa.* / vendor.mesa.*
  3. the default from default_env.conf

The constructor runs before the driver reads any option (TU_DEBUG is parsed
when the instance is created, IR3_SHADER_DEBUG when the compiler is), so the
defaults behave exactly like variables set by the app.

Note: setenv() changes the environment of the whole process, so other code
in the same process that reads the same names sees them too.

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

if not entries:
    print("20-default-env.py: default_env.conf has no entries, nothing to do")
    sys.exit(0)

src = open(TARGET).read()
if MARKER in src:
    print("20-default-env.py: already applied")
    sys.exit(0)


def c_string(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


table = "\n".join(f"   {{ {c_string(n)}, {c_string(v)} }}," for n, v in entries)
code = f"""

/* Built-in default environment (patches/default_env.conf). Runs when the
 * driver is loaded; a variable already set in the environment or as a
 * debug.mesa.* property is left alone.
 */
#include <stdlib.h>
#include "util/log.h"
#include "util/os_misc.h"

static const struct {{
   const char *name;
   const char *value;
}} tu_default_env[] = {{
{table}
}};

__attribute__((constructor)) static void
{MARKER}(void)
{{
   for (unsigned i = 0; i < sizeof(tu_default_env) / sizeof(tu_default_env[0]); i++) {{
      if (os_get_option(tu_default_env[i].name))
         continue;
      if (setenv(tu_default_env[i].name, tu_default_env[i].value, 0) == 0)
         mesa_logi("default env: %s=%s", tu_default_env[i].name,
                   tu_default_env[i].value);
   }}
}}
"""

open(TARGET, "a").write(code)
for n, v in entries:
    print(f"20-default-env.py: default {n}={v}")
