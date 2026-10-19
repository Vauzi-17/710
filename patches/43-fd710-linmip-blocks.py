#!/usr/bin/env python3
"""FD710: supports_linear_mipmap_threshold_in_blocks off.

TPL1_DBG_ECO_CNTL 0x03000000 -> 0x01000000 and the linear mipmap fallback
threshold goes back to texels. In the blob this bit comes from a per-chip
feature flag that is off for 710 and on for a720.

Run from the Mesa source root. All edits are applied or none.
"""
import sys

NAME = '43-fd710-linmip-blocks.py'
SUMMARY = 'FD710 supports_linear_mipmap_threshold_in_blocks = False'

EDITS = [
    ('src/freedreno/common/freedreno_devices.py',
     None,
     '        raw_magic_regs = a710_raw_magic_regs,\n    ))\n',
     '        raw_magic_regs = a710_raw_magic_regs,\n    ))\nGPUProps(supports_linear_mipmap_threshold_in_blocks = False).apply_props(s.gpu_infos[-1])\n'),
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
