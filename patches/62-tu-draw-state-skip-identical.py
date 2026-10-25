#!/usr/bin/env python3
# From: Vauzi-17
"""Avoid redundant dynamic draw state packet emission.

When dynamic state dirty bits are set (e.g. on pipeline binds or repetitive
vkCmdSet* calls with identical arguments), upstream Turnip re-emits draw
state packets and marks dirty_draw_states |= (1u << id). This forces sub_cs
allocation and emits CP_SET_DRAW_STATE packets even when register contents are
unchanged.

This patch compares the newly emitted dwords against the active state IB in
the command buffer. If identical, sub_cs allocation is rewound and re-emission
via CP_SET_DRAW_STATE is skipped, keeping the previously active state bound.

Env TU_DRAW_STATE_SKIP_IDENTICAL (default true):
  true   skip CP_SET_DRAW_STATE when emitted state words are identical
  false  always re-emit dynamic draw states (upstream behavior)

Target: Adreno 7xx / a710 CP command parser.
Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = "62-tu-draw-state-skip-identical.py"
MARKER = "TU_DRAW_STATE_SKIP_IDENTICAL"
CMD_H = "src/freedreno/vulkan/tu_cmd_buffer.h"
PIPELINE_CC = "src/freedreno/vulkan/tu_pipeline.cc"

EDITS = [
    (CMD_H,
     '   /* saved states to re-emit in TU_CMD_DIRTY_DRAW_STATE case */\n'
     '   struct tu_draw_state dynamic_state[TU_DYNAMIC_STATE_COUNT];\n',
     '   /* saved states to re-emit in TU_CMD_DIRTY_DRAW_STATE case */\n'
     '   struct tu_draw_state dynamic_state[TU_DYNAMIC_STATE_COUNT];\n'
     '   /* TU_DRAW_STATE_SKIP_IDENTICAL */\n'
     '   const uint32_t *dynamic_state_map[TU_DYNAMIC_STATE_COUNT];\n',
     1),
    (PIPELINE_CC,
     '#include "tu_rmv.h"\n',
     '#include "tu_rmv.h"\n'
     '\n'
     'DEBUG_GET_ONCE_BOOL_OPTION(tu_draw_state_skip_identical, "TU_DRAW_STATE_SKIP_IDENTICAL", true)\n',
     1),
    (PIPELINE_CC,
     '#define EMIT_STATE(name)                                                      \\\n'
     '   emit_draw_state(&cmd->vk.dynamic_graphics_state, tu_##name##_state,        \\\n'
     '                   ARRAY_SIZE(tu_##name##_state))\n'
     '#define DRAW_STATE_COND(name, id, extra_cond, ...)                            \\\n'
     '   if ((EMIT_STATE(name) || (extra_cond)) &&                                  \\\n'
     '       !(cmd->state.pipeline_draw_states & (1u << id))) {                     \\\n'
     '      unsigned size = tu6_##name##_size<CHIP>(cmd->device, __VA_ARGS__);      \\\n'
     '      if (size > 0) {                                                         \\\n'
     '         tu_cs_begin_sub_stream(&cmd->sub_cs, size, &cs);                     \\\n'
     '         tu6_emit_##name<CHIP>(&cs, __VA_ARGS__);                             \\\n'
     '         cmd->state.dynamic_state[id] =                                       \\\n'
     '            tu_cs_end_draw_state(&cmd->sub_cs, &cs);                          \\\n'
     '      } else {                                                                \\\n'
     '         cmd->state.dynamic_state[id] = {};                                   \\\n'
     '      }                                                                       \\\n'
     '      dirty_draw_states |= (1u << id);                                        \\\n'
     '   }\n'
     '#define DRAW_STATE_FDM(name, id, ...)                                         \\\n'
     '   if ((EMIT_STATE(name) || (cmd->state.dirty &                               \\\n'
     '                             (TU_CMD_DIRTY_FDM |                              \\\n'
     '                              TU_CMD_DIRTY_PER_VIEW_VIEWPORT))) &&            \\\n'
     '       !(cmd->state.pipeline_draw_states & (1u << id))) {                     \\\n'
     '      if (cmd->state.has_fdm || cmd->state.per_layer_viewport) {              \\\n'
     '         tu_cs_set_writeable(&cmd->sub_cs, true);                             \\\n'
     '         tu6_emit_##name##_fdm(&cs, cmd, __VA_ARGS__);                        \\\n'
     '         cmd->state.dynamic_state[id] =                                       \\\n'
     '            tu_cs_end_draw_state(&cmd->sub_cs, &cs);                          \\\n'
     '         tu_cs_set_writeable(&cmd->sub_cs, false);                            \\\n'
     '      } else {                                                                \\\n'
     '         unsigned size = tu6_##name##_size<CHIP>(cmd->device, __VA_ARGS__);   \\\n'
     '         if (size > 0) {                                                      \\\n'
     '            tu_cs_begin_sub_stream(&cmd->sub_cs, size, &cs);                  \\\n'
     '            tu6_emit_##name<CHIP>(&cs, __VA_ARGS__);                          \\\n'
     '            cmd->state.dynamic_state[id] =                                    \\\n'
     '               tu_cs_end_draw_state(&cmd->sub_cs, &cs);                       \\\n'
     '         } else {                                                             \\\n'
     '            cmd->state.dynamic_state[id] = {};                                \\\n'
     '         }                                                                    \\\n'
     '      }                                                                       \\\n'
     '      dirty_draw_states |= (1u << id);                                        \\\n'
     '   }\n',
     '#define EMIT_STATE(name)                                                      \\\n'
     '   emit_draw_state(&cmd->vk.dynamic_graphics_state, tu_##name##_state,        \\\n'
     '                   ARRAY_SIZE(tu_##name##_state))\n'
     '#define DRAW_STATE_COND(name, id, extra_cond, ...)                            \\\n'
     '   if ((EMIT_STATE(name) || (extra_cond)) &&                                  \\\n'
     '       !(cmd->state.pipeline_draw_states & (1u << id))) {                     \\\n'
     '      unsigned size = tu6_##name##_size<CHIP>(cmd->device, __VA_ARGS__);      \\\n'
     '      if (size > 0) {                                                         \\\n'
     '         tu_cs_begin_sub_stream(&cmd->sub_cs, size, &cs);                     \\\n'
     '         tu6_emit_##name<CHIP>(&cs, __VA_ARGS__);                             \\\n'
     '         uint32_t emit_size = tu_cs_get_size(&cs);                            \\\n'
     '         if (debug_get_option_tu_draw_state_skip_identical() &&               \\\n'
     '             cmd->state.dynamic_state_map[id] != NULL &&                      \\\n'
     '             cmd->state.dynamic_state[id].size == emit_size &&                \\\n'
     '             memcmp(cmd->state.dynamic_state_map[id], cs.start,               \\\n'
     '                    emit_size * sizeof(uint32_t)) == 0) {                     \\\n'
     '            cmd->sub_cs.cur = cs.start;                                       \\\n'
     '            cmd->sub_cs.start = cs.start;                                     \\\n'
     '         } else {                                                             \\\n'
     '            cmd->state.dynamic_state_map[id] = cs.start;                      \\\n'
     '            cmd->state.dynamic_state[id] =                                    \\\n'
     '               tu_cs_end_draw_state(&cmd->sub_cs, &cs);                       \\\n'
     '            dirty_draw_states |= (1u << id);                                  \\\n'
     '         }                                                                    \\\n'
     '      } else {                                                                \\\n'
     '         cmd->state.dynamic_state[id] = {};                                   \\\n'
     '         cmd->state.dynamic_state_map[id] = NULL;                             \\\n'
     '         dirty_draw_states |= (1u << id);                                     \\\n'
     '      }                                                                       \\\n'
     '   }\n'
     '#define DRAW_STATE_FDM(name, id, ...)                                         \\\n'
     '   if ((EMIT_STATE(name) || (cmd->state.dirty &                               \\\n'
     '                             (TU_CMD_DIRTY_FDM |                              \\\n'
     '                              TU_CMD_DIRTY_PER_VIEW_VIEWPORT))) &&            \\\n'
     '       !(cmd->state.pipeline_draw_states & (1u << id))) {                     \\\n'
     '      if (cmd->state.has_fdm || cmd->state.per_layer_viewport) {              \\\n'
     '         tu_cs_set_writeable(&cmd->sub_cs, true);                             \\\n'
     '         tu6_emit_##name##_fdm(&cs, cmd, __VA_ARGS__);                        \\\n'
     '         cmd->state.dynamic_state[id] =                                       \\\n'
     '            tu_cs_end_draw_state(&cmd->sub_cs, &cs);                          \\\n'
     '         tu_cs_set_writeable(&cmd->sub_cs, false);                            \\\n'
     '         cmd->state.dynamic_state_map[id] = NULL;                             \\\n'
     '         dirty_draw_states |= (1u << id);                                     \\\n'
     '      } else {                                                                \\\n'
     '         unsigned size = tu6_##name##_size<CHIP>(cmd->device, __VA_ARGS__);   \\\n'
     '         if (size > 0) {                                                      \\\n'
     '            tu_cs_begin_sub_stream(&cmd->sub_cs, size, &cs);                  \\\n'
     '            tu6_emit_##name<CHIP>(&cs, __VA_ARGS__);                          \\\n'
     '            uint32_t emit_size = tu_cs_get_size(&cs);                         \\\n'
     '            if (debug_get_option_tu_draw_state_skip_identical() &&            \\\n'
     '                cmd->state.dynamic_state_map[id] != NULL &&                   \\\n'
     '                cmd->state.dynamic_state[id].size == emit_size &&             \\\n'
     '                memcmp(cmd->state.dynamic_state_map[id], cs.start,            \\\n'
     '                       emit_size * sizeof(uint32_t)) == 0) {                  \\\n'
     '               cmd->sub_cs.cur = cs.start;                                    \\\n'
     '               cmd->sub_cs.start = cs.start;                                  \\\n'
     '            } else {                                                          \\\n'
     '               cmd->state.dynamic_state_map[id] = cs.start;                   \\\n'
     '               cmd->state.dynamic_state[id] =                                 \\\n'
     '                  tu_cs_end_draw_state(&cmd->sub_cs, &cs);                    \\\n'
     '               dirty_draw_states |= (1u << id);                               \\\n'
     '            }                                                                 \\\n'
     '         } else {                                                             \\\n'
     '            cmd->state.dynamic_state[id] = {};                                \\\n'
     '            cmd->state.dynamic_state_map[id] = NULL;                          \\\n'
     '            dirty_draw_states |= (1u << id);                                  \\\n'
     '         }                                                                    \\\n'
     '      }                                                                       \\\n'
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
        files[path] = files[path].replace(old, new)
    for path, s in files.items():
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(s)
    print(f"{NAME}: applied (TU_DRAW_STATE_SKIP_IDENTICAL, default true)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
