#!/usr/bin/env python3
"""
命令行 APK 构建工具

从 Android 源码目录（含 AndroidManifest.xml + Java 源码 + res 资源）
一键构建签名 APK，无需 Gradle。

用法:
    python build_apk.py --src <源码目录> --output <输出 APK 路径> [选项]

自动检测:
    - ANDROID_HOME 环境变量 → 查找 SDK
    - 最新 build-tools 版本
    - 最新 platform android.jar
    - debug.keystore 位置

构建流程:
    aapt2 compile → aapt2 link → javac → d8 → zip → zipalign → apksigner
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def log(msg: str):
    print(f"[build_apk] {msg}", flush=True)


def error(msg: str):
    print(f"[build_apk] ERROR: {msg}", file=sys.stderr, flush=True)


def run(cmd: list[str], desc: str = "") -> subprocess.CompletedProcess:
    """执行命令，失败时终止并输出错误信息。"""
    if desc:
        log(desc)
    log(f"  $ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        error(f"命令失败 (exit {result.returncode}): {' '.join(str(c) for c in cmd)}")
        if result.stdout:
            error(f"  stdout: {result.stdout[:2000]}")
        if result.stderr:
            error(f"  stderr: {result.stderr[:2000]}")
        sys.exit(1)
    return result


def find_android_sdk() -> Path:
    """查找 Android SDK 路径。"""
    # 优先使用环境变量
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if sdk and Path(sdk).is_dir():
        return Path(sdk)
    # 常见默认路径
    candidates = [
        Path.home() / "Library" / "Android" / "sdk",       # macOS
        Path.home() / "Android" / "Sdk",                     # Linux (Android Studio)
        Path.home() / "AppData" / "Local" / "Android" / "sdk",  # Windows
    ]
    for c in candidates:
        if c.is_dir():
            return c
    error("未找到 Android SDK。请设置 ANDROID_HOME 环境变量。")
    sys.exit(1)


def find_latest_dir(base: Path) -> Path:
    """在目录中找到版本号最大的子目录。"""
    dirs = sorted([d for d in base.iterdir() if d.is_dir()], reverse=True)
    if not dirs:
        error(f"目录为空: {base}")
        sys.exit(1)
    return dirs[0]


def find_build_tools(sdk: Path) -> Path:
    """找到最新 build-tools 目录。"""
    bt_dir = sdk / "build-tools"
    if not bt_dir.is_dir():
        error(f"build-tools 目录不存在: {bt_dir}")
        sys.exit(1)
    latest = find_latest_dir(bt_dir)
    log(f"使用 build-tools: {latest.name}")
    return latest


def find_platform_jar(sdk: Path, min_api: int = 30) -> Path:
    """找到最新 platform android.jar。"""
    platforms_dir = sdk / "platforms"
    if not platforms_dir.is_dir():
        error(f"platforms 目录不存在: {platforms_dir}")
        sys.exit(1)
    # 按版本号排序，选最新且 >= min_api
    valid = []
    for d in platforms_dir.iterdir():
        if d.is_dir() and d.name.startswith("android-"):
            try:
                api = int(d.name.split("-")[1])
                if api >= min_api:
                    jar = d / "android.jar"
                    if jar.exists():
                        valid.append((api, jar))
            except ValueError:
                continue
    if not valid:
        error(f"未找到 API >= {min_api} 的 platform android.jar")
        sys.exit(1)
    valid.sort(reverse=True)
    _, jar = valid[0]
    log(f"使用 platform: {jar.parent.name}")
    return jar


def find_debug_keystore() -> Path:
    """找到 debug.keystore。"""
    ks = Path.home() / ".android" / "debug.keystore"
    if ks.exists():
        return ks
    return ks  # 不存在时后续会自动创建


def collect_java_sources(src_dir: Path) -> list[Path]:
    """递归收集所有 .java 文件。"""
    return list(src_dir.rglob("*.java"))


def main():
    parser = argparse.ArgumentParser(
        description="命令行 APK 构建工具（无需 Gradle）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --src ./MyApp --output myapp.apk
  %(prog)s --src ./MyApp --output myapp.apk --keystore my-key.jks --ks-pass pass123
        """,
    )
    parser.add_argument("--src", required=True, help="源码根目录（含 app/src/main/）")
    parser.add_argument("--output", required=True, help="输出 APK 文件路径")
    parser.add_argument("--min-api", type=int, default=24, help="最低 API 级别（默认 24）")
    parser.add_argument("--keystore", help="签名 keystore 路径（默认 debug.keystore）")
    parser.add_argument("--ks-pass", default="android", help="keystore 密码（默认 android）")
    parser.add_argument("--ks-alias", default="androiddebugkey", help="key 别名")
    parser.add_argument("--key-pass", default="android", help="key 密码")
    parser.add_argument("--keep-build", action="store_true", help="保留中间构建目录")
    parser.add_argument("--java-version", default="1.8", help="Java 编译版本（默认 1.8）")

    args = parser.parse_args()

    src_dir = Path(args.src).resolve()
    output_apk = Path(args.output).resolve()

    if not src_dir.is_dir():
        error(f"源码目录不存在: {src_dir}")
        sys.exit(1)

    # 检测标准 Android 项目结构
    main_dir = src_dir / "app" / "src" / "main"
    if main_dir.is_dir():
        manifest = main_dir / "AndroidManifest.xml"
        java_dir = main_dir / "java"
        res_dir = main_dir / "res"
    else:
        # 扁平结构（源码目录直接包含 Manifest 和 java/）
        manifest = src_dir / "AndroidManifest.xml"
        java_dir = src_dir / "java"
        res_dir = src_dir / "res"

    if not manifest.exists():
        error(f"AndroidManifest.xml 不存在: {manifest}")
        sys.exit(1)

    log(f"源码目录: {src_dir}")
    log(f"Manifest: {manifest}")
    log(f"输出: {output_apk}")

    # 检测工具链
    sdk = find_android_sdk()
    bt = find_build_tools(sdk)
    platform_jar = find_platform_jar(sdk, min_api=args.min_api)
    keystore = Path(args.keystore) if args.keystore else find_debug_keystore()

    aapt2 = bt / "aapt2"
    d8 = bt / "d8"
    zipalign = bt / "zipalign"
    apksigner = bt / "apksigner"

    # 创建临时构建目录
    build_dir = Path(tempfile.mkdtemp(prefix="apk_build_"))
    log(f"构建目录: {build_dir}")

    try:
        gen_dir = build_dir / "gen"
        obj_dir = build_dir / "obj"
        dex_dir = build_dir / "dex"
        gen_dir.mkdir()
        obj_dir.mkdir()
        dex_dir.mkdir()

        # Step 1: 编译资源
        if res_dir.exists():
            resources_zip = build_dir / "resources.zip"
            run(
                [str(aapt2), "compile", "--dir", str(res_dir), "-o", str(resources_zip)],
                "Step 1/6: 编译资源 (aapt2 compile)",
            )
        else:
            resources_zip = None
            log("Step 1/6: 无 res 目录，跳过资源编译")

        # Step 2: 链接资源 → resources.apk + R.java
        resources_apk = build_dir / "resources.apk"
        link_cmd = [
            str(aapt2), "link",
            "-o", str(resources_apk),
            "--manifest", str(manifest),
            "--java", str(gen_dir),
            "-I", str(platform_jar),
            "--auto-add-overlay",
        ]
        if resources_zip and resources_zip.exists():
            link_cmd.append(str(resources_zip))
        run(link_cmd, "Step 2/6: 链接资源 (aapt2 link)")

        # Step 3: 编译 Java → .class
        java_files = collect_java_sources(java_dir)
        r_java_files = list(gen_dir.rglob("R.java"))
        all_java = java_files + r_java_files

        if not all_java:
            error("未找到 .java 源文件")
            sys.exit(1)

        log(f"Step 3/6: 编译 Java ({len(all_java)} 个文件)")
        run(
            [
                "javac",
                f"-source", args.java_version,
                f"-target", args.java_version,
                "-classpath", str(platform_jar),
                f"-sourcepath", f"{java_dir}:{gen_dir}",
                "-d", str(obj_dir),
            ] + [str(f) for f in all_java],
        )

        # Step 4: .class → .dex
        class_files = list(obj_dir.rglob("*.class"))
        run(
            [str(d8), "--lib", str(platform_jar), "--output", str(dex_dir)]
            + [str(f) for f in class_files],
            "Step 4/6: 转换 DEX (d8)",
        )

        # Step 5: 组装 APK（resources.apk + classes.dex）
        unsigned_apk = build_dir / "unsigned.apk"
        shutil.copy2(resources_apk, unsigned_apk)

        dex_file = dex_dir / "classes.dex"
        if not dex_file.exists():
            error("classes.dex 未生成")
            sys.exit(1)

        run(
            ["zip", "-j", str(unsigned_apk), str(dex_file)],
            "Step 5/6: 组装 APK (zip)",
        )

        # Step 6: 对齐 + 签名
        aligned_apk = build_dir / "aligned.apk"
        run(
            [str(zipalign), "-f", "4", str(unsigned_apk), str(aligned_apk)],
            "Step 6a: 对齐 (zipalign)",
        )

        # 如果 keystore 不存在，先创建
        if not keystore.exists():
            log(f"创建 debug keystore: {keystore}")
            keystore.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    "keytool", "-genkey", "-v",
                    "-keystore", str(keystore),
                    "-storepass", args.ks_pass,
                    "-alias", args.ks_alias,
                    "-keypass", args.key_pass,
                    "-keyalg", "RSA",
                    "-keysize", "2048",
                    "-validity", "10000",
                    "-dname", "CN=Android Debug,O=Android,C=US",
                ],
                capture_output=True, text=True, check=True,
            )

        run(
            [
                str(apksigner), "sign",
                "--ks", str(keystore),
                "--ks-pass", f"pass:{args.ks_pass}",
                "--key-pass", f"pass:{args.key_pass}",
                "--ks-key-alias", args.ks_alias,
                "--out", str(output_apk),
                str(aligned_apk),
            ],
            "Step 6b: 签名 (apksigner)",
        )

        # 验证
        verify = subprocess.run(
            [str(apksigner), "verify", str(output_apk)],
            capture_output=True, text=True,
        )
        if verify.returncode == 0:
            log(f"✅ APK 构建成功: {output_apk}")
            log(f"   大小: {output_apk.stat().st_size:,} bytes")
        else:
            error(f"APK 签名验证失败: {verify.stderr}")
            sys.exit(1)

    finally:
        if not args.keep_build:
            shutil.rmtree(build_dir, ignore_errors=True)
            log(f"清理构建目录: {build_dir}")
        else:
            log(f"保留构建目录: {build_dir}")


if __name__ == "__main__":
    main()
