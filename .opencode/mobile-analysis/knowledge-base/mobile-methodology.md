# 移动端分析方法论

> 多路径分析决策指南。根据分析需求自动选择最佳分析路径。

## APK 结构

```
app.apk (ZIP 格式)
├── AndroidManifest.xml       # 应用清单（权限、组件、入口 Activity）
├── classes.dex               # Dalvik 字节码（主 DEX）
├── classes2.dex ...          # 多 DEX（方法数超 65536 时分包）
├── lib/                      # Native 库
│   ├── arm64-v8a/*.so
│   ├── armeabi-v7a/*.so
│   └── x86_64/*.so
├── res/                      # 编译后的资源
├── assets/                   # 原始资源（WebView、配置文件、证书）
├── META-INF/                 # 签名信息
└── resources.arsc            # 编译后的资源索引
```

**关键文件优先级**:
1. `AndroidManifest.xml` — 权限、入口点、Service/Receiver 注册
2. `lib/*/` — Native 库（.so），需要 IDA Pro 分析
3. `classes*.dex` — Java/Kotlin 逻辑
4. `assets/` — WebView 前端资源、硬编码密钥、配置文件

## IPA 结构

```
Payload/
└── AppName.app/
    ├── Info.plist                # 应用配置
    ├── AppName (Mach-O)          # 主二进制
    ├── Frameworks/               # 嵌入的动态库
    ├── Resources/                # 资源
    ├── PlugIns/                  # 应用扩展
    ├── _CodeSignature/           # 代码签名
    └── embedded.mobileprovision  # 描述文件
```

---

## APK 多路径分析决策树

根据用户的分析需求，选择以下路径之一。**一个需求可能需要组合多条路径**。

```
用户需求
│
├── 路径 1: Java/Kotlin 逻辑分析
│   触发: 分析按钮点击、API 调用、数据流、认证逻辑
│   工具链: apktool 解包 → jadx 反编译 → 源码搜索
│   步骤:
│     1. apktool d app.apk -o unpacked
│     2. jadx -d java_src --deobf app.apk
│     3. 在 java_src/ 中搜索关键字（类名、方法名、字符串）
│     4. 追踪调用链（入口 → 监听器 → 业务逻辑 → 网络/存储）
│   知识库加载: android-tools.md
│
├── 路径 2: Smali 级精读
│   触发: jadx 输出不可读（混淆严重）、需要精确的字节码分析
│   工具链: apktool 解包+反汇编 → smali 代码分析
│   步骤:
│     1. apktool d app.apk -o unpacked（带 smali 输出）
│     2. 在 smali*/ 目录搜索关键类/方法
│     3. 结合 jadx 对照视图（jadx 看大致逻辑，smali 看精确操作）
│   知识库加载: android-tools.md
│
├── 路径 3: Native 层分析（.so）
│   触发: 分析加密算法、保护机制、JNI 函数、native 层逻辑
│   工具链: apktool 解包 → 识别 .so → IDA Pro 分析
│   步骤:
│     1. apktool d -s app.apk -o unpacked（-s 保留 DEX 不反编译，更快）
│     2. 检查 lib/*/ 下的 .so 文件列表
│     3. 选择目标 .so（通常最大的，或与功能相关的）
│     4. 通过 $SHARED_DIR 的 query.py/initial_analysis.py 分析
│   知识库加载: android-tools.md + IDA 知识库（通过 $SHARED_DIR）
│
├── 路径 4: Hybrid/WebView 分析
│   触发: Hybrid App、H5 页面、JS Bridge
│   工具链: apktool 解包 → 检查 assets/ 和 res/
│   步骤:
│     1. apktool d app.apk -o unpacked
│     2. 检查 assets/ 下的 HTML/JS/CSS 文件
│     3. 搜索 JS Bridge 接口（addJavascriptInterface、shouldOverrideUrlLoading）
│     4. 如需抓包 → 使用 mitmproxy/Charles 抓取 HTTPS 流量
│   知识库加载: android-tools.md
│
└── 路径 5: Java ↔ Native 跨层调用（JNI）
      触发: Java 声明 native 方法、JNI_OnLoad、需要跨层追踪
      工具链: jadx + IDA Pro + Frida
      步骤:
        1. jadx -d java_src app.apk → 搜索 native 方法声明
        2. apktool d -s app.apk -o unpacked → 定位 .so
        3. IDA Pro 分析 .so → 找 JNI_OnLoad 和 Java_* 导出
        4. （可选）Frida Hook 验证参数和返回值
      知识库加载: android-tools.md + IDA 知识库 + mobile-frida.md
│
└── 路径 6: Flutter 应用分析
      触发: APK 包含 libflutter.so、flutter_assets/、单 Activity、Dart 代码
      识别特征（满足 2 个以上即可判定）:
        - lib/ 下有 libflutter.so（通常 15-30MB）
        - assets/flutter_assets/ 目录存在
        - assets/flutter_assets/kernel_blob.bin 或 libapp.so 存在
        - AndroidManifest.xml 只有 1 个 Activity（Flutter 管理 UI）
        - jadx 反编译后 Java 代码极少，只有 MainActivity
      工具链: apktool + IDA Pro（arm64 分析）+ Frida
      步骤:
        1. 确认实际运行架构: adb shell uname -m（不是 getprop ro.product.cpu.abi）
        2. 拉取对应架构的 libflutter.so 到本地
        3. IDA Pro 分析 libflutter.so（通常无符号，需要字符串搜索定位函数）
        4. Frida Hook native 层（Java 层 Hook 对 Flutter 无效）
      知识库加载: flutter-ssl-bypass.md + arm64-reverse-methodology.md（$SHARED_DIR）+ mobile-frida.md
      关键注意: Flutter 不走 Java TLS，SSL Pinning bypass 必须在 native 层
```

### jadx-smali 分层分析原则

**触发**: 路径 1（Java）+ 路径 2（Smali）组合使用时，或关键比较/返回值/跳转条件需要精确验证时。

1. **jadx 用于快速理解结构**（类层次、方法签名、变量命名、调用链）
2. **smali 是 ground truth** — 关键公式（比较、返回值、跳转条件）必须在 smali 层验证
3. **jadx 变量映射在高度混淆代码中不可靠**:
   - jadx 可能将不同 smali 寄存器合并为同一 Java 变量
   - jadx 的变量赋值追踪可能丢失循环中的寄存器复用
   - 实际案例: jadx 显示 `j = jIntValue`（用户输入），
     但 smali 中 `v10 = 124750 + jIntValue`（加了一个常量偏移），
     导致公式推导错误，暴力测试全部失败
4. **验证方法**: 在 smali 中搜索关键操作码（rem-long、cmp-long、if-nez 等）
   定位比较点，再追踪参与比较的寄存器来源

### 场景 → 路径映射表

| 用户需求关键词 | 推荐路径 | 加载知识库 |
|---------------|---------|-----------|
| "加密"、"解密"、"算法"、"保护" | 路径 3（Native） | android-tools.md + IDA 知识库 |
| "登录"、"认证"、"验证"、"Token" | 路径 1（Java）→ 可能 5（JNI） | android-tools.md |
| "按钮"、"点击"、"界面逻辑"、"Activity" | 路径 1（Java） | android-tools.md |
| "证书固定"、"SSL Pinning"、"HTTPS" | 路径 1（Java）+ mobile-patterns.md | android-tools.md + mobile-patterns.md |
| "混淆"、"ProGuard"、"不可读" | 路径 2（Smali） | android-tools.md |
| "WebView"、"H5"、"Hybrid"、"前端" | 路径 4（Hybrid） | android-tools.md |
| "JNI"、"native方法"、"跨层" | 路径 5（JNI） | android-tools.md + IDA 知识库 + mobile-frida.md |
| "Root检测"、"越狱检测"、"反调试" | mobile-patterns.md | android-tools.md + mobile-patterns.md |
| "Hook"、"动态分析"、"运行时" | mobile-frida.md | mobile-frida.md |
| "SO分析"、"native库"、"ELF" | 路径 3（Native） | android-tools.md + IDA 知识库 |
| "Flutter"、"libflutter"、"Dart"、"Flutter应用" | 路径 6（Flutter） | flutter-ssl-bypass.md + mobile-frida.md |

---

## IPA 分析路径

```
用户需求
│
├── 路径 A: Mach-O 分析
│   触发: 所有 IPA 分析的起点
│   工具链: unzip → otool/nm → IDA Pro
│   步骤:
│     1. unzip target.ipa -d ipa_unpacked
│     2. 定位主二进制（Payload/*.app/ 下非 plist/非 framework 的文件）
│     3. otool -h / otool -L / nm -gU 获取基本信息
│     4. 需要深度分析时 → IDA Pro（通过 $SHARED_DIR）
│   知识库加载: ios-tools.md
│
├── 路径 B: Frameworks 分析
│   触发: 分析嵌入的第三方库、自定义 Framework
│   工具链: otool -L → 识别 → 逐个分析
│   步骤:
│     1. otool -L main_binary → 列出所有依赖
│     2. 检查 Frameworks/ 目录
│     3. 可疑 Framework → otool/nm 进一步分析
│     4. 需要深度分析 → IDA Pro
│   知识库加载: ios-tools.md
│
└── 路径 C: ObjC 类信息
      触发: 了解类结构、方法列表、协议实现
      工具链: otool -oV / class-dump
      步骤:
        1. otool -oV main_binary → 查看 ObjC 元数据
        2. （可选）class-dump 导出头文件
        3. 搜索关键类和方法
      知识库加载: ios-tools.md
```

---

## 初始分析检查清单

无论 APK 还是 IPA，初始分析必须完成以下步骤：

### APK 初始分析

```
1. 文件基本信息: file 命令确认 APK 格式
2. 解包: apktool d app.apk -o unpacked
3. AndroidManifest.xml: 权限、入口 Activity、Service/Receiver
4. Native 库: ls lib/*/ → 列出所有 .so
5. 快速反编译: jadx -d java_src app.apk → 浏览包结构
6. 字符串搜索: 在 java_src/ 和 assets/ 中搜索关键字符串
```

### IPA 初始分析

```
1. 文件基本信息: file 命令确认 IPA/ZIP 格式
2. 解压: unzip target.ipa -d ipa_unpacked
3. 定位主二进制: find Payload/ -type f（排除 plist/frameworks）
4. Mach-O 信息: otool -h → 架构, otool -L → 依赖库
5. 符号信息: nm -gU | head -100
6. Frameworks: ls Frameworks/ → 列出嵌入的库
```
