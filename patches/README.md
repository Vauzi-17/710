# patches

Optional patches applied on top of upstream Mesa by `turnip_builder.sh`.
If this folder has no patch files, the build is plain upstream Mesa.

## What gets applied

Files directly in this folder, sorted by name, applied to every build:

| Extension | How it is applied |
|---|---|
| `.patch`, `.diff` | `git apply`, falling back to `patch -p1` with fuzz |
| `.py` | `python3 <file>`, run from the Mesa source root |
| `.sh` | `bash <file>`, run from the Mesa source root |

Anything else is ignored: this README, sub folders (except `variants/`),
and files with other extensions. To turn a patch off without deleting it,
rename it, for example `foo.py` to `foo.py.off`.

Use a number prefix when order matters:

```
patches/
  01-some-fix.patch
  02-another-fix.py
```

The build stops if a `.patch` does not apply or a script exits non-zero.
If a patch runs but changes nothing (already merged upstream, or its anchor
text no longer matches), the build continues with a warning and the patch is
left out of the release notes.

Python scripts written for other builders, such as the ones in
[WinNative-Emu/Drivers](https://github.com/WinNative-Emu/Drivers/tree/main/patches),
work as long as they expect to run from the Mesa root. Copy any helper files
they load (for example `aimapper/`) next to them.

## Variants

Each folder under `variants/` produces one extra zip, built from the common
patches above plus the patches in that folder:

```
patches/
  01-some-fix.patch              -> in every zip
  variants/
    lf/
      DESCRIPTION                -> one line, shown in the release notes
      apply_perf_variant.py      -> only in Turnip-710-720-722-vX-lf.zip
```

Result: `Turnip-710-720-722-vX.zip` and `Turnip-710-720-722-vX-lf.zip`.

## Checking patches without a full build

```
BUILD_VERSION=test PATCH_ONLY=1 bash turnip_builder.sh
```

This clones Mesa and applies everything, then stops before downloading the
NDK or compiling.
