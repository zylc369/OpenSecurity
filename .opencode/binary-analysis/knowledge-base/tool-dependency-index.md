# 外部工具清单（自动安装 + 手动安装）

> 知识库能力全部由项目内实现覆盖: python 依赖由 `detect_py_deps.py` 清单管理（调用 `$(dirname $PYTHON_CMD)/<tool>`——vol/binwalk/sqlmap/dirsearch 及 impacket 全套 .py 脚本等）; 脚本在各领域 scripts/; 命令与算法内联在知识正文。
> 下方「自动安装」部分由 `detect_tools.py` 的 INSTALLABLE_TOOLS 清单管理（CLI: `python control/backend/services/detect_tools.py install`，或一键 `bash .opencode/install.sh`）——产物落 `~/bw-security-analysis/bin`（插件注入 PATH，agent 会话直接可用）/ `~/bw-security-analysis/tools`（jar 与克隆源码）。幂等: PATH 已有（brew 等）或产物齐全即跳过; `--force` 重装; `--tool <name>` 单装。跨平台: darwin/linux/windows × amd64/arm64。

## 一、自动安装（bash .opencode/install.sh 一键, 33 项实测可用）

| 类别 | 工具 | 来源与说明 |
|------|------|-----------|
| Web 扫描 | nuclei / dalfox / ffuf / gobuster / gau / feroxbuster / subfinder / httpx / katana / naabu / dnsx / tlsx | GitHub Releases 官方二进制（win/mac/linux amd64+arm64） |
| 隧道/内网 | chisel / ligolo-ng / ligolo-proxy / frpc / frps | GitHub Releases 官方二进制 |
| 逆向/隐写 | bkcrack / upx / wabt（wasm-objdump·wasm2c·wat2wasm·wasm-decompile） | GitHub Releases 官方二进制 |
| Java 工具 | ysoserial / apktool / jadx | jar/zip + wrapper（**需 java 运行时**; 本机已有 brew 版则自动跳过） |
| git 单文件工具 | rsactftool / wesng / windapsearch / regeorg / redis-rogue-server / pyinstxtractor / pyarmor-1shot / ajpshooter | git clone --depth 1 + BIN_DIR wrapper（windapsearch 依赖 python-ldap 自动装 $PYTHON_CMD 环境） |
| python 包工具 | ccupp | git clone + pip install（console script 落 $(dirname $PYTHON_CMD)/） |
| 音视频 | ffmpeg / ffprobe | linux/win 静态构建直链; **macOS 走 brew install ffmpeg**（本机已有则跳过） |

> Java 系在无 java 的机器上报告 skip（不阻塞），装 java 后重跑 install 补齐。

## 二、仍需手动安装（无免密跨平台方案——编译/系统层依赖/发布渠道限制）

| 工具 | 无法替代原因 | 环境要求 |
|------|------------|---------|
| hashcat / john | GPU/CPU 破解性能（python 慢百倍以上; 小字典 python 循环可替代）; 官方 release 仅 win，linux/mac 需编译+GPU 运行时 | kali core / brew john |
| nmap | 扫描性能+脚本引擎（python-nmap 只是壳）; SYN 扫描需 root+libpcap 系统层 | kali core / brew |
| xray | release 通道非标准 GitHub 二进制（chaitin 自有分发） | 官网 |
| hydra | 多协议高速爆破引擎（低速率定向爆破 python 协议库循环可替代）; C 编译 | kali core |
| msfvenom / Responder 等 kali 套件 | 攻击执行件本体 | kali |
| NetExec (nxc) | pip 安装依赖 aardwolf 构建失败（rust 编译链）; 底层 impacket 已随 $PYTHON_CMD 环境覆盖大部分能力 | pipx / kali |
| PHPGGC / marshalsec | PHP 运行时 / maven 构建（ysoserial 已自动化） | git + php / maven |
| steghide / zsteg / stegseek | C/Ruby 实现，隐写格式解析无 python 库（bkcrack 已自动化） | brew（部分）/ git 编译 |
| de4dot / ilspycmd | .NET 工具链（需 dotnet SDK） | dotnet tool |
| uncompyle6 / pycdc | Python 字节码反编译器（pycdc 需编译; uncompyle6 仅 ≤3.8） | pip uncompyle6 / git |
| Ghidra | 补充反编译（主路径 $IDAT 已覆盖）; ~400MB 按需 | 官网安装 |
| mimikatz / Rubeus / PrintSpoofer / JuicyPotato / GodPotato / PetitPotam / mitm6 / lsassy / nanodump 等 Windows 后渗透件 | Windows 目标机执行件（提权/横向/凭据提取，编译后目标机运行） | 目标机落盘 / git release |
| wpscan | WordPress 插件/主题漏洞库聚合（无环境时 python 循环 readme.txt 探活覆盖枚举）; ruby 运行时 | gem / 官网 |
| WinDbg / cdb | Windows 内核态调试器（语义映射见记忆库: WinDbg 命令→frida/IDAT 等效） | Windows SDK |
| radare2 | 命令行逆向备用（主路径 $IDAT; r2pipe 驱动调试场景）; 源码编译 | brew |
| JsRpc | 浏览器内 JS 运行时桥接（npm 运行时依赖） | npm |
| NoVmp / VMPAttack | VMProtect 去虚拟化（VMPAttack 为 IDA 插件） | git / IDA 插件 |
| tshark | pcap 深度解析+对象导出（基础解析 python 库 scapy 等效） | brew install wireshark |
| exiftool | 元数据读写（读取 PIL 部分覆盖）; perl 源分发 | brew install exiftool |
| medusa / ncrack / smtp-user-enum | 多协议爆破/SMTP 用户枚举（hydra 同族; 低速定向 python 协议库循环/smtplib VRFY-RCPT 循环可替代） | kali / perl |
| searchsploit | exploit-db GitHub repo 已迁移成空壳（离线库不可克隆; 在线等效 exploit-db.com 网页搜索） | kali |
| one_gadget / seccomp-tools | ruby gem 工具（libc execve gadget 搜索/BPF 反汇编; python 思路见正文） | gem |
| gdb / gdbserver | Linux 动态调试（macOS 本机用 lldb/frida; 远程目标侧 gdbserver） | brew / Linux 执行机 |
| qemu（qemu-system-x86_64 / qemu-riscv64） | 全系统/用户态模拟（qiling 随 $PYTHON_CMD 环境，覆盖部分架构） | brew install qemu |
| mingw-w64 | Windows PE 交叉编译 | brew install mingw-w64 |
| BinDiff / Diaphora | 二进制 diff（IDA 插件形态） | 官网 / IDA 插件 |
| ImageMagick（identify / convert / magick） | 图像信息/帧操作（PIL 覆盖主要用例: info/seek 逐帧/拼接） | brew install imagemagick |
| sox | 音频处理（频谱图常用; ffmpeg 已自动化覆盖大部分） | brew install sox |
| outguess / stegdetect / stegbreak | 隐写第二实现族（steghide 失败时换试） | brew / git |
| bftools | BF 图片隐写解码（python 映射表十几行可复现）; 非 GitHub 源 | 官网 zip |
| aeskeyfind | 内存 AES 密钥搜索 | kali |
| Sleuth Kit（fls / icat / istat） | 磁盘镜像遍历提取（python 库 pytsk3 等效） | brew install sleuthkit |
| pcapfix | pcap 头修复（python 重写 24 字节全局头等效） | git |
| vmss2core | VMware 内存转 raw | 官网 |
| icoutils（wrestool） | PE 资源提取（pefile directory ENTRY 等效） | brew install icoutils |
| dsniff（arpspoof） | ARP 欺骗（scapy 可构造等效） | brew install dsniff |
| boolector | SMT 求解器 QF_BV 后端（Z3 卡慢时; brew 装后 angr/claripy 自动调用） | brew install boolector |
| nasm | 汇编器（pwntools asm/keystone 等效） | brew install nasm |
| class-dump / ldid | iOS ObjC 头导出/伪签名 | brew |
| Linux 取证机命令（xfs_db / e2fsck / cryptsetup / btrfs / veracrypt2john） | 目标文件系统/加密容器处理——需 Linux 取证环境 | Linux 执行机 |
