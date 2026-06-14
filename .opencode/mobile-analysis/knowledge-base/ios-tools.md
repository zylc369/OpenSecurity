# iOS 逆向工具安装与 CLI 参考

> 移动端分析 Agent 的 iOS 工具链参考。

## 工具概览

| 工具 | 用途 | 安装方式 |
|------|------|---------|
| otool | Mach-O 文件分析 | macOS 自带 |
| nm | 符号表查看 | macOS 自带 |
| ldid | 伪签名工具 | Homebrew |
| insert_dylib | 动态库注入 | Homebrew (optool) |
| class-dump | ObjC 类信息导出 | GitHub releases（可选） |
| codesign | 代码签名 | macOS 自带 |
| security | 钥匙串/证书管理 | macOS 自带 |

---

## otool — Mach-O 分析

### 常用命令

```bash
# 查看段信息（segments and sections）
otool -l binary

# 查看 Mach-O 头部
otool -h binary

# 反汇编文本段
otool -tV binary

# 查看依赖的动态库
otool -L binary

# 查看加载命令
otool -l binary | grep -A3 LC_LOAD

# 查看指定段内容
otool -s __TEXT __text binary

# 查看ObjC类信息
otool -oV binary
```

### 典型分析场景

| 场景 | 命令 |
|------|------|
| 初次分析 Mach-O | `otool -h binary` → `otool -L binary` → `otool -l binary` |
| 查看架构 | `otool -h binary`（看 magic 和 cputype） |
| 分析依赖库 | `otool -L binary` → 识别 Frameworks |
| 定位 ObjC 方法 | `otool -oV binary` → 搜索方法名 |

---

## nm — 符号表查看

### 常用命令

```bash
# 列出所有符号
nm binary

# 仅显示外部符号（导出的）
nm -gU binary

# 显示符号类型和大小
nm -S binary

# 按地址排序
nm -n binary

# 查找特定符号
nm -gU binary | grep "ClassName"

# 模糊搜索（如搜索含 "decrypt" 的符号）
nm -gU binary | grep -i decrypt

# 去除扁平命名空间（C++ mangled name demangling）
nm -gU binary | c++filt
```

---

## ldid — 伪签名工具

### 安装

```bash
brew install ldid
```

### 常用命令

```bash
# 伪签名（使修改后的二进制可运行）
ldid -S binary

# 使用 entitlements 签名
ldid -Sentitlements.plist binary

# 查看 entitlements
ldid -e binary
```

### Entitlements plist 示例

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>get-task-allow</key>
    <true/>
    <key>platform-application</key>
    <true/>
</dict>
</plist>
```

---

## optool — 动态库注入

### 安装

```bash
brew install optool
```

### 常用命令

```bash
# 注入动态库加载命令
optool install -c load -p @executable_path/Frameworks/hook.dylib -t target_binary

# 移除加载命令
optool uninstall -p @executable_path/Frameworks/hook.dylib -t target_binary

# 查看已注入的库
otool -L target_binary | grep Frameworks
```

> 注意: `insert_dylib` 是旧工具，`optool` 是现代替代。

---

## class-dump — ObjC 类信息导出（可选）

### 安装

class-dump 没有Homebrew 包，需从 GitHub 手动安装：

```bash
# 下载
wget https://github.com/nygard/class-dump/releases/download/3.5/class-dump-3.5.darwin -O /usr/local/bin/class-dump
chmod +x /usr/local/bin/class-dump
```

### 常用命令

```bash
# 导出所有头文件
class-dump -H binary -o headers/

# 查看指定类的方法
class-dump binary | grep -A 20 "ClassName"
```

> class-dump 仅适用于 ObjC 二进制。Swift 类信息有限（大部分 Swift 方法不会出现在 ObjC 元数据中）。

---

## macOS 自带工具

### codesign

```bash
# 查看签名信息
codesign -dvvv binary

# 验证签名
codesign -v binary

# 移除签名
codesign --remove-signature binary

# 重新签名
codesign -s - binary
```

### security

```bash
# 查看钥匙串中的证书
security find-identity -v -p codesigning

# 导出证书
security find-certificate -c "Certificate Name" -p > cert.pem
```

---

## IPA 结构参考

IPA 解压后的标准结构：

```
Payload/
└── AppName.app/
    ├── Info.plist            # 应用配置
    ├── AppName               # 主二进制（Mach-O）
    ├── Frameworks/           # 嵌入的动态库
    │   ├── SomeLib.framework/
    │   └── AnotherLib.dylib
    ├── Resources/            # 资源文件
    │   ├── *.nib             # Interface Builder 文件
    │   ├── *.storyboardc     # Storyboard 编译文件
    │   └── Assets.car        # 资源打包
    ├── PlugIns/              # 应用扩展
    ├── _CodeSignature/       # 代码签名
    │   └── CodeResources
    └── embedded.mobileprovision  # 描述文件
```

### 初次分析 IPA 流程

```bash
# 1. 解压
unzip target.ipa -d ipa_unpacked

# 2. 定位主二进制
MAIN_BIN=$(find ipa_unpacked/Payload -type f -not -name "*.plist" -not -name "*.strings" -not -path "*/Frameworks/*" -not -path "*/_CodeSignature/*" -not -path "*/Resources/*" -not -path "*/PlugIns/*" | head -1)

# 3. 分析
otool -h "$MAIN_BIN"            # 架构
otool -L "$MAIN_BIN"            # 依赖库
nm -gU "$MAIN_BIN" | head -50   # 导出符号
```
