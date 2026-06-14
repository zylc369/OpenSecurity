# Android 加固识别与脱壳

> 常见加固方案识别特征 + Frida 内存 dump DEX 的 3 种策略 + 验证步骤。

---

## 常见加固识别特征

### AndroidManifest.xml 特征

| 加固方案 | 特征 |
|---------|------|
| **梆梆加固** | `com.secneo.apkwrapper`（Application 类名）+ `libsecexe.so` / `libsecmain.so` |
| **360 加固** | `com.stub.StubApp`（Application 类名）+ `libjiagu.so` / `libjiagu_art.so` |
| **腾讯乐固** | `com.tencent.StubShell.TxAppEntry`（Application 类名）+ `libshell-super.2019.so` / `libshella-2.10.5.1.so` |
| **爱加密** | `com.ijiami.ijmip`（Application 类名）+ `libijiami.so` |
| **网易易盾** | `com.netease.nis.bugrpt.CrashHandler` + `libnesec.so` |
| **百度加固** | `com.baidu.protect.Interceptor` + `libbaiduprotect.so` |
| **阿里聚安全** | `com.alibaba.wireless.security.open.*` + `libmobisec.so` |
| **腾讯御安全** | `com.tencent.bugly.crashreport.CrashReport` + `libtup.so` |
| **梆梆企业版** | `com.secneo.guard.NeoGuardApplication` + `libneoguard-core.so` |

### 通用判断方法

```bash
# 1. 解包 APK
apktool d app.apk -o unpacked/

# 2. 检查 Application 类名
grep -i "application" unpacked/AndroidManifest.xml | head -5

# 3. 检查 lib/ 目录
ls -la unpacked/lib/*/ | grep -v "^d"

# 4. 检查 classes.dex 大小
# 加固 APK 通常只有一个很小的 classes.dex（壳代码），原始 DEX 被加密存储
ls -la unpacked/classes.dex
```

---

## 脱壳方法论

### 策略 1：maps 扫描（推荐）

**原理**：扫描 `/proc/<pid>/maps` 中的 DEX 文件映射，直接从内存读取。

**优点**：稳定，不依赖 Java Bridge。**缺点**：可能漏掉未被 mmap 映射的 DEX。

```
1. 读取 /proc/<pid>/maps
2. 查找包含 "dex" 或 ".odex" 或 ".vdex" 的内存区域
3. 读取每块区域的前 8 字节，检查 DEX magic（"dex\n035\0" 或 "dex\n036\0" 等）
4. 读取 DEX header 中的 file_size 字段
5. 从基址读取完整 DEX 数据
6. 保存到文件
```

### 策略 2：全量扫描

**原理**：扫描进程全部可读内存区域，逐块搜索 DEX magic。

**优点**：最全面，能找到所有 DEX。**缺点**：耗时较长（大进程可能需要 30-60 秒）。

```
1. Process.enumerateRanges('r--')  获取所有可读内存区域
2. 对每个区域执行 Memory.scan 搜索 DEX magic: "64 65 78 0a"（"dex\n"）
3. 对每个匹配地址读取 DEX header，验证完整性
4. 读取完整 DEX 数据并保存
```

### 策略 3：ClassLoader 枚举

**原理**：通过 Java Bridge 枚举 ClassLoader 加载的所有 DEX。

**优点**：精确，直接对应 ClassLoader 的 DEX。**缺点**：依赖 Java Bridge（frida 17.x Python SDK 需 Compiler 编译）。

```javascript
Java.perform(function() {
    // 获取当前应用的 ClassLoader
    var app = Java.use("android.app.ActivityThread").currentApplication();
    var classLoader = app.getClassLoader();

    // 通过反射获取 DexPathList
    var pathList = Java.cast(
        classLoader.loadClass("dalvik.system.BaseDexClassLoader")
            .getDeclaredField("pathList")
            .get(classLoader),
        Java.use("dalvik.system.DexPathList")
    );

    // 遍历 dexElements
    var dexElements = pathList.dexElements.value;
    for (var i = 0; i < dexElements.length; i++) {
        var dexFile = dexElements[i].dexFile.value;
        // 读取 dexFile 的 cookie 获取内存中的 DEX
    }
});
```

---

## 推荐流程

```
1. 识别加固类型（见上表）
2. 启动 frida-server（$AGENT_DIR/scripts/manage_frida.py --action start）
3. 启动目标 app（等待加固壳解密 DEX）
4. 使用全量扫描 dump DEX（策略 2，最全面）
5. 验证 dump 结果
```

---

## 验证步骤

### 1. 检查 DEX 文件数量和大小

```bash
ls -la output_dir/*.dex
# 预期：多个 DEX，总大小与原 APK 的 classes*.dex 差异大（脱壳后更大）
```

### 2. 验证 DEX 头部

```bash
# 每个 DEX 应以 "dex\n" 开头
xxd output_dir/classes.dex | head -2
# 00000000: 6465 780a 3337 00...  dex.37.
```

### 3. 使用 jadx 反编译验证

```bash
jadx -d java_src output_dir/classes.dex
# 检查反编译结果中是否有业务代码（不是壳代码）
```

### 4. 检查类数量

```bash
# 使用 dexdump
dexdump -f output_dir/classes.dex | grep "class_def" | wc -l
```

---

## frida 17.x 注意事项

- **frida CLI**：可直接加载 JS 脚本（策略 1/2 的 Native 代码不需要 Java bridge）
- **Python SDK**：
  - 策略 1/2（纯 Native）：可用纯 JS 字符串 `session.create_script(js)`
  - 策略 3（Java Bridge）：需用 `frida.Compiler` 编译 TypeScript（详见 `$AGENT_DIR/knowledge-base/frida-17x-bridge.md`）
- 使用 `$AGENT_DIR/scripts/dex_dump.py` 自动化 dump
