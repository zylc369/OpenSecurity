# 数字取证 CTF 方法论

> 遇到内存镜像/pcap/磁盘镜像/日志取证题时读取。覆盖取证流程与各类取证工具命令。**命令行工具为主**（AI 可执行，避免 GUI 依赖）。不依赖主 prompt 上下文。

---

## 1. 取证类型识别与流程

拿到素材先判断类型再选工具：

| 素材特征 | 类型 | 去读 |
|---------|------|------|
| `.pcap`/`.pcapng` | 网络取证 | §2 |
| 内存镜像（`.raw`/`.vmem`/`.dmp`，常无扩展名，`file` 显示 "Windows dump"/"data"） | 内存取证 | §3 |
| 磁盘镜像（`.dd`/`.E01`/`.img`） | 磁盘取证 | §4 |
| `.evtx`/`/var/log/*`/access.log | 日志分析 | §5 |
| 图像/音频/视频/文档疑似藏数据 | 隐写分析 | `steganography-forensics.md`（专项文件） |
| pcap 加密流量/隐蔽信道/隧道/文件层修复 | 网络取证进阶 | `network-forensics.md`（专项文件，本文件 §2 是基础侦察） |
| 磁盘恢复/加密卷/内存 key/容器云/文件系统修复 | 磁盘内存进阶 | `disk-memory-forensics.md`（专项文件，本文件 §3-§4 是基础） |
| Windows 事件ID/USN/ADS/反取证/MPLog | Windows 专项 | `windows-forensics.md` |
| USB 外设/逻辑分析/显示信号/侧信道/3D 打印 | 硬件信号 | `hardware-signal-forensics.md` |
| 压缩包/混合 | 先解压分类，按内容类型分流 | — |

**通用第一步（任何类型先做）**：
```bash
file <素材>                                          # 确认真实类型
strings -n 8 <素材> | grep -iE "flag|ctf|key|pass"   # 快速捞敏感串
```

---

## 2. 网络取证（pcap）

工具：**tshark**。

**基本侦察**：
```bash
tshark -r cap.pcap                                              # 概览协议分布
tshark -r cap.pcap -Y "http" -T fields -e http.request.uri      # HTTP URI
tshark -r cap.pcap -Y "http.request.method==POST" -T fields -e http.file_data   # POST body
tshark -r cap.pcap --export-objects "http,./out/"               # 导出 HTTP 传输的文件
tshark -r cap.pcap -Y "dns" -T fields -e dns.qry.name           # DNS 查询名
```

**常见考点**：
- **HTTP 文件传输**：`--export-objects` 重组上传/下载的文件
- **凭证提取**：HTTP Basic Auth（`http.authorization`）、POST 表单里 grep `password`
- **TLS 解密**：提供私钥 `tshark -o tls.keys_list:"<ip>,<port>,http,<key.pem>"`；或找 SSLKEYLOGFILE
- **DNS 隧道**：查询名异常长/纯编码（Base64/十六进制）→ 解码藏的数据
- **数据隐藏**：ICMP payload、TCP 序列号、自定义协议字段

**文件 carving（pcap 内嵌文件）**：
```bash
tshark -r cap.pcap --export-objects "smb,./out/"     # SMB 传输文件
tshark -r cap.pcap -z expert                          # 专家信息汇总（告警/错误分组统计）
tshark -r cap.pcap -z follow,tcp,0                    # 命令行追踪流（ASCII 流还原）
tshark -r cap.pcap -z conv,ip                          # IP 会话统计（谁和谁聊最多）
# 捕获过滤器（BPF，-f 抓包时）与显示过滤器（-Y 读包时）语法不同: BPF=`tcp port 80 and host 1.2.3.4`; 显示=`tcp.port==80 && ip.addr==1.2.3.4`
tshark -r cap.pcap --export-objects http,out_http       # HTTP 传输文件导出（pcap 场景首选）
```

---

## 3. 内存取证（Volatility 3）

工具：**Volatility 3**（随 $PYTHON_CMD 环境提供，调用 `$(dirname $PYTHON_CMD)/vol`；v3 自动识别 profile，无需像 v2 手动指定）。

**Windows 镜像常用插件**：
```bash
$(dirname $PYTHON_CMD)/vol -f mem.raw windows.info                                    # OS 版本/架构
$(dirname $PYTHON_CMD)/vol -f mem.raw windows.pslist                                  # 进程列表
$(dirname $PYTHON_CMD)/vol -f mem.raw windows.pstree                                  # 进程树（看父子异常）
$(dirname $PYTHON_CMD)/vol -f mem.raw windows.netscan                                 # 网络连接（找 C2）
$(dirname $PYTHON_CMD)/vol -f mem.raw windows.cmdline                                 # 各进程命令行
$(dirname $PYTHON_CMD)/vol -f mem.raw windows.filescan | grep -iE "flag|\.txt|\.zip"  # 扫文件名
$(dirname $PYTHON_CMD)/vol -f mem.raw windows.dumpfiles --pid <PID>                   # 提取某进程文件
$(dirname $PYTHON_CMD)/vol -f mem.raw windows.hashdump                                # SAM 密码哈希
$(dirname $PYTHON_CMD)/vol -f mem.raw windows.registry.printkey --key "SAM\\Domains\\Account"  # 注册表
$(dirname $PYTHON_CMD)/vol -f mem.raw windows.malfind --pid <PID>                     # 检测注入代码（malware）
```

**Linux 镜像**：插件前缀换 `linux.`（`linux.pslist`/`linux.netscan`/`linux.bash` 等）。

**常见考点**：
- **恶意进程**：pstree 找异常父子（如 svchost 的父进程不是 services.exe）；malfind 找注入区
- **凭证**：hashdump（Windows 密码哈希）；浏览器/IM 进程内存里 grep
- **隐藏 flag**：filescan + dumpfiles 按文件名/类型提取
- **命令历史**：Linux `linux.bash`；Windows `cmdline` + 注册表 `UserAssist`/`Shellbags`
- **网络行为**：netscan 找外连 IP/端口

---

## 4. 磁盘/文件系统取证

AI 用命令行（autopsy 是 GUI，不便自动化）。

**文件 carving（按 magic 提取，含已删文件）**：
```bash
$(dirname $PYTHON_CMD)/binwalk -e firmware.bin   # 固件/嵌入文件系统提取（签名库扫描+递归解包，覆盖通用 carving）
$(dirname $PYTHON_CMD)/binwalk --dd=".*" image.dd  # 按签名提取全部嵌入文件（含已删文件的 magic 级恢复）
```

**挂载只读分析**：
```bash
mount -o ro,loop image.dd /mnt           # ext/通用
mount -o ro,loop,show_sys_files -t ntfs-3g image.dd /mnt   # NTFS（含 $MFT 等）
```

**Windows artifact（解析注册表 hive：SAM/SYSTEM/SOFTWARE/NTUSER.DAT）**：
- 工具：python-registry（随 $PYTHON_CMD 环境提供; `import Registry; Registry.Registry(hive)` 程序化解析）
- 关键键：`UserAssist`（程序执行记录）、`Shellbags`（浏览过的文件夹）、`Run`/`RunOnce`（持久化）、`MountedDevices`
- 捞串：`strings -n 8 NTUSER.DAT | grep -iE "flag|recent"`

**常见考点**：已删文件（carving）、注册表痕迹、NTFS 备用数据流（ADS：`file:stream`）、隐藏分区、文件时间戳篡改（MFT `$STANDARD_INFORMATION` vs `$FILE_NAME`）。

---

## 5. 日志分析

**Windows 事件日志（`.evtx`）**：
```bash
python-evtx 解析（$PYTHON_CMD 环境: `from Evtx.Evtx import Evtx; Evtx(path).records()` 逐条 record; evtx_dump 为 Rust 等效外部 CLI） security.evtx > sec.xml        # 转 XML（python-evtx 或 evtx-dump）
grep -iE "4624|4625|4688|4698" sec.xml
```
关键事件 ID：
- `4624`/`4625`：登录成功/失败（爆破：大量 4625）
- `4688`：进程创建（命令执行审计）
- `4698`：计划任务创建（持久化）
- `7045`：服务创建（持久化/恶意服务）

**Web 日志（access.log）**：
```bash
grep -iE "union|select|%3Cscript|cmd=|wget|curl" access.log   # SQLi/XSS/RCE 痕迹
awk '{print $1}' access.log | sort |uniq -c | sort -rn        # IP 频次（扫描识别）
```

**盲注日志还原**（攻击已完成、从日志反推被拖出的数据）: 布尔盲注日志形如 `...ORD(RDER BY flag LIMIT 0,1),(N,1))>V HTTP/1.1" 200 LEN`——正则提取三元组（字符位 N/比较值 V/响应长度 LEN）: 响应长度与"正确页"一致则真实 ascii=V+1、否则=V; 全部字符位按 N 排序后 `chr()` 拼接即明文。`re.findall(r'%2C(\d+)%2C1%29%29%3E(\d+).*? 200 (\d+)', line)` + 以 LEN 区分真假页。

**扫描器 UA/请求指纹**（应急响应定性攻击工具）: awvs→`http contains "acunetix"`（或 wvs）/ netsparker→"netsparker" / appscan→"Appscan" / nessus→"nessus" / sqlmap→"sqlmap"。

**应急响应流量/日志搜索套路**（问什么搜什么）: 黑客后台→`http contains "admin"`; webshell→搜 eval/base64 POST; robots 泄露→"Disallow"; 数据库凭据→"dbhost"; 网卡配置→"eth0"; VPN/CC 地址→统计→端点按流量排序; 暴力枚举范围→`tcp.connection.syn and ip.src==攻击者IP`; telnet 登录信息→`ip.addr==攻击者 and telnet contains "login"`。

**中国菜刀 webshell 流量特征**（pcap 取证解码）: POST 参数典型三元组 `z1`=目标主机名+连接用户名+数据库密码（以自定义分隔符拼接，分隔符看 webshell 源码 `$ar = explode("分隔符", $conf)` 得知）/ `z2`=库名 / `z3`=base64 的 SQL 语句（`c2VsZWN0...` 解码即 `select ...`）; 抓到 z1 串后按分隔符切开即得数据库凭据，无需解密。登录成功判别: 同一批 POST 中响应长度显著异于其余（如 75x vs 4xx）的即成功登录。中文乱码处理: 追踪 TCP 流→显示"原始数据"→save as 文本。

**Linux 日志**：`/var/log/auth.log`（登录/sudo/SSH）、`/var/log/syslog`、`/var/log/cron`、`.bash_history`。

**常见考点**：攻击时间线还原、爆破识别、Web 攻击特征定位、持久化机制。

---

## 6. 恶意样本提取与联动（衔接 binary 逆向）

取证题常需提取可疑样本 → 逆向。

**流程**：
1. 从内存（`malfind`/`dumpfiles`）或磁盘提取 PE/ELF/脚本/shellcode
2. `file`/`die`（Detect It Easy）识别类型与加壳
3. 逆向分析 → 详见 `$SHARED_DIR/knowledge-base/` 的逆向方法论：
   - 编码规范：`idapython-conventions.md`
   - 去混淆选型：`deobfuscation-selection.md`
   - 加壳处理：`packer-handling.md`

**IOC 关联**：用 hash/字符串/C2 地址串联多处取证证据，还原完整攻击链。

---

## 7. 工具速查

| 工具 | 用途 | 关键命令/插件 |
|------|------|--------------|
| tshark | pcap 分析 | `-r`/`-Y <filter>`/`--export-objects <proto,dir>` |
| vol (Volatility 3) | 内存取证 | `vol -f <dump> windows.<plugin>`；Linux 用 `linux.*` |
| binwalk | 文件 carving/固件提取 | `$(dirname $PYTHON_CMD)/binwalk -e <file>` |
| binwalk | 固件/嵌入文件 | `binwalk -e <file>` |
| strings | 字符串提取 | `strings -n 8 <file>` |
| python-evtx 解析（$PYTHON_CMD 环境: `from Evtx.Evtx import Evtx; Evtx(path).records()` 逐条 record; evtx_dump 为 Rust 等效外部 CLI） | Windows 日志 | `python-evtx 解析（$PYTHON_CMD 环境: `from Evtx.Evtx import Evtx; Evtx(path).records()` 逐条 record; evtx_dump 为 Rust 等效外部 CLI） <evtx>` |
| python-registry | 注册表 hive | `import Registry; Registry.Registry("NTUSER.DAT")` |

**获取**：python 依赖全部在 $PYTHON_CMD 环境（volatility3/binwalk/python-registry/python-evtx/pytsk3/scapy/yara 等）; tshark 为外部工具（`brew install wireshark`），无 tshark 时 pcap 解析用 scapy（$PYTHON_CMD 环境: `from scapy.all import rdpcap`），HTTP 对象导出用 scapy 遍历 tcp.payload 重组。

> autopsy/FTK/X-Ways 是 GUI 工具，AI 自动化优先用上方命令行替代；确需 GUI 时参考 `$SHARED_DIR/knowledge-base/gui-automation.md`。

---
