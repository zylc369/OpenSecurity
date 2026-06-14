# 移动端 Frida 指南

> 移动端 Frida 的安全部署、设备连接和 Hook 模板。

## 概述

移动端 Frida 与 PC 端的主要差异：
- 需要在设备上部署 frida-server（安全安装）
- Android 需要端口转发（adb forward）
- iOS 通过 USB 直连（无需端口转发）
- 支持语言级 Hook（Java Bridge / Objective-C Bridge）

---

## 安全安装 frida-server

> 基于项目内置的 Frida 管理经验：默认端口和默认文件名极易被检测。

### 原则

1. **随机二进制名**: 不含 "frida" 关键字（如 `x7k2m9`）
2. **随机目录名**: 不含 "frida" 关键字
3. **非默认端口**: 从 6655 起动态分配（不使用 27042）
4. **chmod 755**: 确保可执行

### 推荐方式：使用 manage_frida.py 脚本

```bash
# 一键安装（自动下载 + 随机名 + 随机目录）
$PYTHON_CMD $AGENT_DIR/scripts/manage_frida.py --action install -s <serial>

# 启动（自动分配端口 + 端口转发，输出 JSON）
$PYTHON_CMD $AGENT_DIR/scripts/manage_frida.py --action start -s <serial>

# 检查状态
$PYTHON_CMD $AGENT_DIR/scripts/manage_frida.py --action status -s <serial>

# 停止
$PYTHON_CMD $AGENT_DIR/scripts/manage_frida.py --action stop -s <serial>
```

### 手动安装（备用）

仅在脚本不可用时使用：

```bash
# 1. 确认设备架构
adb shell getprop ro.product.cpu.abi
# 输出示例: arm64-v8a

# 2. 下载对应版本（frida-server 版本必须与 pip frida 版本一致）
# 从 https://github.com/frida/frida/releases 下载 frida-server-<version>-android-arm64.xz

# 3. 生成随机名
RANDOM_NAME=$($PYTHON_CMD -c "import secrets; print(secrets.token_hex(4))")

# 4. 推送到设备（随机目录）
adb push frida-server /data/local/tmp/.tmp_${RANDOM_NAME}/${RANDOM_NAME}
adb shell chmod 755 /data/local/tmp/.tmp_${RANDOM_NAME}/${RANDOM_NAME}

# 5. 启动 frida-server（非默认端口）
adb shell "/data/local/tmp/.tmp_${RANDOM_NAME}/${RANDOM_NAME} -l 0.0.0.0:6656 &"

# 6. 端口转发
adb forward tcp:6655 tcp:6656
```

### iOS frida-server 安装步骤

```bash
# 越狱设备: 通过 Cydia/Loader 安装 frida-server
# 非越狱设备: 需要重新打包 IPA 注入 frida-gadget

# 检查 frida-server 状态
frida-ps -U  # USB 连接的设备
```

---

## 设备连接

### Android 连接流程

```bash
# 1. 检查设备连接
adb devices

# 2. 端口转发（如已配置 frida-server）
adb forward tcp:6655 tcp:6656

# 3. 验证连接
frida-ps -H 127.0.0.1:6655
```

### iOS 连接流程

```bash
# iOS 通过 USB 直连，无需端口转发
# 需要安装 usbmuxd（macOS: brew install usbmuxd）

# 验证连接
frida-ps -U
```

### Frida 连接代码模板

```python
import frida

# Android（通过 adb forward）
device = frida.get_device_manager().add_remote_device("127.0.0.1:6655")

# iOS（通过 USB）
device = frida.get_device_manager().find_device("")  # 空 string 获取 USB 设备

# 列出进程
for proc in device.enumerate_processes():
    print(f"{proc.pid}: {proc.name}")
```

---

## device.json 规范

> device.json 是任务级设备快照，记录当前任务绑定的设备。由 Agent 在首次连接设备时创建，放在 `$TASK_DIR/device.json`。

### Android 设备示例

```json
{
  "device_id": "emulator-5554",
  "device_type": "android",
  "frida_server": {
    "running": true,
    "device_port": 6656,
    "host_port": 6655,
    "binary_name": "x7k2m9"
  }
}
```

### iOS 设备示例

```json
{
  "device_id": "a1b2c3d4e5f6...",
  "device_type": "ios",
  "frida_server": {
    "running": true
  }
}
```

### 字段说明

| 字段 | Android | iOS | 说明 |
|------|---------|-----|------|
| `device_id` | adb 序列号 | UDID | 设备唯一标识 |
| `device_type` | `"android"` | `"ios"` | 由 Agent 根据检测来源自动设置 |
| `frida_server.running` | ✅ | ✅ | frida-server 是否在运行 |
| `frida_server.device_port` | ✅ | ❌ | 设备端监听端口 |
| `frida_server.host_port` | ✅ | ❌ | 主机端映射端口（adb forward） |
| `frida_server.binary_name` | ✅ | ✅ | 随机化的二进制文件名 |

### 设备选择流程

```
首次操作设备时:
1. 执行 adb devices (Android) 或 idevice_id -l (iOS)
2. $TASK_DIR/device.json 不存在 → 进入选择流程
3. 在线设备数 = 0 → 告知用户，提示连接步骤
4. 在线设备数 = 1 → 自动选择，创建 device.json
5. 在线设备数 > 1 → 列出设备，请用户选择
```

### 设备校验（每次操作设备前）

```
1. 读取 device.json 的 device_id
2. 检查设备是否仍在线
3. 不在线 → 告知用户，列出当前在线设备，等待选择
4. 在线 → 继续操作
```

---

## Java Bridge Hook 模板

> 用于 Hook Android Java/Kotlin 方法。
>
> **⚠️ frida 17.x 注意事项**：
> - **frida CLI**: 直接 `frida -H ... -l hook.js` 即可，REPL 内置 Java bridge
> - **Python SDK**: 必须用 `frida.Compiler` 编译 TypeScript（`import Java from "frida-java-bridge"`），详见 `$AGENT_DIR/knowledge-base/frida-17x-bridge.md`
> - **纯 Native Hook（Interceptor）**: 无需 Java bridge，直接 `session.create_script(js_string)` 即可

```javascript
// Hook 指定类的指定方法
Java.perform(function() {
    var ClassName = Java.use("com.example.app.ClassName");

    // Hook 方法（带参数）
    ClassName.methodName.implementation = function(arg1, arg2) {
        console.log("[*] ClassName.methodName called");
        console.log("    arg1: " + arg1);
        console.log("    arg2: " + arg2);

        // 调用原始方法
        var result = this.methodName(arg1, arg2);
        console.log("    result: " + result);

        return result;
    };
});

// Hook 所有重载
Java.perform(function() {
    var ClassName = Java.use("com.example.app.ClassName");
    var overloads = ClassName.methodName.overloads;
    overloads.forEach(function(overload) {
        overload.implementation = function() {
            console.log("[*] ClassName.methodName called with " + arguments.length + " args");
            for (var i = 0; i < arguments.length; i++) {
                console.log("    arg" + i + ": " + arguments[i]);
            }
            var result = this.methodName.apply(this, arguments);
            console.log("    result: " + result);
            return result;
        };
    });
});

// Hook 构造函数
Java.perform(function() {
    var ClassName = Java.use("com.example.app.ClassName");
    ClassName.$init.implementation = function() {
        console.log("[*] new ClassName() called");
        return this.$init.apply(this, arguments);
    };
});

// 搜索并 Hook（类名未知时）
Java.perform(function() {
    Java.enumerateLoadedClasses({
        onMatch: function(className) {
            if (className.indexOf("keyword") !== -1) {
                console.log("[+] Found: " + className);
            }
        },
        onComplete: function() {}
    });
});
```

## Objective-C Bridge Hook 模板

> 用于 Hook iOS ObjC 方法。
>
> **⚠️ frida 17.x 注意事项**：
> - **frida CLI**: 直接 `frida -U -l hook.js` 即可，REPL 内置 ObjC bridge
> - **Python SDK**: 必须用 `frida.Compiler` 编译 TypeScript（`import ObjC from "frida-objc-bridge"`），详见 `$AGENT_DIR/knowledge-base/frida-17x-bridge.md`

```javascript
// Hook ObjC 实例方法
var className = "UIViewController";
var methodName = "- viewDidLoad";
var hook = ObjC.classes[className][methodName];

Interceptor.attach(hook.implementation, {
    onEnter: function(args) {
        console.log("[*] " + className + " " + methodName);
    },
    onLeave: function(retval) {
        // 修改返回值: retval.replace(ptr(0));
    }
});

// Hook ObjC 类方法（+ 开头）
var className = "NSURLSession";
var methodName = "+ sharedSession";
var hook = ObjC.classes[className][methodName];

Interceptor.attach(hook.implementation, {
    onEnter: function(args) {
        console.log("[*] " + className + " " + methodName);
    }
});

// Hook 并读取 NSString 参数
var className = "NSString";
var methodName = "- isEqualToString:";
var hook = ObjC.classes[className][methodName];

Interceptor.attach(hook.implementation, {
    onEnter: function(args) {
        var other = ObjC.Object(args[2]);
        console.log("[*] isEqualToString: " + other.toString());
    }
});
```

---

## 防检测技术

### frida-server 检测与绕过

| 检测方式 | 绕过方法 |
|---------|---------|
| 端口扫描（27042） | 使用非默认端口（6655+） |
| /proc/pid/maps 检查 frida | 重命名 frida-server（随机名） |
| /proc/pid/status 检查 TracerPid | 反反调试 Hook |
| frida-agent.so 特征 | 使用 frida-gadget 注入方式 |
| D-Bus 协议特征 | 使用 frida-gadget + 随机端口 |

### Root/越狱检测绕过

| 检测方式 | 绕过方法 |
|---------|---------|
| su/which su | MagiskSU 隐藏 + Frida Hook `File.exists()` |
| /system/app/Superuser.apk | Magisk Hide / DenyList |
| 检查 SELinux | 通过 adb shell getenforce 确认状态 |
| 检查 Cydia Substrate | 不越狱 / 使用 frida-gadget |

### 设备失联处理

```
frida 连接失败时:
1. 中断当前操作
2. 告知用户设备可能已断开
3. 执行 adb devices (Android) 或 idevice_id -l (iOS)
4. 列出当前可用设备
5. 等待用户重新连接或选择新设备
6. 更新 device.json
```
