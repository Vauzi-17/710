#!/usr/bin/env python3
"""Prioritize instructions with lower live register effect during pressure growth.

In choose_instr_inc, when all available ready instructions increase register
pressure, upstream Turnip breaks ties purely on instruction distance to nearest
use. This causes large register consumers (such as vec4 operations) to be
scheduled early, creating register pressure spikes that exceed Adreno 710 GPR
occupancy limits (48/64 GPRs).

This patch checks live_effect(n->instr) when comparing candidates in
choose_instr_inc, choosing instructions with smaller register increases before
falling back to the nearest-use tiebreaker.

Env TU_IR3_SCHED_LOWER_LIVE (default true):
  true   prefer candidates with lower live_effect during pressure increase
  false  rank purely by nearest_use (upstream behavior)

Target: Adreno 7xx / a710 wave occupancy and GPR allocation.
Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = "63-ir3-sched-prefer-lower-live.py"
MARKER = "TU_IR3_SCHED_LOWER_LIVE"
IR3_SCHED = "src/freedreno/ir3/ir3_sched.c"

EDITS = [
    (IR3_SCHED,
     '   unsigned chosen_distance = 0;\n'
     '\n'
     '   /* Pick the max delay of the remaining ready set. */\n',
     '   unsigned chosen_distance = 0;\n'
     '   int chosen_live = 0;\n'
     '\n'
     '   /* Pick the max delay of the remaining ready set. */\n',
     1),
    (IR3_SCHED,
     '      unsigned distance = nearest_use(n->instr);\n'
     '\n'
     '      if (!chosen || rank > chosen_rank ||\n'
     '          (rank == chosen_rank && distance < chosen_distance)) {\n'
     '         chosen = n;\n'
     '         chosen_distance = distance;\n'
     '         chosen_rank = rank;\n'
     '      }\n',
     '      unsigned distance = nearest_use(n->instr);\n'
     '      int live = live_effect(n->instr);\n'
     '\n'
     '      static int prefer_lower_live = -1;\n'
     '      if (prefer_lower_live < 0)\n'
     '         prefer_lower_live = debug_get_bool_option("TU_IR3_SCHED_LOWER_LIVE", true);\n'
     '\n'
     '      bool better = !chosen || rank > chosen_rank;\n'
     '      if (!better && rank == chosen_rank) {\n'
     '         if (prefer_lower_live) {\n'
     '            if (live < chosen_live)\n'
     '               better = true;\n'
     '            else if (live == chosen_live && distance < chosen_distance)\n'
     '               better = true;\n'
     '         } else {\n'
     '            if (distance < chosen_distance)\n'
     '               better = true;\n'
     '         }\n'
     '      }\n'
     '\n'
     '      if (better) {\n'
     '         chosen = n;\n'
     '         chosen_distance = distance;\n'
     '         chosen_rank = rank;\n'
     '         chosen_live = live;\n'
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
    print(f"{NAME}: applied (TU_IR3_SCHED_LOWER_LIVE, default true)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
