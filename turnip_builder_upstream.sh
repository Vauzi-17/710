#!/bin/bash -e

#Define variables
green='\033[0;32m'
red='\033[0;31m'
nocolor='\033[0m'
deps="git meson ninja patchelf unzip curl pip flex bison zip glslang glslangValidator"
workdir="$(pwd)/turnip_workdir"
magiskdir="$workdir/turnip_module"
ndkver="android-ndk-r29"
ndk="$workdir/$ndkver/toolchains/llvm/prebuilt/linux-x86_64/bin"
sdkver="34"
mesasrc="https://gitlab.freedesktop.org/mesa/mesa"
srcfolder="mesa"

clear

#There are 4 functions here, simply comment to disable.
#You can insert your own function and make a pull request.
run_all(){
	echo "====== Begin building TU V$BUILD_VERSION! ======"
	check_deps
	prepare_workdir
	build_lib_for_android main tu8_kgsl.patch
}

check_deps(){
	echo "Checking system for required Dependencies ..."
		for deps_chk in $deps;
			do
				sleep 0.25
				if command -v "$deps_chk" >/dev/null 2>&1 ; then
					echo -e "$green - $deps_chk found $nocolor"
				else
					echo -e "$red - $deps_chk not found, can't countinue. $nocolor"
					deps_missing=1
				fi;
			done

		if [ "$deps_missing" == "1" ]
			then echo "Please install missing dependencies" && exit 1
		fi

	echo "Installing python Mako dependency (if missing) ..." $'\n'
		pip install mako &> /dev/null
}

prepare_workdir(){
	echo "Preparing work directory ..." $'\n'
		mkdir -p "$workdir" && cd "$_"

	echo "Downloading android-ndk from google server ..." $'\n'
		curl https://dl.google.com/android/repository/"$ndkver"-linux.zip --output "$ndkver"-linux.zip &> /dev/null
	echo "Exracting android-ndk ..." $'\n'
		unzip "$ndkver"-linux.zip &> /dev/null

	echo "Downloading mesa source ..." $'\n'
		git clone $mesasrc --depth=1 -b main $srcfolder
		cd $srcfolder
#	echo "Pushing TU_VERSION..."
#		echo "#define TUGEN8_DRV_VERSION \"v$BUILD_VERSION\"" > ./src/freedreno/vulkan/tu_version.h
}


build_lib_for_android(){
    echo "==== Building Mesa on $1 branch ===="
    echo "Applying patches... ($2)"
    wget https://github.com/whitebelyash/mesa-tu8/releases/download/patchset-head-v2/$2
    if ! git apply --check $2; then
        echo "Failed to apply $2!"
        exit 1
    fi
    git apply $2

    # Apply A710 patch
    echo "Applying A710 patch..."
    python3 - << 'PYEOF'
import re

filepath = "src/freedreno/common/freedreno_devices.py"
with open(filepath, "r") as f:
    content = f.read()

a710_block = '''
# Adreno 710 - Snapdragon 6 Gen 1 (SM6450)
#
# Confirmed hardware: deviceID=0x07010000, GMEM=512KB, num_ccu=2, Vulkan 1.1.128
#
# ROOT CAUSE OF SYSMEM ARTIFACT (confirmed from tu_cmd_buffer.cc):
#   color_ccu_offset = gmem_size - (num_ccu * sysmem_per_ccu_color_cache_size)
#   depth_ccu_offset = color_ccu_offset - (num_ccu * sysmem_per_ccu_depth_cache_size)
#   a7xx_base sets sysmem_per_ccu_depth_cache_size = 256KB (for A730 4 CCU).
#   On A710 (512KB GMEM, 2 CCU): depth_ccu_offset = -128KB OVERFLOW -> ARTIFACT!
add_gpus([
        GPUId(710),
        GPUId(chip_id=0x07010000, name="FD710"),
        GPUId(chip_id=0xffff07010000, name="FD710"),
    ], A6xxGPUInfo(
        CHIP.A7XX,
        [a7xx_base, a7xx_gen1, GPUProps(
            sysmem_per_ccu_color_cache_size = 128 * 1024,
            sysmem_per_ccu_depth_cache_size = 64 * 1024,
            gmem_ccu_color_cache_fraction = CCUColorCacheFraction.QUARTER.value,
            has_ray_intersection = False,
            ubwc_unorm_snorm_int_compatible = True,
        )],
        num_ccu = 2,
        tile_align_w = 32,
        tile_align_h = 16,
        tile_max_w = 1024,
        tile_max_h = 1024,
        num_vsc_pipes = 32,
        cs_shared_mem_size = 32 * 1024,
        wave_granularity = 2,
        fibers_per_sp = 128 * 2 * 16,
        highest_bank_bit = 16,
        magic_regs = a730_magic_regs,
        raw_magic_regs = a730_raw_magic_regs,
    ))

'''

# Insert before FD725 entry
marker = "        # These are named as Adreno730v3 or Adreno725v1."
if marker not in content:
    # fallback marker
    marker = "        GPUId(chip_id=0x07030002, name=\"FD725\")"

if marker in content:
    content = content.replace(marker, a710_block + marker)
    with open(filepath, "w") as f:
        f.write(content)
    print("A710 patch applied successfully!")
else:
    print("ERROR: Could not find insertion point for A710 patch!")
    exit(1)
PYEOF

    # ... rest of build script
	#git checkout origin/$1
	#Workaround for using Clang as c compiler instead of GCC
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
	GITHASH=$(git rev-parse --short HEAD)

	echo "Generating build files ..." $'\n'
		cat <<EOF >"android-aarch64.txt"
[binaries]
ar = '$ndk/llvm-ar'
c = ['ccache', '$ndk/aarch64-linux-android$sdkver-clang']
cpp = ['ccache', '$ndk/aarch64-linux-android$sdkver-clang++', '-fno-exceptions', '-fno-unwind-tables', '-fno-asynchronous-unwind-tables', '--start-no-unused-arguments', '-static-libstdc++', '--end-no-unused-arguments']
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

		cat <<EOF >"native.txt"
[build_machine]
c = ['ccache', 'clang']
cpp = ['ccache', 'clang++']
ar = 'llvm-ar'
strip = 'llvm-strip'
c_ld = 'ld.lld'
cpp_ld = 'ld.lld'
system = 'linux'
cpu_family = 'x86_64'
cpu = 'x86_64'
endian = 'little'
EOF

		meson setup build-android-aarch64 \
			--cross-file "android-aarch64.txt" \
			--native-file "native.txt" \
			--prefix /tmp/turnip-$1 \
			-Dbuildtype=release \
			-Dstrip=true \
			-Dplatforms=android \
			-Dvideo-codecs= \
			-Dplatform-sdk-version="$sdkver" \
			-Dandroid-stub=true \
			-Dgallium-drivers= \
			-Dvulkan-drivers=freedreno \
			-Dvulkan-beta=true \
			-Dfreedreno-kmds=kgsl \
			-Degl=disabled \
			-Dplatform-sdk-version=36 \
			-Dandroid-libbacktrace=disabled \
			--reconfigure

	echo "Compiling build files ..." $'\n'
		ninja -C build-android-aarch64 install

	if ! [ -a /tmp/turnip-$1/lib/libvulkan_freedreno.so ]; then
		echo -e "$red Build failed! $nocolor" && exit 1
	fi
	echo "Making the archive"
	cd /tmp/turnip-$1/lib
	cat <<EOF >"meta.json"
{
  "schemaVersion": 1,
  "name": "Mesa Turnip v$BUILD_VERSION-$GITHASH",
  "description": "Mesa-git Freedreno/Turnip adapted for AdrenoTools (git $GITHASH)",
  "author": "whitebelyash",
  "packageVersion": "1",
  "vendor": "Mesa",
  "driverVersion": "Vulkan 1.4.335",
  "minApi": 28,
  "libraryName": "libvulkan_freedreno.so"
}
EOF
zip /tmp/mesa-turnip-$1-V$BUILD_VERSION.zip libvulkan_freedreno.so meta.json
cd -
if ! [ -a /tmp/mesa-turnip-$1-V$BUILD_VERSION.zip ]; then
	echo -e "$red Failed to pack the archive! $nocolor"
fi
}

run_all
