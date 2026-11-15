# WSA Google libndk_translation Builder

Automated CI/CD pipeline to inject Google's official `libndk_translation` (Android 13) into Windows Subsystem for Android (WSA x86_64) `system.vhdx`, replacing Intel Houdini directly inside the system image.

## Why?
- Intel Houdini often fails or is blocked by heavily protected/obfuscated applications (such as banking apps like MB Bank, Techcombank, etc.).
- KernelSU / Magisk modules for `libndk_translation` suffer from SELinux restrictions (`tmpfs:s0`), OverlayFS casefold incompatibilities, and delayed `ro.dalvik.vm.native.bridge` propagation during early Zygote startup.
- Baking `libndk_translation` directly into `system.vhdx` guarantees native bridge initialization from boot with correct SELinux attributes (`u:object_r:system_file:s0` and `system_lib_file:s0`).

## How to use
1. Download `system_ndk_translation.7z` from [Releases](https://github.com/hpbzareth/wsa-ndk-builder/releases).
2. Fully terminate WSA (`wsaclient.exe /shutdown`).
3. Backup your original `system.vhdx`.
4. Extract `system.vhdx` into your WSA root folder (e.g. `C:\WSA_2407.40000.4.0_x64`).
5. Launch WSA. User data and installed apps (`userdata.vhdx`) remain completely untouched.
