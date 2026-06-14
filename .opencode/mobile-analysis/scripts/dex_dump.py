#!/usr/bin/env python3
"""DEX 内存 dump 工具 — 通过 Frida 从 Android 进程内存中 dump DEX 文件。

使用 frida.Compiler 编译 TypeScript（含 Java bridge），支持全量内存扫描。

用法:
  python dex_dump.py --pid 1234 --output /tmp/dex_output --host 127.0.0.1:6656
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Bridge 项目目录（用于 frida.Compiler 编译 TypeScript）
BRIDGE_PROJECT_DIR = os.path.join(tempfile.gettempdir(), "frida-dex-dump-project")

# TypeScript 模板：全量内存扫描 DEX
# 注意: 此脚本只使用纯 Native API（Memory.scanSync/readByteArray），不需要 Java bridge。
# 但 frida.Compiler 要求至少有一个 import，所以保留 frida-java-bridge import 以触发编译。
# 如果未来 frida.Compiler 支持编译无 import 的 TS，可以移除。
DEX_DUMP_TS = r"""
// frida-java-bridge import 仅用于触发 frida.Compiler 编译，脚本本身不需要 Java API
import Java from "frida-java-bridge";

// DEX magic: "dex\n"
var DEX_MAGIC = [0x64, 0x65, 0x78, 0x0a];
// DEX 文件最大 100MB（超过此大小的匹配很可能是误判）
var MAX_DEX_SIZE = 100 * 1024 * 1024;

function tsLog(msg: string): void {
    var d = new Date();
    var ts = d.getHours() + ":" +
        ("0" + d.getMinutes()).slice(-2) + ":" +
        ("0" + d.getSeconds()).slice(-2) + "." +
        ("00" + d.getMilliseconds()).slice(-3);
    console.log("[" + ts + "] " + msg);
}

function isDexMagic(addr: NativePointer): boolean {
    try {
        var b0 = addr.readU8();
        var b1 = addr.add(1).readU8();
        var b2 = addr.add(2).readU8();
        var b3 = addr.add(3).readU8();
        return b0 === DEX_MAGIC[0] && b1 === DEX_MAGIC[1] &&
               b2 === DEX_MAGIC[2] && b3 === DEX_MAGIC[3];
    } catch (e) {
        return false;
    }
}

function readDexHeader(addr: NativePointer): { fileSize: number, version: string } | null {
    try {
        var magic = addr.readByteArray(8);
        var magicBytes = new Uint8Array(magic as ArrayBuffer);
        var version = String.fromCharCode(magicBytes[4], magicBytes[5], magicBytes[6], magicBytes[7]);
        // file_size at offset 32, uint32 little-endian
        var fileSize = addr.add(32).readU32();
        return { fileSize: fileSize, version: version };
    } catch (e) {
        return null;
    }
}

function dumpDexFromMemory(): void {
    tsLog("开始全量内存扫描 DEX...");
    var ranges = Process.enumerateRanges("r--");
    tsLog("可读内存区域数量: " + ranges.length);

    var dexCount = 0;

    for (var i = 0; i < ranges.length; i++) {
        var range = ranges[i];
        if (range.size < 0x70) continue;  // DEX header 最小 0x70

        try {
            // 逐块搜索 DEX magic
            var matches = Memory.scanSync(range.base, range.size, "64 65 78 0a");
            for (var j = 0; j < matches.length; j++) {
                var addr = matches[j].address;
                var header = readDexHeader(addr);
                if (header === null) continue;
                if (header.fileSize < 0x70 || header.fileSize > MAX_DEX_SIZE) continue;

                try {
                    var dexData = addr.readByteArray(header.fileSize);
                    if (dexData === null) continue;

                    dexCount++;
                    tsLog("[DEX #" + dexCount + "] addr=" + addr.toString() +
                          " size=" + header.fileSize + " version=" + header.version);

                    // 发送 DEX 数据到 Python
                    send({ type: "dex", index: dexCount, size: header.fileSize, version: header.version, base: addr.toString() },
                         dexData);
                } catch (e) {
                    // 读取失败，跳过
                }
            }
        } catch (e) {
            // 扫描失败，跳过此区域
        }
    }

    tsLog("扫描完成，共找到 " + dexCount + " 个 DEX");
    send({ type: "done", count: dexCount });
}

// 执行
dumpDexFromMemory();
"""


def ensure_bridge_project() -> None:
    """确保 TypeScript 编译所需的项目目录和 npm 依赖存在。"""
    os.makedirs(BRIDGE_PROJECT_DIR, exist_ok=True)

    package_json = os.path.join(BRIDGE_PROJECT_DIR, "package.json")
    if not os.path.isfile(package_json):
        with open(package_json, "w") as f:
            json.dump({"name": "frida-dex-dump", "version": "1.0.0"}, f)

    node_modules = os.path.join(BRIDGE_PROJECT_DIR, "node_modules")
    bridge_path = os.path.join(node_modules, "frida-java-bridge")
    if not os.path.isdir(bridge_path):
        print("[*] 首次运行，安装 frida-java-bridge...", file=sys.stderr)
        result = subprocess.run(
            ["npm", "install", "frida-java-bridge"],
            cwd=BRIDGE_PROJECT_DIR,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"[ERROR] npm install 失败: {result.stderr}", file=sys.stderr)
            sys.exit(1)
        print("[*] frida-java-bridge 安装完成", file=sys.stderr)


def compile_dex_script() -> str:
    """编译 DEX dump TypeScript 脚本，返回 bundle 字符串。"""
    import frida

    ensure_bridge_project()

    ts_path = os.path.join(BRIDGE_PROJECT_DIR, "dex_dump.ts")
    with open(ts_path, "w") as f:
        f.write(DEX_DUMP_TS)

    compiler = frida.Compiler()
    bundle = compiler.build("dex_dump.ts", project_root=BRIDGE_PROJECT_DIR)
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description="DEX 内存 dump 工具")
    parser.add_argument("--pid", type=int, required=True, help="目标进程 PID")
    parser.add_argument("--output", required=True, help="输出目录")
    parser.add_argument("--host", default="127.0.0.1:6656", help="frida-server 地址（默认 127.0.0.1:6656）")
    args = parser.parse_args()

    import frida

    # 创建输出目录
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 编译脚本
    print(f"[*] 编译 TypeScript 脚本...", file=sys.stderr)
    bundle = compile_dex_script()
    print(f"[*] 编译完成，bundle 大小: {len(bundle)} 字节", file=sys.stderr)

    # 连接目标进程
    print(f"[*] 连接 frida-server: {args.host}", file=sys.stderr)
    device = frida.get_device_manager().add_remote_device(args.host)

    print(f"[*] Attach 到 PID {args.pid}...", file=sys.stderr)
    session = device.attach(args.pid)

    # 收集 DEX 数据
    dex_files = []
    scan_done = {"done": False}

    def on_message(message, data):
        if message["type"] == "send":
            payload = message["payload"]
            if payload.get("type") == "dex":
                idx = payload["index"]
                size = payload["size"]
                version = payload["version"]
                base = payload["base"]
                filename = f"classes_{idx}.dex"
                filepath = output_dir / filename

                if data:
                    with open(filepath, "wb") as f:
                        f.write(data)
                    dex_files.append(filepath)
                    print(f"[+] {filename}: {size} bytes (version={version}, base={base})", file=sys.stderr)
                else:
                    print(f"[-] DEX #{idx}: 数据为空 (base={base})", file=sys.stderr)
            elif payload.get("type") == "done":
                scan_done["done"] = True
                print(f"[*] 扫描完成，共 {payload['count']} 个 DEX", file=sys.stderr)
        elif message["type"] == "error":
            print(f"[ERROR] {message.get('description', message)}", file=sys.stderr)

    script = session.create_script(bundle)
    script.on("message", on_message)
    script.load()

    # 等待扫描完成（事件驱动 + 超时保护）
    max_wait = 120  # 最大等待 120 秒
    elapsed = 0
    while not scan_done["done"] and elapsed < max_wait:
        time.sleep(1)
        elapsed += 1

    if not scan_done["done"]:
        print(f"[WARNING] 扫描超时（{max_wait}s），已收到 {len(dex_files)} 个 DEX", file=sys.stderr)

    print(f"\n[*] 结果: {len(dex_files)} 个 DEX 文件已保存到 {output_dir}", file=sys.stderr)
    for f in sorted(dex_files):
        print(f"    {f.name}: {f.stat().st_size} bytes", file=sys.stderr)

    try:
        session.detach()
    except Exception:
        pass


if __name__ == "__main__":
    main()
