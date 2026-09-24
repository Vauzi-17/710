#!/usr/bin/env python3
"""
Writes the GitHub release notes for a build made by turnip_builder.sh.

Reads out/build-info.env, out/patches-<variant>.txt and the zips in out/.
Optional inputs (environment variables):
  CHANGES       "Changes in vX" lines, separated by ";"
  GITHUB_REPOSITORY, GH_TOKEN
                used to find the previous release, so the notes can list the
                upstream freedreno commits that landed since then
  MESA_SRC      Mesa checkout used for the build (default: turnip_workdir/mesa)
  OUT_DIR       default: out
Also reads release_notes/v<version>.md if it exists and adds it under
"Changes in v<version>".

Usage: python3 release_notes.py > RELEASE_NOTES.md
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DIR = Path(os.environ.get("OUT_DIR", ROOT / "out"))
PATCH_DIR = Path(os.environ.get("PATCH_DIR", ROOT / "patches"))
MESA_SRC = Path(os.environ.get("MESA_SRC", ROOT / "turnip_workdir" / "mesa"))
MESA_WEB = "https://gitlab.freedesktop.org/mesa/mesa"
MAX_UPSTREAM_COMMITS = 200


def log(msg):
    print(msg, file=sys.stderr)


def read_env_file(path):
    info = {}
    for line in path.read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            info[key.strip()] = value.strip()
    return info


def patch_description(path):
    """First line of a .py docstring/comment or the Subject of a .patch."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return ""

    if path.suffix in (".patch", ".diff"):
        m = re.search(r"^Subject:\s*(?:\[[^\]]*\]\s*)?(.+)$", text, re.M)
        return m.group(1).strip() if m else ""

    if path.suffix == ".py":
        m = re.search(r'^\s*(?:"""|\'\'\')\s*\n?\s*(.+)$', text, re.M)
        if m:
            return m.group(1).strip().rstrip("\"'").rstrip(".")

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") and not line.startswith("#!"):
            desc = line.lstrip("#").strip()
            if desc:
                return desc.rstrip(".")
    return ""


def read_patch_log(variant):
    path = OUT_DIR / f"patches-{variant}.txt"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        if "\t" in line:
            name, status = line.split("\t", 1)
            rows.append((name, status))
    return rows


def variant_description(variant):
    path = PATCH_DIR / "variants" / variant / "DESCRIPTION"
    if path.exists():
        return path.read_text().strip().splitlines()[0]
    return ""


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def previous_release():
    """Latest published release of this repo, or None."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        return None
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except Exception as e:  # first release, no network, rate limit, ...
        log(f"could not read previous release: {e}")
        return None


def git(*args):
    return subprocess.run(["git", "-C", str(MESA_SRC), *args],
                          capture_output=True, text=True)


def upstream_commits(prev, mesa_commit, mesa_ref, mesa_repo):
    """freedreno commits between the previous release's Mesa commit and ours."""
    if not prev:
        return None
    if not (MESA_SRC / ".git").exists():
        # Release job without a build tree: history only, no file contents.
        MESA_SRC.mkdir(parents=True, exist_ok=True)
        git("init", "-q")
        git("remote", "add", "origin", mesa_repo)
        git("config", "remote.origin.partialclonefilter", "blob:none")
        git("config", "remote.origin.promisor", "true")

    m = re.search(r"mesa/-/commit/([0-9a-f]{40})", prev.get("body") or "")
    prev_commit = m.group(1) if m else None
    published = prev.get("published_at")
    if not published:
        return None
    since = datetime.fromisoformat(published.replace("Z", "+00:00"))

    # The build clone is shallow; fetch enough history to reach the old commit.
    fetch_since = (since - timedelta(days=14)).strftime("%Y-%m-%d")
    if git("fetch", "-q", "--filter=blob:none", f"--shallow-since={fetch_since}",
           "origin", mesa_ref).returncode != 0:
        git("fetch", "-q", "--filter=blob:none", "--depth=1000", "origin", mesa_ref)

    if prev_commit and prev_commit == mesa_commit:
        return prev, []

    if prev_commit and git("merge-base", "--is-ancestor", prev_commit, mesa_commit).returncode == 0:
        rev_args = [f"{prev_commit}..{mesa_commit}"]
    else:
        # Older releases do not record their Mesa commit; fall back to the date.
        rev_args = [f"--since={since.isoformat()}", mesa_commit]

    res = git("log", "--no-merges", "--format=%H%x09%s", *rev_args, "--", "src/freedreno")
    if res.returncode != 0:
        log(f"git log failed: {res.stderr.strip()}")
        return None
    commits = [line.split("\t", 1) for line in res.stdout.splitlines() if "\t" in line]
    return prev, commits


A7XX_RE = re.compile(r"\ba7(xx|\d\d)\b", re.I)


def group_commits(commits):
    """Split commits into display groups, based on the commit title only.

    Anything mentioning A7xx comes first, whatever its prefix. The rest is
    sorted by the "prefix:" part of the title, so a commit with an unusual
    prefix can land in the wrong group.
    """
    groups = {"A7xx": [], "Turnip (tu)": [], "Compiler (ir3)": [], "Other": []}
    for sha, subject in commits:
        prefix = subject.split(":", 1)[0].strip().lower() if ":" in subject else ""
        if A7XX_RE.search(subject):
            key = "A7xx"
        elif re.match(r"(tu|turnip)\b", prefix):
            key = "Turnip (tu)"
        elif re.match(r"ir3\b", prefix):
            key = "Compiler (ir3)"
        else:
            key = "Other"
        groups[key].append((sha, subject))
    return [(title, group) for title, group in groups.items() if group]


def escape(text):
    """Keep commit titles from being read as HTML inside <details>."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main():
    info_path = OUT_DIR / "build-info.env"
    if not info_path.exists():
        sys.exit(f"{info_path} not found, run turnip_builder.sh first")
    info = read_env_file(info_path)

    version = info["BUILD_VERSION"]
    mesa_commit = info["MESA_COMMIT"]
    android = read_env_file(OUT_DIR / "android-info.env") if (OUT_DIR / "android-info.env").exists() else {}
    glibc = read_env_file(OUT_DIR / "glibc-info.env") if (OUT_DIR / "glibc-info.env").exists() else {}
    ndk = android.get("NDK_VERSION", "").replace("android-ndk-", "")

    # File name: <prefix>-v<version>[-<variant>][-glibc].zip|.tzst
    files = list(OUT_DIR.glob("*.zip")) + list(OUT_DIR.glob("*.tzst"))
    kind_of = {}
    for f in files:
        rest = f.stem.rsplit(f"v{version}", 1)[-1].lstrip("-")
        target = "android"
        if f.suffix == ".tzst":
            target = "glibc"
            rest = rest[:-len("glibc")].rstrip("-") if rest.endswith("glibc") else rest
        kind_of[f] = (rest or "base", target)
    # Android first, then glibc; standard build before variants.
    files.sort(key=lambda f: (kind_of[f][1] != "android", kind_of[f][0] != "base", f.name))
    variants = list(dict.fromkeys(kind_of[f][0] for f in files))

    lines = []
    add = lines.append

    add("> Experimental build based on Mesa (main branch).")
    add("> Not officially supported — do **not** report issues to Mesa upstream.")
    add("")
    add("## Support")
    add("- Need help? https://t.me/vauzi_17")
    add("")
    add("---")
    add("")

    # Changes: manual notes first, then the notes file, then the default line.
    add(f"## Changes in v{version}")
    changes = [c.strip() for c in os.environ.get("CHANGES", "").split(";") if c.strip()]
    for c in changes:
        add(f"- {c}")
    notes_file = ROOT / "release_notes" / f"v{version}.md"
    if notes_file.exists():
        add(notes_file.read_text().strip())
    if not changes and not notes_file.exists():
        add("- Synced with the latest Mesa main branch")
    add("")

    add("## Build Info")
    add("| | |")
    add("|---|---|")
    add(f"| Mesa | {info['MESA_VERSION']} |")
    add(f"| Mesa commit | [`{mesa_commit[:12]}`]({MESA_WEB}/-/commit/{mesa_commit}) ({info['MESA_COMMIT_DATE']}) |")
    add(f"| Vulkan | {info['VULKAN_VERSION']} |")
    if ndk:
        add(f"| Android NDK | {ndk} |")
    if glibc:
        add(f"| glibc build host | {glibc.get('GLIBC_BUILD_HOST', '')} |")
        add(f"| glibc build requires | glibc {glibc.get('GLIBC_REQUIRED', '?')} or newer in the rootfs |")
    add(f"| Build date | {datetime.now(timezone.utc).strftime('%Y-%m-%d')} |")
    add("")

    # Patches, per build. Section is left out for a plain upstream build.
    base = [n for n, s in read_patch_log("base") if s == "applied"]
    extras = {v: [n for n, s in read_patch_log(v) if s == "applied" and n not in base]
              for v in variants if v != "base"}
    glibc_only = list(dict.fromkeys(
        n for v in variants for n, s in read_patch_log(f"glibc-{v}") if s == "applied"))
    if base or any(extras.values()) or glibc_only:
        add("## Applied Patches")
    if not base and (any(extras.values()) or glibc_only):
        add("None in the standard build.")
    for name in base:
        desc = patch_description(PATCH_DIR / name)
        add(f"- `{name}`" + (f" — {desc}" if desc else ""))
    for variant, extra in extras.items():
        if not extra:
            continue
        add("")
        add(f"Only in the `{variant}` variant:")
        for name in extra:
            desc = patch_description(PATCH_DIR / name)
            add(f"- `{Path(name).name}`" + (f" — {desc}" if desc else ""))
    if glibc_only:
        add("")
        add("Only in the glibc build:")
        for name in glibc_only:
            desc = patch_description(PATCH_DIR / name)
            add(f"- `{Path(name).name}`" + (f" — {desc}" if desc else ""))
    if base or any(extras.values()) or glibc_only:
        add("")

    result = upstream_commits(previous_release(), mesa_commit, info.get("MESA_REF", "main"),
                              info.get("MESA_REPO", MESA_WEB))
    if result:
        prev, commits = result
        prev_name = prev.get("tag_name", "previous release")
        add(f"## Upstream Freedreno Changes Since {prev_name}")
        if not commits:
            add("No new commits under `src/freedreno`.")
        else:
            add(f"{len(commits)} commits under `src/freedreno`, grouped by commit title.")
            add("")
            for title, group in group_commits(commits):
                add("<details>")
                add(f"<summary>{title} ({len(group)})</summary>")
                add("")
                for sha, subject in group[:MAX_UPSTREAM_COMMITS]:
                    add(f"- [`{sha[:10]}`]({MESA_WEB}/-/commit/{sha}) {escape(subject)}")
                if len(group) > MAX_UPSTREAM_COMMITS:
                    add(f"- ... and {len(group) - MAX_UPSTREAM_COMMITS} more")
                add("")
                add("</details>")
                add("")
        add("")

    add("## GPU Support")
    add("Supports all GPUs currently supported by Mesa, including Adreno 6xx, 7xx, and 8xx series.")
    add("For the complete and up-to-date device list, see:")
    add(f"{MESA_WEB}/-/blob/main/src/freedreno/common/freedreno_devices.py")
    add("")
    add("## Notes")
    add("- Graphics issues may still occur depending on the game or emulator.")
    add("- Performance and compatibility vary by device, firmware, emulator version, and game.")
    add("- Recommended memory mode: **sysmem** (`TU_DEBUG=sysmem`).")
    add("- Experimental build.")
    if glibc:
        add("- The `.tzst` is a glibc build with X11 presentation, for Winlator and similar"
            " containers. Extract it into the rootfs. The ICD file points to"
            f" `{glibc.get('GLIBC_ICD_LIBRARY_PATH', '')}`; edit it if your app uses another path.")
        extra = glibc.get("GLIBC_EXTRA_LIBS", "").split()
        if extra:
            add(f"- The `.tzst` also contains {', '.join(f'`{e}`' for e in extra)} from the build host.")
    add("")

    add("## Files")
    for f in files:
        variant, target = kind_of[f]
        if variant == "base":
            desc = "standard build"
        else:
            desc = variant_description(variant) or f"{variant} variant"
        if target == "glibc":
            desc = f"glibc (Winlator), {desc}"
        else:
            desc = f"Android (AdrenoTools), {desc}"
        add(f"- `{f.name}` — {desc}")
    add("")
    add("<details>")
    add("<summary>SHA-256</summary>")
    add("")
    add("```")
    for f in files:
        add(f"{sha256(f)}  {f.name}")
    add("```")
    add("")
    add("</details>")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
