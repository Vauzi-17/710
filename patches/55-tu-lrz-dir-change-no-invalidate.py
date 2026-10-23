#!/usr/bin/env python3
"""Preserve LRZ state across draws on depth compare-op direction change.

Upstream Turnip permanently invalidates LRZ for the remaining render pass when
a draw writes depth with a compare-op direction different from the previous draw
("Depth write + compare-op direction change"). This drops early-Z testing for all
subsequent geometry in the pass, which severely penalizes Switch emulation (Eden)
where scenes commonly intermix depth operations (e.g. background/skybox vs character models).

On GPUs with hardware direction tracking (A7xx/A8xx), the hardware can track direction
changes per-draw without needing driver software to kill LRZ for the rest of the pass.
With TU_LRZ_PRESERVE_DIR_CHANGE (default true), this patch skips LRZ for the conflicting
draw only, updates the tracked direction, and preserves early-Z culling for all subsequent
draws conforming to the new direction.

Run from Mesa source root. Idempotent and safe to run multiple times.
"""
import sys

NAME = "55-tu-lrz-dir-change-no-invalidate.py"
MARKER = "TU_LRZ_PRESERVE_DIR_CHANGE"
TARGET = "src/freedreno/vulkan/tu_lrz.cc"

OLD_CHUNK = (
    "   if (cmd->state.lrz.prev_direction != TU_LRZ_UNKNOWN &&\n"
    "       lrz_direction != TU_LRZ_UNKNOWN &&\n"
    "       cmd->state.lrz.prev_direction != lrz_direction) {\n"
    "      if (z_write_enable) {\n"
    "         tu_lrz_invalidate(cmd, \"Depth write + compare-op direction change\");\n"
    "      } else {\n"
    "         perf_debug(cmd->device, \"Skipping LRZ due to direction change\");\n"
    "         temporary_disable_lrz = true;\n"
    "      }\n"
    "   }\n"
)

NEW_CHUNK = (
    "   if (cmd->state.lrz.prev_direction != TU_LRZ_UNKNOWN &&\n"
    "       lrz_direction != TU_LRZ_UNKNOWN &&\n"
    "       cmd->state.lrz.prev_direction != lrz_direction) {\n"
    "      static int preserve_dir = -1;\n"
    "      if (preserve_dir < 0)\n"
    "         preserve_dir = debug_get_bool_option(\"TU_LRZ_PRESERVE_DIR_CHANGE\", true);\n"
    "      if (preserve_dir && cmd->state.lrz.gpu_dir_tracking) {\n"
    "         perf_debug(cmd->device, \"Skipping LRZ for direction change draw only\");\n"
    "         temporary_disable_lrz = true;\n"
    "         if (z_write_enable)\n"
    "            cmd->state.lrz.prev_direction = lrz_direction;\n"
    "      } else if (z_write_enable) {\n"
    "         tu_lrz_invalidate(cmd, \"Depth write + compare-op direction change\");\n"
    "      } else {\n"
    "         perf_debug(cmd->device, \"Skipping LRZ due to direction change\");\n"
    "         temporary_disable_lrz = true;\n"
    "      }\n"
    "   }\n"
)


def main():
    try:
        content = open(TARGET, "r", encoding="utf-8").read()
    except OSError as e:
        print(f"{NAME}: WARNING cannot read {TARGET}: {e}; skipped")
        return 0

    if MARKER in content:
        print(f"{NAME}: already applied ({MARKER} present)")
        return 0

    if OLD_CHUNK not in content:
        print(f"{NAME}: ERROR target anchor not found in {TARGET}", file=sys.stderr)
        return 1

    new_content = content.replace(OLD_CHUNK, NEW_CHUNK, 1)
    try:
        open(TARGET, "w", encoding="utf-8").write(new_content)
    except OSError as e:
        print(f"{NAME}: ERROR cannot write {TARGET}: {e}", file=sys.stderr)
        return 1

    print(f"{NAME}: applied successfully (LRZ preserved on direction change)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
