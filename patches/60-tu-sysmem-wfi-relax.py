#!/usr/bin/env python3
"""Relax subpass slice wait from WFI to WAIT_FOR_ME in sysmem mode.

In sysmem mode, upstream Turnip emits a full WFI (Wait For Idle) pipeline drain
on subpass slice waits. WFI stalls the command processor until all active shader
waves finish execution. In sysmem rendering, CP_WAIT_FOR_ME is sufficient to ensure
command stream synchronization without stalling shader execution units.

Env TU_SYSMEM_RELAX_WFI (default true):
  true   emit CP_WAIT_FOR_ME on subpass slice wait in sysmem mode
  false  emit tu_cs_emit_wfi (upstream behavior)

Target: Adreno 7xx / a710 sysmem pipeline.
Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = "60-tu-sysmem-wfi-relax.py"
MARKER = "TU_SYSMEM_RELAX_WFI"
CMD_BUFFER = "src/freedreno/vulkan/tu_cmd_buffer.cc"

EDITS = [
    (CMD_BUFFER,
     '#include "tu_trace_bin_layout.h"\n',
     '#include "tu_trace_bin_layout.h"\n'
     '\n'
     '#include "util/u_debug.h"\n'
     '\n'
     'DEBUG_GET_ONCE_BOOL_OPTION(tu_sysmem_relax_wfi, "TU_SYSMEM_RELAX_WFI", true)\n',
     1),
    (CMD_BUFFER,
     '      if (emit_subpass_slice_wait)\n'
     '         tu_cs_emit_wfi(cs);\n',
     '      if (emit_subpass_slice_wait) {\n'
     '         if (debug_get_option_tu_sysmem_relax_wfi())\n'
     '            tu_cs_emit_pkt7(cs, CP_WAIT_FOR_ME, 0);\n'
     '         else\n'
     '            tu_cs_emit_wfi(cs);\n'
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
        files[path] = files[path].replace(old, new)
    for path, s in files.items():
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(s)
    print(f"{NAME}: applied (TU_SYSMEM_RELAX_WFI, default true)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
