#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess
import urllib.request
import re

WSA_7Z_URL = "https://github.com/MustardChef/WSABuilds/releases/download/Windows_11_2407.40000.4.0_LTS_8/WSA_2407.40000.4.0_x64_Release-Nightly-NoGApps-NoAmazon.7z"
NDK_12_URL = "https://raw.githubusercontent.com/zhouziyang/libndk_translation/master/libndk_translation-12.0.0.tar"
NDK_11_URL = "https://raw.githubusercontent.com/zhouziyang/libndk_translation/master/libndk_translation-11.0.0.tar"

def run(cmd, check=True):
    print(f"[RUN] {cmd}")
    res = subprocess.run(cmd, shell=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed (code {res.returncode}): {cmd}")

def download(url, out_path):
    print(f"[DOWNLOAD] {url} -> {out_path}")
    if os.path.exists(out_path):
        print("  Already exists, skipping download.")
        return
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp, open(out_path, "wb") as f:
        shutil.copyfileobj(resp, f)
    print("  Done.")

def main():
    root_dir = os.path.dirname(os.path.abspath(__file__))
    work_dir = os.path.join(root_dir, "work")
    os.makedirs(work_dir, exist_ok=True)
    os.chdir(work_dir)

    # 1. Download base WSA 7z
    wsa_7z = os.path.join(work_dir, "wsa_base.7z")
    download(WSA_7Z_URL, wsa_7z)

    # 2. Extract system.vhdx (flat extract with -r)
    print("[EXTRACT] Extracting system.vhdx from WSA...")
    run(f"7z e -y {wsa_7z} system.vhdx -r")
    if not os.path.exists("system.vhdx"):
        raise FileNotFoundError("system.vhdx not found in WSA package!")

    # 3. Download libndk_translation tarballs
    download(NDK_11_URL, "libndk_11.tar")
    download(NDK_12_URL, "libndk_12.tar")

    # 4. Convert VHDX to raw ext4
    print("[CONVERT] Converting system.vhdx -> system.raw...")
    run("qemu-img convert -f vhdx -O raw system.vhdx system.raw")

    # 5. Expand raw image by 512MB
    print("[EXPAND] Expanding filesystem by 512MB...")
    run("truncate -s +512M system.raw")
    run("e2fsck -f -y system.raw || true")
    run("resize2fs system.raw")

    # 6. Mount filesystem
    mnt_dir = "/mnt/system"
    os.makedirs(mnt_dir, exist_ok=True)
    run(f"mount -o loop,rw system.raw {mnt_dir}")

    try:
        # 7. Extract libndk_translation (11 first, then 12 so 12 overwrites with Android 13 versions)
        print("[INJECT] Extracting libndk_11.tar (32-bit)...")
        run(f"tar -xf libndk_11.tar -C {mnt_dir}")
        print("[INJECT] Extracting libndk_12.tar (64-bit Android 13)...")
        run(f"tar -xf libndk_12.tar -C {mnt_dir}")

        # 8. Modify /mnt/system/system/build.prop
        build_prop = os.path.join(mnt_dir, "system", "build.prop")
        print(f"[PATCH] Patching {build_prop}...")
        with open(build_prop, "r", encoding="utf-8") as f:
            content = f.read()

        # Replace ro.dalvik.vm.native.bridge
        if "ro.dalvik.vm.native.bridge=0" in content:
            content = content.replace("ro.dalvik.vm.native.bridge=0", "ro.dalvik.vm.native.bridge=libndk_translation.so")
        elif "ro.dalvik.vm.native.bridge" in content:
            content = re.sub(r"ro\.dalvik\.vm\.native\.bridge=.*", "ro.dalvik.vm.native.bridge=libndk_translation.so", content)
        else:
            content += "\nro.dalvik.vm.native.bridge=libndk_translation.so\n"

        extra_props = [
            "ro.enable.native.bridge.exec=1",
            "ro.dalvik.vm.isa.arm=x86",
            "ro.dalvik.vm.isa.arm64=x86_64",
            "ro.ndk_translation.version=0.2.3"
        ]
        for prop in extra_props:
            key = prop.split("=")[0]
            if key not in content:
                content += f"\n{prop}\n"

        with open(build_prop, "w", encoding="utf-8") as f:
            f.write(content)

        # 9. Set permissions and SELinux contexts
        print("[SELINUX] Setting ownership and security.selinux contexts...")
        run(f"chown -R 0:0 {mnt_dir}")

        system_dir = os.path.join(mnt_dir, "system")
        for root, dirs, files in os.walk(system_dir):
            for d in dirs:
                full_d = os.path.join(root, d)
                if os.path.islink(full_d):
                    continue
                try:
                    os.chmod(full_d, 0o755)
                    os.setxattr(full_d, "security.selinux", b"u:object_r:system_file:s0\x00", follow_symlinks=False)
                except Exception:
                    pass

            for f in files:
                full_f = os.path.join(root, f)
                if os.path.islink(full_f):
                    continue
                rel = os.path.relpath(full_f, system_dir).replace("\\", "/")
                
                try:
                    if rel.startswith("bin/"):
                        os.chmod(full_f, 0o755)
                        ctx = b"u:object_r:system_file:s0\x00"
                    elif rel.startswith("lib64/") or rel.startswith("lib/"):
                        os.chmod(full_f, 0o644)
                        ctx = b"u:object_r:system_lib_file:s0\x00"
                    else:
                        os.chmod(full_f, 0o644)
                        ctx = b"u:object_r:system_file:s0\x00"

                    os.setxattr(full_f, "security.selinux", ctx, follow_symlinks=False)
                except Exception as e:
                    print(f"Warning: could not process {full_f}: {e}")

        print("[INJECT] Complete.")

    finally:
        print("[UNMOUNT] Unmounting...")
        run(f"umount {mnt_dir}")

    # 10. Check filesystem integrity
    run("e2fsck -f -y system.raw || true")

    # 11. Convert back to VHDX
    out_vhdx = os.path.join(root_dir, "system.vhdx")
    print(f"[CONVERT] Converting system.raw -> {out_vhdx}...")
    run(f"qemu-img convert -f raw -O vhdx -o subformat=dynamic system.raw {out_vhdx}")

    # 12. Compress to 7z
    out_7z = os.path.join(root_dir, "system_ndk_translation.7z")
    print(f"[COMPRESS] Compressing to {out_7z}...")
    run(f"7z a -mx=6 {out_7z} {out_vhdx}")

    print("[SUCCESS] Build finished successfully!")

if __name__ == "__main__":
    main()
