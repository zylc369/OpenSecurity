# Docker 工具箱: 容器化安装与 AI 调用可行性分析

> 目的: 把"手动清单"中编译类工具迁入容器，AI 通过 PATH wrapper 无感调用。本文档基于 **20 项逐项实测**（非推演），实测环境: macOS Apple Silicon + Docker Desktop 29.7.2 + kalilinux/kali-rolling arm64。
> 结论先行: **可行，且已扫清主要坑**。但有一个架构前提（分层镜像）、三类工具不可容器化、若干 wrapper 层必须处理的陷阱（本文 §2 逐条给出实测证据与修法）。

## 0. 结论速览

| 分类 | 数量 | 判定 |
|------|------|------|
| ✓ 容器内功能完整可用 | 26 | steg 族/取证族/爆破族/hashcat(CPU)/ghidra headless/msfvenom/nxc/wpscan/searchsploit/mingw/gdb(gdbstub 模式)/PHPGGC/one_gadget 等 |
| △ 条件可用（特定镜像/特定模式） | 5 | .NET 工具（需独立 dotnet 镜像）/ responder（仅 Linux 宿主）/ GPU hashcat（仅 Linux+NVidia）等 |
| ✗ 不可容器化 | 9 | Windows 目标侧执行件/WinDbg/IDA 插件类/USB 外设类/宿主进程注入类 |
| 镜像分层 | 3 个 | core ~5.3GB / full ~9.1GB / dotnet 独立 |

## 1. 调用机制实测（AI 调用可靠性的根基）

wrapper 形态: `~/bw-security-analysis/bin/<tool>` → 内部执行 `docker run --rm ... image tool "$@"`。以下每条均已实测:

| # | 机制 | 实测结果 | 处置 |
|---|------|---------|------|
| 1 | 退出码传播 | ✓ `exit 42` 原样透传到宿主机 | AI 判断命令成败不受影响 |
| 2 | stdout/stderr 回传 | ✓ 直接回终端 | 大输出正常 |
| 3 | stdin 管道传入 | ✓ 需 `docker run -i`（wrapper 固定带） | john --stdin 类可用 |
| 4 | 文件读（宿主→容器） | ✓ `-v "$PWD":/work -w /work` | 卷挂载 |
| 5 | 文件写（容器→宿主） | ✓ 写 /work 即落宿主机，**属主正确**（非 root） | `--user` 或 entrypoint 降权保证 |
| 6 | 冷启动开销 | ✓ 0.14s/次（macOS Docker Desktop） | 可忽略 |
| 7 | 卷 I/O 性能 | ✓ VirtioFS 100MB 读 0.31s（原生 0.17s，~2x） | 大镜像（内存 dump GB 级）可接受 |
| 8 | 并发调用 | ✓ docker run 天然隔离 | AI 并行工具调用安全 |

### 1.1 三个必须由 wrapper/镜像处理的陷阱（实测捕获）

**陷阱 ① 孤儿容器**（高危）: 工具忽略 SIGTERM 时（破解/扫描中常见），外层 `timeout` 杀死 docker 客户端后**容器继续运行**（实测: `trap "" TERM; sleep 30` 容器存活）。修法: wrapper 内 `--name <唯一名>` + `trap 'docker kill <名>' EXIT`。

**陷阱 ② --user 无 passwd 条目**（高危）: `docker run --user 501:20` 时容器内无该 uid 的 passwd 记录，`whoami`/`git`/`nuclei`/`lsassy` 等调 `getpwuid` 的工具直接崩（实测: `whoami: cannot find name for user ID 501`）。修法（已验证，uid 无关）: 镜像 ENTRYPOINT 以 root 启动 → 运行时向 /etc/passwd 追加 `u$PUID:x:$PUID:$PGID::/tmp:/bin/sh` → `setpriv --reuid --regid --clear-groups` 降权 exec。wrapper 只需传 `-e PUID=$(id -u) -e PGID=$(id -g)`。

**陷阱 ③ HOME 不可写**（中危）: 降权后 HOME=/ 或缺省 → 依赖配置目录的工具失败。实测: wpscan 缺 DB 时**拒绝扫描**（`Update required`）; NetExec 首跑要在 HOME 建 DB。修法: entrypoint 固定 `HOME=/tmp/home`（可写），wpscan 类需持久 DB 的再加专用卷。注意 ghidra headless 需 `_JAVA_OPTIONS="-Duser.home=/tmp"`。

### 1.2 路径语义（AI 使用面的最大隐患）

容器内看不到宿主机绝对路径。规则:
- wrapper 挂载 `$PWD:/work` 并把参数中 `$PWD` 前缀的绝对路径重写为 `/work/...`（sed 一行）
- AI 在工作目录内操作（相对路径/重写后的绝对路径）→ 零感知
- `$PWD` 之外的路径（如 /var/folders 临时目录）: wrapper 不覆盖——**知识库需写明: 容器工具只吃工作目录内的文件，外部文件先 cp 进 cwd**（这是少数需要 AI 主动配合的点）
- `~/bw-security-analysis/wordlists` 以 ro 挂载到 `/usr/share/wordlists`（kali 工具默认路径）——rockyou 由 `wordlists` apt 包提供（实测 2026.2.0 版 53MB 含 rockyou），**烘进镜像**而非运行时下载（kali 工具默认路径直接可用，离线可用）

## 2. 网络边界实测（网络类工具的生死判定）

macOS Docker Desktop 的容器经 VPNKit NAT 出网，实测行为：

| 场景 | 实测 | 判定 |
|------|------|------|
| -sT 全握手扫 LAN 网关 | ✓ 2.2s 完成 | 可用 |
| **-sS SYN raw socket 扫 LAN** | ✓ 1.55s 完成 | 可用（root in container; NAT 回程正常） |
| -sn -PE /24 存活发现 | ✓ 发现 8 主机 | 可用 |
| **arpspoof（L2 ARP 欺骗）** | ✗ `couldn't arp for host` | **不可用**——VM 网络无 LAN L2; 宿主 scapy 替代 |
| 访问宿主机服务 | ✓ `host.docker.internal` → 192.168.65.254 | JsRpc 类工具可达宿主浏览器 |
| `--network host` | = Docker VM 网络，**不是 Mac 宿主** | macOS 上无意义 |

结论: nmap/hydra/nxc 打 LAN 与公网**均可用**（源 IP 为宿主共享）; 仅 L2 攻击类（arpspoof/Responder 毒化）在 macOS 容器不可用（Linux 宿主 + `--network host` + cap_add NET_RAW 可用，需注明）。

## 3. 逐工具分类总表（核心交付）

### 3.1 ✓ 容器内可用（22 项: 16 项功能实测 + 6 项 apt 包存在性确认，含多工具合并行）

> 标记说明: **[实测]** = 本机跑通功能链; **[包确认]** = apt 包存在于 kali-rolling 且属同机制（文件 I/O 型），未逐个跑功能——风险低但如实标注。
>
> 不在表中的四个边缘项: outguess/stegdetect（kali 已移除包，需源码 make 层，未实测）/ aeskeyfind（同源码层）——均维持手动，低频不阻塞。

| 工具 | 容器来源 | 实测证据 | 备注 |
|------|---------|---------|------|
| steghide **[实测]** | kali apt | 宿主造载体→容器嵌/提全链 | 文件 I/O 型，完美适配 |
| stegseek **[实测]** | kali apt | 装入 core; rockyou 走镜像 wordlists 包 | 高速爆破比 steghide 快 |
| john **[实测]** | kali apt | NT hash 字典破解跑通 | 自带 rockyou |
| **hashcat [实测]** | kali apt + pocl-opencl-icd | **PoCL CPU 设备 ✓，NTLM 322 MH/s** | CPU 模式仍千倍于 python; GPU 见 3.2 |
| nmap **[实测]** | kali apt | LAN SYN 扫描/存活发现 ✓ | 见 §2 |
| hydra / medusa / ncrack **[包确认]** | kali apt | 同 nmap 网络路径 | |
| **NetExec (nxc) [实测]** | kali apt `netexec` | `nxc --version`/DB 初始化 ✓ | pip aardwolf 失败的正解; HOME=/tmp 可写 |
| searchsploit **[实测]** | kali apt `exploitdb` | `searchsploit amsi` ✓ | 离线 DB 烘镜像; GitHub repo 已空的替代 |
| wpscan **[实测]** | kali apt | HOME 可写+update 后扫描 ✓ | build 期预 update 烘 DB 或卷持久化 |
| Sleuth Kit fls/icat/istat **[实测]** | kali apt `sleuthkit` + `e2fsprogs` | ext4 镜像 fls 列目录+icat 提取全链 ✓ | **需补 e2fsprogs**（mkfs/debugfs） |
| tshark **[实测]** | kali apt | -r pcap 解析 ✓ | 只读 pcap 无需特权 |
| exiftool **[实测]** | kali apt `libimage-exiftool-perl` | 13.55 ✓ | |
| mingw-w64 **[实测]** | kali apt | 交叉编译 PE32+ 落宿主属主正确 ✓ | |
| nasm **[包确认]** | kali apt | apt 安装即用 | |
| radare2 **[包确认]** | kali apt | kali 6.0.4 | r2pipe 调试在容器内自洽 |
| **gdb（amd64 目标在 mac 上）[实测]** | `qemu-user` + `gdb-multiarch` | **binfmt 直接 gdb 全灭（ptrace 失效）→ qemu gdbstub 模式断点/寄存器 ✓** | 见 §4 专项分析 |
| one_gadget / seccomp-tools **[实测]** | gem + **binutils-multiarch** | **裸装崩（arm64 容器分析 amd64 libc 报 UnsupportedArchitecture）→ 补 binutils-multiarch 后 3 个 gadget 输出 ✓** | one_gadget 是静态分析: 永远喂目标 libc 文件而非容器自身 libc |
| PHPGGC **[实测]** | git clone + php-cli | Laravel/RCE1 生成 ✓ | |
| pcapfix **[包确认]** | kali apt | apt 有 1.1.7 | |
| ImageMagick / sox **[包确认]** | kali apt | 同 apt 机制 | PIL/ffmpeg 主路径的补充 |
| binwalk（完整版含 magic 提取）**[包确认]** | kali apt | | $PYTHON_CMD 环境已有 pip 版，容器版功能更全 |

### 3.2 △ 条件可用（5 项）

| 工具 | 条件 | 说明 |
|------|------|------|
| ghidra headless | full 层镜像; `-Xmx` + `-Duser.home` | 实测 import+analyze ✓; 体积 +2GB 级; $IDAT 主路径的补充 |
| msfvenom | full 层（metasploit-framework） | 实测 payload 生成 ✓——纯生成器不依赖网络 |
| de4dot / ilspycmd | **独立 `mcr.microsoft.com/dotnet/sdk` 镜像**（kali 无 dotnet 包，实测确认; de4dot 官方 GitHub 零 release 资产） | dotnet 层单独构建; **build 全链未实测**（见 §6 残留） |
| responder / L2 毒化 | 仅 Linux 宿主（--network host + NET_RAW） | macOS 容器不可用 |
| GPU hashcat | 仅 Linux 宿主 + nvidia-container-toolkit | mac 容器走 CPU PoCL |

### 3.3 ✗ 不可容器化（9 项，原理性排除）

| 工具 | 排除原因 |
|------|---------|
| mimikatz / Rubeus / PrintSpoofer / JuicyPotato / GodPotato / PetitPotam 等 | Windows **目标侧**执行件——在目标机运行，不在分析机（离线分析已由 pypykatz 覆盖; Windows 容器需 Windows 宿主且无意义） |
| WinDbg / cdb | Windows 内核调试需 Windows 宿主+双机内核连接 |
| BinDiff / Diaphora / VMPAttack / NoVmp | IDA 插件形态，宿主 $IDAT 进程内运行 |
| JsRpc | 浏览器在宿主运行——容器内装无意义（host.docker.internal 虽可达，宿主 npx 更直接） |
| adb / iOS 工具链（class-dump/ldid） | USB 外设透传容器不可靠; 宿主 brew |
| frida（注入场景） | 容器内 frida 无法注入宿主进程; 宿主 $PYTHON_CMD 环境已有 |
| $IDAT / IDA 本体 | license + 宿主 GUI/headless 已就绪 |
| xray | 官方下载渠道（downloads.xray.cool）响应异常且 release 通道迁移混乱——维持手动（nuclei 覆盖主用例） |
| L2 攻击族（macOS） | 见 §2 |

## 4. gdb 跨架构专项（最重要的单点分析）

需求: Apple Silicon 宿主上调试任意架构 ELF（容器为 arm64 原生）。**架构 × 调试方式完整矩阵**（全部实测）:

| ELF 架构 | 仅执行 | 调试 | 机制 |
|---------|--------|------|------|
| **arm64**（容器同架构） | ✓ 原生跑 | ✓ **gdb 直接调**（ptrace 原生可用） | 无需 qemu——同架构原生环境 |
| **amd64 静态** | ✓ binfmt 透明执行（Docker Desktop VM 内核已注册 qemu 解释器） | ✗ 直接 gdb 全灭（binfmt 不模拟 ptrace——`Couldn't get registers`）→ ✓ **qemu gdbstub** | 断点经 qemu 内置 stub |
| **amd64 动态** | ✓ 需 `-L /usr/x86_64-linux-gnu`（amd64 ld/libc 缺失时） | ✓ qemu gdbstub + `set sysroot` | 同上 |

结论: `qemu-gdb` wrapper 按架构自动路由——arm64 ELF 走 gdb 直调（容器内原生 ptrace）; amd64 ELF 走 qemu gdbstub 模式（binfmt 下 ptrace 失效的唯一可行路径，动态自动挂 sysroot）。$IDAT 静态分析覆盖不了的场景（运行时解密/堆布局/ASLR 真实地址）由此补齐。

## 5. 镜像分层设计（体积实测数据）

| 镜像 | 内容 | 实测体积 | 构建耗时 |
|------|------|---------|---------|
| `opensecurity/toolbox-core` | §3.1 全部 + wordlists + qemu-user/gdb-multiarch + entrypoint 降权 | **5.21GB**（可再瘦: 去 --no-install-recommends 冗余） | 3.5 分钟 |
| `opensecurity/toolbox-full` | core + ghidra + metasploit-framework | **9.07GB** | +2 分钟（1GB 下载） |
| `opensecurity/toolbox-dotnet` | mcr.microsoft.com/dotnet/sdk + ilspycmd + de4dot 源码 build | 未实测（dotnet sdk 基镜像 ~700MB） | 未实测 |

- 双架构: kali-rolling 与全部 apt 包均 arm64+amd64（Apple Silicon 原生跑，无模拟损耗）
- 分层理由: full 换机多拉 4GB 且 ghidra/metasploit 低频; AI 按需 `--tool` 触发对应层
- `docker_manager.py` 收口: 镜像登记 KNOWN_IMAGES，控制台可见/可拉; detect_tools 增 `DockerRecipe`（image 存在检查→缺失 build/pull→生成 wrapper; docker 不存在→skip 提示装 Docker Desktop）

## 6. wrapper 规范（实施蓝本）

```sh
#!/bin/sh
# ~/bw-security-analysis/bin/steghide（由 detect_tools DockerRecipe 生成）
TOOL=steghide; IMG=opensecurity/toolbox-core
NAME="${TOOL}-$$-$(date +%s 2>/dev/null || echo x)"
DIR="$(pwd)"
# 参数路径重写: $PWD 前缀绝对路径 → /work 相对
ARGS=""; for a in "$@"; do ARGS="$ARGS $(printf %s "$a" | sed "s|^$DIR|/work|")"; done
trap 'docker kill "$NAME" 2>/dev/null' EXIT INT TERM   # 防孤儿容器（陷阱①）
docker run --rm -i --name "$NAME" \
  -e PUID=$(id -u) -e PGID=$(id -g) \
  -v "$DIR":/work -v "$HOME/bw-security-analysis/wordlists":/usr/share/wordlists:ro \
  -w /work "$IMG" "$TOOL" $ARGS
```

镜像 ENTRYPOINT（root→运行时 passwd 注入→setpriv 降权，已验证）见调研记录; 固定 `HOME=/tmp/home` 可写。

**长短任务超时机制**（wrapper 内建）:
- 短任务（steghide/exiftool/fls/...）: 固定 30 分钟容器内自灭
- 长任务（hashcat/john/stegseek/hydra/nmap/wpscan/nxc/medusa/ncrack）: **必须传 `--wrapper-timeout <秒>`**，否则报错并给用法示例（exit 64）; 该参数由 wrapper 消费，不透传容器内命令
- hashcat 特化: 未显式给 `-w` 自动注入 `-w 3`（全力）; `POCL_MAX_PTHREAD_COUNT` = 容器内逻辑核数/2（最低 1）——核数探测在容器内做（nproc/getconf，天然继承 cgroup 限额与架构差异; 大小核混合 CPU 在 Linux 侧呈对称逻辑核，调度器自动均衡，按逻辑核数分配即可）
- 容器内 timeout 保证: wrapper 被 SIGKILL 后容器最迟在时限内自灭（`--rm` 由 daemon 在容器退出时生效）
- 注意: `--opencl-device-types` 在容器内无意义——它是"从已有设备中选类型"的过滤声明，不是启用 GPU 的开关。macOS Docker Desktop 无 GPU 透传（设备列表只有 PoCL CPU 设备）; Windows WSL2 理论上可配 NVIDIA Container Toolkit + CUDA 基座镜像，但 toolbox-core 是 kali 基座未配——两平台现状均为 CPU（PoCL）。真 GPU 需 Linux 宿主+NVIDIA+toolkit+CUDA 镜像（§3.2）

**wrapper 跨平台策略**: 统一 sh 脚本（Windows 走 Git Bash/WSL 执行——与 install.sh 同前提）。历史上有过 .cmd 双语言分支，因"无法实测验证+每次功能演进双份维护"导致腐化（长短任务机制就没同步进去）而删除——单语言是可维护性的选择。

**AI 使用约束（须写入知识库对应工具条目）**:
1. 容器工具只吃 **cwd 内文件**（$PWD 外文件先 cp 进来）
2. 交互式 TTY 工具不可用（AI bash 本就非交互，影响面为零）
3. 输出大量中间文件的工具（ghidra 项目目录）注意 cwd 落盘即宿主可见
4. 长任务必须带 `--wrapper-timeout`（报错信息即引导，重跑加上即可）

## 7. 残留风险与未实测项（诚实清单）

| 项 | 状态 | 风险 |
|----|------|------|
| de4dot/dotnet 层构建全链 | 未实测（kali 无包、官方无资产已确认） | msbuild 源码 build 可能失败; 失败则 .NET 维持宿主 dotnet SDK 手动 |
| xray 容器化 | 渠道异常，未纳入 | 维持手动 |
| Linux 宿主下的行为差异（--network host 真宿主网络/KVM 加速 qemu） | 未实测（本机 macOS） | Linux 上能力只会更多不会更少 |
| Docker Desktop 依赖 | 前提条件 | 无 docker 的机器 DockerRecipe 报 skip 提示安装——不阻塞其他层 |
| Docker Desktop 升级导致 VPNKit 行为变化（SYN 扫描可用性） | 中期风险 | 版本锁定建议 + 复测命令留在本文档 |
| aeskeyfind/outguess/stegdetect 源码 build | 未实测 | 上游老项目 make 失败概率存在; 失败维持手动 |
| 大内存 dump（>4GB）经 VirtioFS 给 volatility 容器 | 未测 GB 级 | 2x 慢的线性外推可接受; 若瓶颈换 tmpfs 中转 |

## 8. 实施步骤（确认后执行）

1. `control/docker/toolbox-core.Dockerfile` + `toolbox-full.Dockerfile`（含 entrypoint 降权脚本与全部 §1.1 修法）
2. detect_tools.py 增 `DockerRecipe` + `--image` 分层路由 + docker_manager 收口登记 KNOWN_IMAGES
3. wrapper 生成器（§6 蓝本: 路径重写/trap 清理/wordlists 挂载）
4. EXTERNAL_TOOLS 注册（scan 面可见 available）
5. 知识库正文同步: 手动清单中 §3.1 工具的"外部工具（安装方式）"标注改为直接可用的容器路径口径（正文命令不变——wrapper 透明的核心价值）
