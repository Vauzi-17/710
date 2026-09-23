#!/bin/bash
#
# Turnip builder for Adreno 710 / 720 / 722.
#
# Builds the Freedreno Vulkan driver (Turnip) for Android from upstream Mesa,
# applies the optional patches in patches/, and packs the result as an
# AdrenoTools zip.
#
# Usage:
#   BUILD_VERSION=3.9 bash turnip_builder.sh
#
# Settings (environment variables, all optional except BUILD_VERSION):
#   BUILD_VERSION     Release version, e.g. 3.9 (used in zip name and meta.json)
#   MESA_REPO         Mesa git repository   (default: upstream GitLab)
#   MESA_REF          Branch, tag or commit (default: main)
#   BUILD_VARIANTS    Which builds to make: "all" (default), or a space
#                     separated list such as "base" or "base lf"
#   PATCH_DIR         Patch folder          (default: ./patches)
#   OUT_DIR           Output folder         (default: ./out)
#   ANDROID_NDK_HOME  Use an existing NDK instead of downloading NDK_VERSION
#   NDK_VERSION       NDK to download       (default: android-ndk-r29)
#   PATCH_ONLY=1      Clone and apply patches, then stop (no NDK, no compile).
#                     Handy for checking whether patches still apply to main.
#
# Patch folder layout (see patches/README.md):
#   patches/*.patch|*.diff|*.py|*.sh   applied to every build, in name order
#   patches/variants/<name>/...        extra patches for the <name> variant,
#                                      which is built as a separate zip
#   anything else (README, sub folders, *.off) is ignored

set -euo pipefail

green='\033[0;32m'
yellow='\033[0;33m'
red='\033[0;31m'
nocolor='\033[0m'

rootdir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workdir="$rootdir/turnip_workdir"
srcdir="$workdir/mesa"

BUILD_VERSION="${BUILD_VERSION:-}"
MESA_REPO="${MESA_REPO:-https://gitlab.freedesktop.org/mesa/mesa}"
MESA_REF="${MESA_REF:-main}"
BUILD_VARIANTS="${BUILD_VARIANTS:-all}"
PATCH_DIR="${PATCH_DIR:-$rootdir/patches}"
OUT_DIR="${OUT_DIR:-$rootdir/out}"
NDK_VERSION="${NDK_VERSION:-android-ndk-r29}"
PATCH_ONLY="${PATCH_ONLY:-0}"

# The API level the NDK compiler targets, and the one Mesa is configured for.
sdkver="34"
platform_sdkver="36"

# meta.json fields
DRIVER_NAME="${DRIVER_NAME:-710 720 & 722}"
DRIVER_DESCRIPTION="${DRIVER_DESCRIPTION:-Turnip driver for Adreno 710/720/722}"
DRIVER_AUTHOR="${DRIVER_AUTHOR:-vauzi}"
ZIP_PREFIX="${ZIP_PREFIX:-Turnip-710-720-722}"

info(){ echo -e "${green}$*${nocolor}"; }
warn(){
	echo -e "${yellow}WARNING: $*${nocolor}" >&2
	if [ -n "${GITHUB_ACTIONS:-}" ]; then echo "::warning::$*"; fi
}
die(){
	echo -e "${red}ERROR: $*${nocolor}" >&2
	if [ -n "${GITHUB_ACTIONS:-}" ]; then echo "::error::$*"; fi
	exit 1
}

run_all(){
	[ -n "$BUILD_VERSION" ] || die "BUILD_VERSION is not set (example: BUILD_VERSION=3.9 bash turnip_builder.sh)"

	info "====== Turnip 710/720/722 v$BUILD_VERSION ======"
	check_deps
	mkdir -p "$workdir"
	rm -rf "$OUT_DIR"
	mkdir -p "$OUT_DIR"

	if [ "$PATCH_ONLY" != "1" ]; then
		prepare_ndk
	fi
	clone_mesa
	write_build_info

	local variant
	for variant in $(resolve_variants); do
		build_variant "$variant"
	done

	info "====== Done ======"
	ls -lh "$OUT_DIR"
}

check_deps(){
	local deps="git python3 patch"
	if [ "$PATCH_ONLY" != "1" ]; then
		deps="$deps meson ninja unzip curl flex bison zip glslangValidator"
	fi

	echo "Checking dependencies ..."
	local missing=0 dep
	for dep in $deps; do
		if command -v "$dep" >/dev/null 2>&1; then
			echo -e "$green - $dep found $nocolor"
		else
			echo -e "$red - $dep not found $nocolor"
			missing=1
		fi
	done
	[ "$missing" = "0" ] || die "please install the missing dependencies"

	if [ "$PATCH_ONLY" != "1" ] && ! python3 -c "import mako" >/dev/null 2>&1; then
		echo "Installing python Mako ..."
		pip install mako >/dev/null || die "could not install python mako"
	fi
}

prepare_ndk(){
	if [ -n "${ANDROID_NDK_HOME:-}" ]; then
		ndkroot="$ANDROID_NDK_HOME"
	else
		ndkroot="$workdir/$NDK_VERSION"
		if [ ! -d "$ndkroot" ]; then
			echo "Downloading $NDK_VERSION ..."
			curl -fL --retry 3 -o "$workdir/$NDK_VERSION-linux.zip" \
				"https://dl.google.com/android/repository/$NDK_VERSION-linux.zip"
			echo "Extracting $NDK_VERSION ..."
			unzip -q "$workdir/$NDK_VERSION-linux.zip" -d "$workdir"
			rm -f "$workdir/$NDK_VERSION-linux.zip"
		fi
	fi
	ndk="$ndkroot/toolchains/llvm/prebuilt/linux-x86_64/bin"
	[ -x "$ndk/aarch64-linux-android$sdkver-clang" ] || die "NDK compiler not found in $ndk"
}

clone_mesa(){
	echo "Fetching Mesa $MESA_REF from $MESA_REPO ..."
	rm -rf "$srcdir"
	git init -q "$srcdir"
	git -C "$srcdir" remote add origin "$MESA_REPO"
	# Fetching by name works for branches, tags and full commit hashes alike.
	git -C "$srcdir" fetch -q --depth=1 origin "$MESA_REF"
	git -C "$srcdir" -c advice.detachedHead=false checkout -q FETCH_HEAD

	MESA_COMMIT="$(git -C "$srcdir" rev-parse HEAD)"
	MESA_COMMIT_DATE="$(git -C "$srcdir" log -1 --format=%cs HEAD)"
	MESA_VERSION="$(tr -d '[:space:]' < "$srcdir/VERSION")"

	local header="$srcdir/include/vulkan/vulkan_core.h" vk_patch vk_major_minor
	vk_patch="$(sed -n 's/^#define VK_HEADER_VERSION \([0-9]\+\).*/\1/p' "$header")"
	vk_major_minor="$(sed -n 's/^#define VK_HEADER_VERSION_COMPLETE VK_MAKE_API_VERSION(0, \([0-9]\+\), \([0-9]\+\),.*/\1.\2/p' "$header")"
	VULKAN_VERSION="$vk_major_minor.$vk_patch"

	info "Mesa $MESA_VERSION, commit $MESA_COMMIT ($MESA_COMMIT_DATE), Vulkan $VULKAN_VERSION"
}

write_build_info(){
	cat <<EOF >"$OUT_DIR/build-info.env"
BUILD_VERSION=$BUILD_VERSION
MESA_REPO=$MESA_REPO
MESA_REF=$MESA_REF
MESA_COMMIT=$MESA_COMMIT
MESA_COMMIT_DATE=$MESA_COMMIT_DATE
MESA_VERSION=$MESA_VERSION
VULKAN_VERSION=$VULKAN_VERSION
NDK_VERSION=$( [ -n "${ANDROID_NDK_HOME:-}" ] && basename "$ANDROID_NDK_HOME" || echo "$NDK_VERSION" )
EOF
}

# "base" is the build with only the common patches. Every folder under
# patches/variants/ adds one more build on top of it.
resolve_variants(){
	if [ "$BUILD_VARIANTS" != "all" ]; then
		echo "$BUILD_VARIANTS"
		return
	fi
	echo "base"
	local d
	if [ -d "$PATCH_DIR/variants" ]; then
		for d in "$PATCH_DIR"/variants/*/; do
			[ -d "$d" ] && basename "$d"
		done
	fi
	return 0
}

# Changes to tracked files and the list of untracked files, as one hash.
# Used to notice a patch that ran fine but changed nothing, which usually
# means its anchor no longer matches upstream code.
tree_state(){
	{
		git -C "$srcdir" diff HEAD --binary
		git -C "$srcdir" ls-files --others --exclude-standard
	} | sha1sum
}

# Applies every patch file directly inside $1, sorted by name.
# Appends "<name>\t<applied|no-change>" lines to $2.
apply_patch_dir(){
	local dir="$1" log="$2" f name before
	[ -d "$dir" ] || return 0

	local files=()
	while IFS= read -r f; do
		files+=("$f")
	done < <(find "$dir" -maxdepth 1 -type f \( -name '*.patch' -o -name '*.diff' -o -name '*.py' -o -name '*.sh' \) | LC_ALL=C sort)

	if [ "${#files[@]}" -eq 0 ]; then
		echo "No patches in ${dir#"$rootdir"/}"
		return 0
	fi

	for f in "${files[@]}"; do
		name="${f#"$PATCH_DIR"/}"
		echo "---- Applying $name"
		before="$(tree_state)"
		case "$f" in
		*.patch|*.diff)
			if git -C "$srcdir" apply --check "$f" 2>/dev/null; then
				git -C "$srcdir" apply "$f"
			elif (cd "$srcdir" && patch -p1 -N --dry-run --silent < "$f" >/dev/null 2>&1); then
				echo "git apply refused $name, applying with patch (fuzz)"
				(cd "$srcdir" && patch -p1 -N < "$f")
			else
				(cd "$srcdir" && git apply --check -v "$f") || true
				die "$name does not apply to Mesa $MESA_COMMIT"
			fi
			;;
		*.py)
			(cd "$srcdir" && python3 "$f") || die "$name failed"
			;;
		*.sh)
			(cd "$srcdir" && bash "$f") || die "$name failed"
			;;
		esac

		if [ "$(tree_state)" = "$before" ]; then
			warn "$name made no changes (already upstream, or its anchor no longer matches)"
			printf '%s\tno-change\n' "$name" >> "$log"
		else
			printf '%s\tapplied\n' "$name" >> "$log"
		fi
	done
}

build_variant(){
	local variant="$1"
	local suffix="" label=""
	if [ "$variant" != "base" ]; then
		[ -d "$PATCH_DIR/variants/$variant" ] || die "variant '$variant' has no folder patches/variants/$variant"
		suffix="-$variant"
		label=" ($variant)"
	fi

	info "==== Building v$BUILD_VERSION$suffix ===="

	# Every variant starts from the same clean Mesa tree.
	git -C "$srcdir" reset -q --hard HEAD
	git -C "$srcdir" clean -q -fdx

	local patchlog="$OUT_DIR/patches-$variant.txt"
	: > "$patchlog"

	apply_patch_dir "$PATCH_DIR" "$patchlog"
	if [ "$variant" != "base" ]; then
		apply_patch_dir "$PATCH_DIR/variants/$variant" "$patchlog"
	fi

	git -C "$srcdir" diff --stat HEAD | tail -n 1

	if [ "$PATCH_ONLY" = "1" ]; then
		info "PATCH_ONLY=1, skipping compile for $variant"
		return 0
	fi

	compile_mesa "$variant"
	package_zip "$variant" "$suffix" "$label"
}

compile_mesa(){
	local variant="$1"
	builddir="$workdir/build-$variant"
	installdir="$workdir/install-$variant"
	rm -rf "$builddir" "$installdir"

	# Clang from the NDK is also used for the host tools Mesa builds.
	mkdir -p "$workdir/bin"
	ln -sf "$ndk/clang" "$workdir/bin/cc"
	ln -sf "$ndk/clang++" "$workdir/bin/c++"
	export PATH="$workdir/bin:$ndk:$PATH"
	export CC=clang
	export CXX=clang++
	export AR=llvm-ar
	export RANLIB=llvm-ranlib
	export STRIP=llvm-strip
	export OBJDUMP=llvm-objdump
	export OBJCOPY=llvm-objcopy
	export LDFLAGS="-fuse-ld=lld"

	local cc_prefix=""
	if command -v ccache >/dev/null 2>&1; then
		cc_prefix="'ccache', "
	fi

	cat <<EOF >"$workdir/android-aarch64.txt"
[binaries]
ar = '$ndk/llvm-ar'
c = [${cc_prefix}'$ndk/aarch64-linux-android$sdkver-clang']
cpp = [${cc_prefix}'$ndk/aarch64-linux-android$sdkver-clang++', '-fno-exceptions', '-fno-unwind-tables', '-fno-asynchronous-unwind-tables', '--start-no-unused-arguments', '-static-libstdc++', '--end-no-unused-arguments']
c_ld = '$ndk/ld.lld'
cpp_ld = '$ndk/ld.lld'
strip = '$ndk/llvm-strip'
pkg-config = ['env', 'PKG_CONFIG_LIBDIR=$ndk/pkg-config', '/usr/bin/pkg-config']

[host_machine]
system = 'android'
cpu_family = 'aarch64'
cpu = 'armv8'
endian = 'little'
EOF

	cat <<EOF >"$workdir/native.txt"
[build_machine]
c = [${cc_prefix}'clang']
cpp = [${cc_prefix}'clang++']
ar = 'llvm-ar'
strip = 'llvm-strip'
c_ld = 'ld.lld'
cpp_ld = 'ld.lld'
system = 'linux'
cpu_family = 'x86_64'
cpu = 'x86_64'
endian = 'little'
EOF

	echo "Configuring ..."
	(cd "$srcdir" && meson setup "$builddir" \
		--cross-file "$workdir/android-aarch64.txt" \
		--native-file "$workdir/native.txt" \
		--prefix "$installdir" \
		-Dbuildtype=release \
		-Db_lto=false \
		-Dstrip=true \
		-Dplatforms=android \
		-Dvideo-codecs= \
		-Dplatform-sdk-version="$platform_sdkver" \
		-Dandroid-stub=true \
		-Dgallium-drivers= \
		-Dvulkan-drivers=freedreno \
		-Dvulkan-beta=true \
		-Dfreedreno-kmds=kgsl \
		-Degl=disabled \
		-Dandroid-libbacktrace=disabled)

	echo "Compiling ..."
	ninja -C "$builddir" install

	[ -f "$installdir/lib/libvulkan_freedreno.so" ] || die "build failed, libvulkan_freedreno.so not found"
}

package_zip(){
	local variant="$1" suffix="$2" label="$3"
	local libdir="$installdir/lib"
	local zipname="$ZIP_PREFIX-v$BUILD_VERSION$suffix.zip"

	# meta.json shows "Mesa 26.3.0", not "26.3.0-devel".
	local mesa_short="${MESA_VERSION%%-*}"

	cat <<EOF >"$libdir/meta.json"
{
  "schemaVersion": 1,
  "name": "$DRIVER_NAME v$BUILD_VERSION$suffix",
  "description": "$DRIVER_DESCRIPTION$label",
  "author": "$DRIVER_AUTHOR",
  "packageVersion": "1",
  "vendor": "Mesa",
  "driverVersion": "Mesa $mesa_short Vulkan $VULKAN_VERSION",
  "minApi": 28,
  "libraryName": "libvulkan_freedreno.so"
}
EOF

	echo "Packing $zipname ..."
	(cd "$libdir" && zip -q -j "$OUT_DIR/$zipname" libvulkan_freedreno.so meta.json)
	[ -f "$OUT_DIR/$zipname" ] || die "failed to pack $zipname"
	cat "$libdir/meta.json"
	info "Created $OUT_DIR/$zipname"
}

run_all
