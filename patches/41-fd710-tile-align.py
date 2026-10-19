#!/usr/bin/env python3
"""FD710: tile_align_w/h 64x32 -> 32x16.

Blob 710 picks bins 416x208 (test-lrz 800x600, 2x3 bins), 288x224, 160x96: width
granularity 32, height 16. Other 1-CCU parts in mesa (FD702, A810) use 32x16.
Only affects GMEM rendering (no effect while 36-tu-z-sysmem-only forces sysmem).

Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = '41-fd710-tile-align.py'
SUMMARY = 'FD710 tile_align_w = 32, tile_align_h = 16'

EDITS = [
    ('src/freedreno/common/freedreno_devices.py',
     None,
     'name="FD710"), # Default no-speedbin fallback\n    ], A6xxGPUInfo(\n        CHIP.A7XX,\n        [a7xx_base, a7xx_gen1],\n        num_ccu = 1,\n        tile_align_w = 64,\n        tile_align_h = 32,\n',
     'name="FD710"), # Default no-speedbin fallback\n    ], A6xxGPUInfo(\n        CHIP.A7XX,\n        [a7xx_base, a7xx_gen1],\n        num_ccu = 1,\n        tile_align_w = 32,\n        tile_align_h = 16,\n'),
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
    def applied(path, scope, old, new):
        s = files[path]
        if not scope:
            return (new[len(old):] if new.startswith(old) else new) in s
        start = s.find(scope)
        n, o = s.find(new, start), s.find(old, start)
        return start >= 0 and n >= 0 and (o < 0 or n < o)
    if all(applied(*e) for e in EDITS):
        print(f"{NAME}: already applied")
        return 0
    for path, scope, old, new in EDITS:
        s = files[path]
        start = 0
        if scope:
            if s.count(scope) != 1:
                print(f"{NAME}: WARNING scope matched {s.count(scope)}x in {path}; patch skipped")
                return 0
            start = s.index(scope)
        i = s.find(old, start)
        if i < 0 or (not scope and s.count(old) != 1):
            print(f"{NAME}: WARNING anchor not unique/found in {path}; upstream changed, patch skipped")
            return 0
        files[path] = s[:i] + new + s[i + len(old):]
    for path, s in files.items():
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(s)
    print(f"{NAME}: applied ({SUMMARY})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
