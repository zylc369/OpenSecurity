/**
 * DEX 内存 dump 脚本 — frida CLI 专用。
 *
 * 用法:
 *   frida -H 127.0.0.1:6656 -n com.target.app -l dex_dump.js
 *
 * 注意: frida CLI/REPL 内置 Java bridge，无需 import。
 *       如在 Python SDK 中使用，需通过 frida.Compiler 编译 TypeScript 版本（见 dex_dump.py）。
 */

"use strict";

// DEX magic: "dex\n"
var DEX_MAGIC = [0x64, 0x65, 0x78, 0x0a];
// DEX 文件最大 100MB（超过此大小的匹配很可能是误判）
var MAX_DEX_SIZE = 100 * 1024 * 1024;

function tsLog(msg) {
    var d = new Date();
    var ts = d.getHours() + ":" +
        ("0" + d.getMinutes()).slice(-2) + ":" +
        ("0" + d.getSeconds()).slice(-2) + "." +
        ("00" + d.getMilliseconds()).slice(-3);
    console.log("[" + ts + "] " + msg);
}

function isDexMagic(addr) {
    try {
        return addr.readU8() === DEX_MAGIC[0] &&
               addr.add(1).readU8() === DEX_MAGIC[1] &&
               addr.add(2).readU8() === DEX_MAGIC[2] &&
               addr.add(3).readU8() === DEX_MAGIC[3];
    } catch (e) {
        return false;
    }
}

function readDexHeader(addr) {
    try {
        var magic = addr.readByteArray(8);
        var magicBytes = new Uint8Array(magic);
        var version = String.fromCharCode(
            magicBytes[4], magicBytes[5], magicBytes[6], magicBytes[7]
        );
        var fileSize = addr.add(32).readU32();
        return { fileSize: fileSize, version: version };
    } catch (e) {
        return null;
    }
}

function dumpDexFromMemory() {
    tsLog("开始全量内存扫描 DEX...");
    var ranges = Process.enumerateRanges("r--");
    tsLog("可读内存区域数量: " + ranges.length);

    var dexCount = 0;

    for (var i = 0; i < ranges.length; i++) {
        var range = ranges[i];
        if (range.size < 0x70) continue;

        try {
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
                    tsLog("[DEX #" + dexCount + "] addr=" + addr +
                          " size=" + header.fileSize +
                          " version=" + header.version);

                    // 发送到 host
                    send(
                        {
                            type: "dex",
                            index: dexCount,
                            size: header.fileSize,
                            version: header.version
                        },
                        dexData
                    );
                } catch (e) {
                    // 读取失败，跳过
                }
            }
        } catch (e) {
            // 扫描失败，跳过
        }
    }

    tsLog("扫描完成，共找到 " + dexCount + " 个 DEX");
    send({ type: "done", count: dexCount });
}

// 执行
dumpDexFromMemory();
