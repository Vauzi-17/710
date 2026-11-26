#!/usr/bin/env python3
"""
Writes the GitHub release notes for a multi-branch build made by
.github/workflows/release_all.yml, matching the v4.6 release notes layout.

Reads per-branch artifact directories under COLLECTED_DIR (default: ./collected),
each containing out/branch-meta.json, out/build-info.env, out/android-info.env
(or out/glibc-meta.json + out/glibc-info.env), and the packaged files in
RELEASE_DIR (default: ./release).

Optional inputs (environment variables):
  RELEASE_VERSION     Release tag / version, e.g. 4.7
  CHANGES             "Changes in vX" lines, separated by ";"
  MESA_REF_DISPLAY    User-facing Mesa ref (default: main)
  GITHUB_REPOSITORY   owner/repo (used for default_env.conf URL & prev release)
  GH_TOKEN            GitHub API token for finding the previous release
  COLLECTED_DIR       Directory with downloaded turnip-* artifacts (default: collected)
  RELEASE_DIR         Directory with final release files (default: release)
  INCLUDE_SHA256      "true" to append a collapsible SHA-256 block
  MESA_SRC            Scratch git dir for upstream Mesa commit history

Usage: python3 release_notes_multi.py > RELEASE_NOTES.md
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import release_notes as rn

ROOT = Path(__file__).resolve().parent
COLLECTED_DIR = Path(os.environ.get("COLLECTED_DIR", ROOT / "collected"))
RELEASE_DIR = Path(os.environ.get("RELEASE_DIR", ROOT / "release"))
MESA_WEB = rn.MESA_WEB
MAX_UPSTREAM_COMMITS = rn.MAX_UPSTREAM_COMMITS

# Canonical ordering and display metadata for known branch keys.
KNOWN_VARIANTS = {
    "main": {
        "order": 0,
        "variant_title": "Regular / Universal",
        "patch_title": "Regular / Universal (Upstream)",
        "description": (
            "Upstream Mesa build with minimal patches for general use across "
            "emulators and native Android apps."
        ),
    },
    "sw": {
        "order": 1,
        "variant_title": "Switch",
        "patch_title": "Switch (SW)",
        "description": (
            "Build with patches for Nintendo Switch emulators (Eden, etc.), "
            "including sysmem defaults, BGRA swap, and LRZ rescue."
        ),
    },
    "win": {
        "order": 2,
        "variant_title": "Winlator",
        "patch_title": "Winlator / Windows (WIN)",
        "description": (
            "Build with patches for Winlator and DXVK/vkd3d-proton, including "
            "cached-coherent staging, sample shading gating, and UBO-only descriptor prefetch."
        ),
    },
    "unified": {
        "order": 3,
        "variant_title": "Unified",
        "patch_title": "Unified (UNIFIED)",
        "description": (
            "Combined build merging the Switch, Winlator, and Vita3K patch sets "
            "into a single driver."
        ),
    },
    "vita": {
        "order": 4,
        "variant_title": "Vita3K",
        "patch_title": "Vita3K (VITA)",
        "description": (
            "Build with patches targeting Vita3K, adding raster-order barrier bypass, "
            "prim-mode control, non-sticky LRZ stencil handling, and vertex buffer deduplication."
        ),
    },
}


def load_branch_metas():
    """Load all out/branch-meta.json files from COLLECTED_DIR."""
    metas = []
    if not COLLECTED_DIR.exists():
        return metas
    for meta_path in sorted(COLLECTED_DIR.glob("*/out/branch-meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as e:
            rn.log(f"skipping unreadable {meta_path}: {e}")
            continue
        if not meta.get("zips"):
            rn.log(f"skipping {meta_path} (no zip files produced)")
            continue
        out_dir = meta_path.parent
        meta["_out_dir"] = out_dir
        build_env = out_dir / "build-info.env"
        android_env = out_dir / "android-info.env"
        meta["_build_info"] = rn.read_env_file(build_env) if build_env.exists() else {}
        meta["_android_info"] = rn.read_env_file(android_env) if android_env.exists() else {}
        metas.append(meta)

    def sort_key(m):
        key = m.get("key", "")
        if key in KNOWN_VARIANTS:
            return (0, KNOWN_VARIANTS[key]["order"], key)
        return (1, 999, key)

    metas.sort(key=sort_key)
    return metas


def load_glibc_meta():
    """Load optional glibc artifact metadata if present."""
    if not COLLECTED_DIR.exists():
        return None
    for meta_path in sorted(COLLECTED_DIR.glob("*/out/glibc-meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as e:
            rn.log(f"skipping unreadable {meta_path}: {e}")
            continue
        if not meta.get("tzsts"):
            rn.log(f"skipping {meta_path} (no tzst files produced)")
            continue
        out_dir = meta_path.parent
        build_env = out_dir / "build-info.env"
        glibc_env = out_dir / "glibc-info.env"
        meta["_build_info"] = rn.read_env_file(build_env) if build_env.exists() else {}
        meta["_glibc_info"] = rn.read_env_file(glibc_env) if glibc_env.exists() else {}
        return meta
    return None


def main():
    branches = load_branch_metas()
    glibc_meta = load_glibc_meta()

    if not branches and not glibc_meta:
        sys.exit(f"No build metadata found under {COLLECTED_DIR}")

    # Pick primary build-info.env (all branches share the same pinned Mesa commit).
    primary_info = {}
    android_info = {}
    for b in branches:
        if b["_build_info"] and not primary_info:
            primary_info = b["_build_info"]
        if b["_android_info"] and not android_info:
            android_info = b["_android_info"]
    if not primary_info and glibc_meta:
        primary_info = glibc_meta["_build_info"]

    if not primary_info:
        sys.exit("build-info.env not found in any collected artifact")

    version = os.environ.get("RELEASE_VERSION") or (
        branches[0].get("release_version") if branches else ""
    ) or primary_info.get("BUILD_VERSION", "")
    mesa_commit = primary_info["MESA_COMMIT"]
    mesa_ref_display = os.environ.get("MESA_REF_DISPLAY", "").strip() or "main"
    repo = os.environ.get("GITHUB_REPOSITORY", "Vauzi-17/710")
    include_sha256 = os.environ.get("INCLUDE_SHA256", "false").lower() == "true"

    ndk_raw = android_info.get("NDK_VERSION", "")
    ndk = ndk_raw.split(",", 1)[0].replace("android-ndk-", "").strip()
    glibc_info = glibc_meta["_glibc_info"] if glibc_meta else {}

    lines = []
    add = lines.append

    if mesa_ref_display == "main":
        add("> Experimental build based on Mesa (main branch).")
    else:
        add(f"> Experimental build based on Mesa (`{mesa_ref_display}`).")
    add("> Not officially supported — do **not** report issues to Mesa upstream.")
    add("")
    add("## Support")
    add("- Need help? https://t.me/vauzi_17")
    add("")
    add("---")
    add("")

    # Optional Changes section (shown only when manual CHANGES or release_notes/v<ver>.md exists).
    changes = [c.strip() for c in os.environ.get("CHANGES", "").split(";") if c.strip()]
    notes_file = ROOT / "release_notes" / f"v{version}.md"
    if changes or notes_file.exists():
        add(f"## Changes in v{version}")
        for c in changes:
            add(f"- {c}")
        if notes_file.exists():
            add(notes_file.read_text(encoding="utf-8").strip())
        add("")

    # Driver Variants
    add("## Driver Variants")
    for b in branches:
        key = b.get("key", "")
        branch_name = b.get("branch", key)
        zips = b.get("zips") or []
        known = KNOWN_VARIANTS.get(key)
        title = known["variant_title"] if known else (b.get("label") or branch_name)
        desc = known["description"] if known else f"Custom build from branch `{branch_name}`."
        if zips:
            file_list = ", ".join(f"`{z}`" for z in zips)
            add(f"- **{title} ({file_list})**:")
        else:
            add(f"- **{title}**:")
        add(f"  {desc}")

    if glibc_meta:
        tzsts = glibc_meta.get("tzsts") or []
        g_branch = glibc_meta.get("branch", "win")
        if tzsts:
            file_list = ", ".join(f"`{t}`" for t in tzsts)
            add(f"- **Winlator glibc ({file_list})**:")
        else:
            add("- **Winlator glibc**:")
        add(
            f"  Experimental Linux glibc build with X11 presentation for Winlator "
            f"containers (built from branch `{g_branch}`)."
        )
    add("")

    # Environment Configuration (default_env.conf)
    if (RELEASE_DIR / "default_env.conf").exists():
        add("## Environment Configuration (`default_env.conf`) (Optional)")
        add(
            f"Download: [**default_env.conf**]"
            f"(https://github.com/{repo}/releases/download/{version}/default_env.conf)"
        )
        add("")
        add("### File Placement")
        add("Save the downloaded `default_env.conf` file to:")
        add("- **Per-App Storage**: `/sdcard/Android/data/<package_name>/files/default_env.conf`")
        add("  - Eden: `/sdcard/Android/data/<package_name>/files/default_env.conf`")
        add("  - Winlator: `/sdcard/Android/data/com.winlator/files/default_env.conf`")
        add("- **Global Fallback**: `/sdcard/default_env.conf`")
        add("")
        add(
            "> **Note**: Settings already active by default in the driver are commented out "
            "with `#`. You only need to remove the `#` or adjust the value if you want to "
            "override the driver's default behavior."
        )
        add("")

    # Build Info
    add("## Build Info")
    add("| | |")
    add("|---|---|")
    add(f"| Mesa | {primary_info['MESA_VERSION']} |")
    add(
        f"| Mesa commit | [`{mesa_commit[:12]}`]({MESA_WEB}/-/commit/{mesa_commit}) "
        f"({primary_info['MESA_COMMIT_DATE']}) |"
    )
    add(f"| Vulkan | {primary_info['VULKAN_VERSION']} |")
    if ndk:
        add(f"| Android NDK | {ndk} |")
    if glibc_info:
        add(f"| glibc build host | {glibc_info.get('GLIBC_BUILD_HOST', '')} |")
        add(
            f"| glibc build requires | glibc {glibc_info.get('GLIBC_REQUIRED', '?')} "
            "or newer in the rootfs |"
        )
    add(f"| Build date | {datetime.now(timezone.utc).strftime('%Y-%m-%d')} |")
    add("")

    # Applied Patches (collapsible <details> per branch, matching v4.6)
    patch_sections = []
    for b in branches:
        applied = [p for p in (b.get("patches") or []) if p.get("status") == "applied"]
        if not applied:
            continue
        key = b.get("key", "")
        known = KNOWN_VARIANTS.get(key)
        if known:
            summary = known["patch_title"]
        else:
            label = b.get("label") or b.get("branch", key)
            summary = f"{label} ({key.upper()})"
        patch_sections.append((summary, applied))

    if glibc_meta:
        g_applied = [
            p for p in (glibc_meta.get("glibc_patches") or []) if p.get("status") == "applied"
        ]
        if g_applied:
            g_branch = glibc_meta.get("branch", "glibc")
            patch_sections.append((f"Winlator glibc-specific ({g_branch})", g_applied))

    if patch_sections:
        add("## Applied Patches")
        add("")
        for summary, applied in patch_sections:
            add("<details>")
            add(f"<summary><b>{rn.escape(summary)}</b></summary>")
            add("")
            for p in applied:
                name = Path(p["name"]).name
                desc = (p.get("description") or "").strip()
                add(f"- `{name}`" + (f" — {rn.escape(desc)}" if desc else ""))
            add("")
            add("</details>")
            add("")

    # Upstream Freedreno Changes Since <prev_tag>
    result = rn.upstream_commits(
        rn.previous_release(version),
        mesa_commit,
        primary_info.get("MESA_REF", "main"),
        primary_info.get("MESA_REPO", MESA_WEB),
    )
    if result:
        prev, commits = result
        prev_name = prev.get("tag_name", "previous release")
        add(f"## Upstream Freedreno Changes Since {prev_name}")
        if not commits:
            add("No new commits under `src/freedreno`.")
        else:
            add(f"{len(commits)} commits under `src/freedreno`, grouped by commit title.")
            add("")
            for title, group in rn.group_commits(commits):
                add("<details>")
                add(f"<summary>{title} ({len(group)})</summary>")
                add("")
                for sha, subject in group[:MAX_UPSTREAM_COMMITS]:
                    add(f"- [`{sha[:10]}`]({MESA_WEB}/-/commit/{sha}) {rn.escape(subject)}")
                if len(group) > MAX_UPSTREAM_COMMITS:
                    add(f"- ... and {len(group) - MAX_UPSTREAM_COMMITS} more")
                add("")
                add("</details>")
                add("")
        add("")

    # GPU Support
    add("## GPU Support")
    add("Supports all GPUs currently supported by Mesa, including Adreno 6xx, 7xx, and 8xx series.")
    add("For the complete and up-to-date device list, see:")
    add(f"{MESA_WEB}/-/blob/main/src/freedreno/common/freedreno_devices.py")
    add("")

    # Notes
    add("## Notes")
    add("- Graphics issues may still occur depending on the game or emulator.")
    add("- Performance and compatibility vary by device, firmware, emulator version, and game.")
    add("- Recommended memory mode: **sysmem** (`TU_DEBUG=sysmem`).")
    add("- Experimental build.")
    if glibc_info:
        add(
            "- The `.tzst` is a glibc build with X11 presentation, for Winlator and similar"
            " containers. Extract it into the rootfs. The ICD file points to"
            f" `{glibc_info.get('GLIBC_ICD_LIBRARY_PATH', '')}`; edit it if your app uses another path."
        )
        extra = glibc_info.get("GLIBC_EXTRA_LIBS", "").split()
        if extra:
            add(
                f"- The `.tzst` also contains {', '.join(f'`{e}`' for e in extra)} "
                "from the build host."
            )
    add("")

    # Credits
    add("## Credits")
    add(
        "Special thanks to **whitebelyash**, **Leb-Sun**, **Max Jividen (MaxsTechReview)**, "
        "**Alex Sanz (AlexSanz0902)**, **Dhruv Mark Collins**, **Hugo223**, and **StevenMX**"
    )

    # Optional SHA-256 block
    if include_sha256 and RELEASE_DIR.exists():
        release_files = sorted(
            [f for f in RELEASE_DIR.iterdir() if f.is_file()],
            key=lambda p: (p.suffix != ".zip", p.suffix != ".tzst", p.name),
        )
        if release_files:
            add("")
            add("<details>")
            add("<summary>SHA-256</summary>")
            add("")
            add("```")
            for f in release_files:
                add(f"{rn.sha256(f)}  {f.name}")
            add("```")
            add("")
            add("</details>")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
