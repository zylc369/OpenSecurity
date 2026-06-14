# Android 逆向工具安装与 CLI 参考

> 移动端分析 Agent 的 Android 工具链参考。每个工具包含安装方法、常用命令和典型分析场景。

## 工具概览

| 工具 | 用途 | 定位 |
|------|------|------|
| apktool | APK 解包 + 反汇编（DEX → smali） | **解包+反汇编** |
| jadx | DEX → Java 反编译 | **反编译** |
| adb | Android Debug Bridge | **设备通信** |

> **术语区分**: apktool = 解包 + 反汇编（输出 smali 字节码），jadx = 反编译（输出 Java 源码）。两者互补，不是替代关系。

---

## apktool — APK 解包与反汇编

### 安装

```bash
# macOS
brew install apktool

# Linux
# 从 https://bitbucket.org/iBotPeaches/apktool/downloads/ 下载 jar
sudo wget https://bitbucket.org/iBotPeaches/apktool/downloads/apktool_2.9.3.jar -O /usr/local/bin/apktool.jar
echo '#!/bin/bash\njava -jar /usr/local/bin/apktool.jar "$@"' | sudo tee /usr/local/bin/apktool
sudo chmod +x /usr/local/bin/apktool

# Windows
# 下载 apktool.jar + apktool.bat，放入 PATH 目录
```

### 常用命令

```bash
# 解包 + 反汇编（DEX → smali）
apktool d target.apk -o output_dir

# 解包（不反汇编，仅提取资源）
apktool d -s target.apk -o output_dir

# 重打包
apktool b output_dir -o repackaged.apk

# 解包指定 framework
apktool d target.apk -o output_dir -t framework_tag
```

### 输出结构

```
output_dir/
├── AndroidManifest.xml    # 解码后的清单文件（可读 XML）
├── apktool.yml            # apktool 元数据
├── assets/                # 原始 assets（WebView 资源等）
├── lib/                   # native 库（.so 文件，按架构分子目录）
│   ├── arm64-v8a/
│   ├── armeabi-v7a/
│   └── x86_64/
├── original/              # 原始签名信息
├── res/                   # 解码后的资源文件
└── smali*/                # 反汇编输出（smali 字节码）
    ├── smali/             # classes.dex → smali
    ├── smali_classes2/    # classes2.dex → smali
    └── ...
```

### 典型分析场景

| 场景 | 命令 |
|------|------|
| 初次分析 APK | `apktool d app.apk -o app_unpacked` |
| 混淆严重时精读 smali | `apktool d app.apk -o app_smali`，然后在 smali 目录搜索 |
| 修改资源后重打包 | `apktool b app_unpacked -o new.apk` |

---

## jadx — DEX 反编译器

### 安装

```bash
# macOS
brew install jadx

# Linux
# 从 https://github.com/skylot/jadx/releases 下载最新版
wget https://github.com/skylot/jadx/releases/download/v1.5.1/jadx-1.5.1.zip
unzip jadx-1.5.1.zip -d ~/tools/jadx

# Windows
# 下载 jadx zip，解压，将 bin/ 加入 PATH
```

### 常用命令

```bash
# 反编译为 Java 源码
jadx -d output_dir target.apk

# 反编译指定 DEX
jadx -d output_dir classes.dex

# 启用反混淆
jadx -d output_dir --deobf target.apk

# 输出 JSON 格式（结构化，适合自动化解析）
jadx -d output_dir --json target.apk

# 指定线程数（大 APK 加速）
jadx -d output_dir -j 4 target.apk
```

### 反编译输出结构

```
output_dir/
├── resources/          # 资源文件
└── sources/            # Java 源码（按包名组织）
    └── com/example/app/
        ├── MainActivity.java
        └── ...
```

### 典型分析场景

| 场景 | 命令 |
|------|------|
| 快速获取可读 Java 源码 | `jadx -d java_src app.apk` |
| 混淆 APK 反编译 | `jadx -d java_src --deobf app.apk` |
| 仅需确认类结构 | `jadx -d java_src app.apk` → 搜索 `extends`/`implements` |

---

## adb — Android Debug Bridge

### 安装

```bash
# macOS（通过 Android SDK Platform Tools）
brew install android-platform-tools

# Linux
# 下载 https://developer.android.com/studio/releases/platform-tools
# 或通过 apt: sudo apt install adb

# Windows
# 下载 Android SDK Platform Tools，加入 PATH
```

### 常用命令

```bash
# 设备管理
adb devices                    # 列出已连接设备
adb devices -l                 # 详细信息（含型号）

# 文件操作
adb push local_file /data/local/tmp/    # 推送文件到设备
adb pull /data/local/tmp/file .         # 从设备拉取文件

# Shell
adb shell ls /data/local/tmp/           # 在设备上执行命令
adb shell pm list packages              # 列出已安装包
adb shell pm path com.example.app       # 获取 APK 安装路径
adb shell dumpsys package com.example.app  # 查看包信息（权限、组件等）

# 端口转发（用于 Frida）
adb forward tcp:6655 tcp:6656           # 主机 6655 → 设备 6656
adb forward --list                       # 查看转发规则
adb forward --remove tcp:6655            # 移除转发

# 安装/卸载
adb install app.apk                      # 安装 APK
adb install -r app.apk                   # 覆盖安装
adb uninstall com.example.app            # 卸载

# 日志
adb logcat                               # 实时日志
adb logcat -s TAG                        # 过滤 TAG
adb logcat | grep -i frida               # 过滤 Frida 相关日志
```

### 典型分析场景

| 场景 | 命令组合 |
|------|---------|
| 提取已安装 APK | `adb shell pm path com.app` → `adb pull /path/base.apk .` |
| 端口转发 + Frida | `adb forward tcp:6655 tcp:6656` → 主机端连接 |
| 检查设备架构 | `adb shell getprop ro.product.cpu.abi` |
| 查看应用数据目录 | `adb shell run-as com.example.app ls` |
