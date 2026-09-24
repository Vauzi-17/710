# Status of the Winlator patches

Tested on Adreno 710 with Winlator 11.2 (Test Direct3D):

| Build | Result |
|---|---|
| Upstream X11 WSI (no WSI patches) | Works, image shown |
| `01` + `02` enabled, Direct rendering on | Driver loads, window stays black, also with `MESA_VK_WSI_FORCE_WAIT_FOR_FENCES=1` |
| `01` + `02` enabled, Direct rendering off | Test Direct3D crashes |

`01`, `02` and `04` are disabled (`.off`) until this is solved. Rename them
back to enable them. `03-tu-override-heap-size.py` stays enabled; it only
acts when Winlator sets `TU_OVERRIDE_HEAP_SIZE`.

Likely cause, not confirmed: the ported WSI is the last public version
(brunodev85/mesa3d-custom, August 2026). Winlator app version code 33
(September 2026) changed the X server's Present and DRI3 handling (BGRA
window buffers, PresentConfigureNotify, a new environment variable), and
the Mesa side of that change is not public.
