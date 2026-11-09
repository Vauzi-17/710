#!/usr/bin/env python3
"""Gate per-sample shading escalation unless fragment shader statically uses it.

vkd3d-proton sets sampleShadingEnable for an entire pipeline when any stage
declares the SampleRateShading capability in SPIR-V, even if the fragment shader
does not consume per-sample inputs or interpolate at sample frequency.

Upstream Turnip unconditionally forces uses_sample_shading = true and marks all
non-centroid inputs as sample whenever key->force_sample_interp is set, causing
severe rasterization bottlenecks and redundant multi-sample fragment evaluations.

This patch ensures sample shading and per-sample variable interpolation are only
escalated when nir->info.fs.uses_sample_shading is already statically true in the shader.

Env TU_SAMPLE_SHADING_GATE (default true):
  true   gate sample interpolation to shaders statically consuming sample inputs
  false  unconditionally force sample interpolation on pipeline flag (upstream behavior)

Target: Adreno 7xx / 8xx (a710, a810) under Winlator + vkd3d-proton / DXVK.
Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = "75-tu-sample-shading-gate.py"
MARKER = "TU_SAMPLE_SHADING_GATE"
SHADER_CC = "src/freedreno/vulkan/tu_shader.cc"

EDITS = [
    (SHADER_CC,
     '#include "tu_subsampled_image.h"\n',
     '#include "tu_subsampled_image.h"\n'
     '\n'
     '#include "util/u_debug.h"\n'
     '\n'
     'DEBUG_GET_ONCE_BOOL_OPTION(tu_sample_shading_gate, "TU_SAMPLE_SHADING_GATE", true)\n',
     1),
    (SHADER_CC,
     '   if (nir->info.stage == MESA_SHADER_FRAGMENT && key->force_sample_interp) {\n'
     '      nir->info.fs.uses_sample_shading = true;\n'
     '      nir_foreach_shader_in_variable(var, nir) {\n'
     '         if (!var->data.centroid)\n'
     '            var->data.sample = true;\n'
     '      }\n'
     '   }\n',
     '   if (nir->info.stage == MESA_SHADER_FRAGMENT && key->force_sample_interp &&\n'
     '       (!debug_get_option_tu_sample_shading_gate() ||\n'
     '        nir->info.fs.uses_sample_shading)) {\n'
     '      nir->info.fs.uses_sample_shading = true;\n'
     '      nir_foreach_shader_in_variable(var, nir) {\n'
     '         if (!var->data.centroid)\n'
     '            var->data.sample = true;\n'
     '      }\n'
     '   }\n',
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

    print(f"{NAME}: applied (TU_SAMPLE_SHADING_GATE, default true)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
