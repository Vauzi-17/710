#!/usr/bin/env python3
"""Avoid redundant vertex buffer draw state allocations and packet emissions.

In tu_CmdBindVertexBuffers2, applications and emulators often bind vertex buffers
redundantly with identical parameters across draw calls. Upstream allocates new
draw state in sub_cs and re-emits register packets on every invocation.

This patch compares incoming vertex buffer bindings (IOVA base address, size,
and stride) against cmd->state.vb and dynamic VI strides. If identical to current
state, the call returns early, eliminating redundant sub_cs allocations and
CP_SET_DRAW_STATE emissions.

Env TU_VB_DEDUP (default true):
  true   deduplicate identical vertex buffer bindings and return early
  false  always allocate and emit vertex buffer draw states (upstream behavior)

Target: Adreno 7xx / 8xx (a710, a810 [Snapdragon 6 Gen 4, 7s Gen 3, 7s Gen 4]).
Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = "73-tu-vb-dedup.py"
MARKER = "TU_VB_DEDUP"
CMD_BUFFER = "src/freedreno/vulkan/tu_cmd_buffer.cc"

EDITS = [
    (CMD_BUFFER,
     '   cmd_buffer->state.max_vbs_bound = 0;\n',
     '   cmd_buffer->state.max_vbs_bound = 0;\n'
     '   cmd_buffer->state.vertex_buffers = {};\n',
     1),
    (CMD_BUFFER,
     'VKAPI_ATTR void VKAPI_CALL\n'
     'tu_CmdBindVertexBuffers2(VkCommandBuffer commandBuffer,\n'
     '                         uint32_t firstBinding,\n'
     '                         uint32_t bindingCount,\n'
     '                         const VkBuffer *pBuffers,\n'
     '                         const VkDeviceSize *pOffsets,\n'
     '                         const VkDeviceSize *pSizes,\n'
     '                         const VkDeviceSize *pStrides)\n'
     '{\n'
     '   VK_FROM_HANDLE(tu_cmd_buffer, cmd, commandBuffer);\n'
     '   struct tu_cs cs;\n',
     '#include "util/u_debug.h"\n'
     '\n'
     'DEBUG_GET_ONCE_BOOL_OPTION(tu_vb_dedup, "TU_VB_DEDUP", true)\n'
     '\n'
     'VKAPI_ATTR void VKAPI_CALL\n'
     'tu_CmdBindVertexBuffers2(VkCommandBuffer commandBuffer,\n'
     '                         uint32_t firstBinding,\n'
     '                         uint32_t bindingCount,\n'
     '                         const VkBuffer *pBuffers,\n'
     '                         const VkDeviceSize *pOffsets,\n'
     '                         const VkDeviceSize *pSizes,\n'
     '                         const VkDeviceSize *pStrides)\n'
     '{\n'
     '   VK_FROM_HANDLE(tu_cmd_buffer, cmd, commandBuffer);\n'
     '\n'
     '   if (debug_get_option_tu_vb_dedup() &&\n'
     '       cmd->state.vertex_buffers.iova != 0 &&\n'
     '       cmd->state.max_vbs_bound >= (firstBinding + bindingCount)) {\n'
     '      bool identical = true;\n'
     '      for (uint32_t i = 0; i < bindingCount; i++) {\n'
     '         uint32_t b = firstBinding + i;\n'
     '         uint64_t base = 0;\n'
     '         uint32_t size = 0;\n'
     '         if (pBuffers[i] != VK_NULL_HANDLE) {\n'
     '            struct tu_buffer *buf = tu_buffer_from_handle(pBuffers[i]);\n'
     '            base = vk_buffer_address(&buf->vk, pOffsets[i]);\n'
     '            size = vk_buffer_range(&buf->vk, pOffsets[i], pSizes ? pSizes[i] : VK_WHOLE_SIZE);\n'
     '         }\n'
     '         if (cmd->state.vb[b].base != base || cmd->state.vb[b].size != size) {\n'
     '            identical = false;\n'
     '            break;\n'
     '         }\n'
     '         if (pStrides &&\n'
     '             cmd->vk.dynamic_graphics_state.vi_binding_strides[b] != pStrides[i]) {\n'
     '            identical = false;\n'
     '            break;\n'
     '         }\n'
     '      }\n'
     '      if (identical)\n'
     '         return;\n'
     '   }\n'
     '\n'
     '   struct tu_cs cs;\n',
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
    print(f"{NAME}: applied (TU_VB_DEDUP, default true)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
