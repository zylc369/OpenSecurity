# Windows 取证 (Windows Forensics)

> Windows 镜像/KAPE 包/事件日志/注册表/USN/反取证场景加载。
> 基础（evtx 转换/注册表 hive/关键键）见 `forensics-methodology.md` §4-§5。

## §1 事件 ID 深化

- **账户生命周期**: 4720 创建/4722 启用/4724 密码重置/4726 删除/4738 更改/4781 改名; 1001 Bugcheck、41 非正常关机
- **RDP 三日志源**: LocalSessionManager（21 登录/23 注销/24 断开/25 重连/40-42）; RemoteConnectionManager（**1149 认证成功含源 IP**/261）; RdpCoreTS（131 含 ClientIP:port/103 断开查 ReasonCode）
- 解析: python-evtx → XPath `.//ns:EventID` + `.//ns:Data@Name`

## §2 USN Journal 时间线

记录: len@0/major@4/file_ref@8/parent_ref@16/timestamp@32（1601 纪元 100ns）/reason@40/UTF-16 文件名@fn_off。Reason: 0x2 DATA_EXTEND/0x100 CREATE/0x200 DELETE。

三大应用: ①wmiexec 每命令建删 `__<unix时间戳>.<随机>` 于 C:\Windows\——循环计数=命令数（WMIPRVSE prefetch 佐证） ②PSReadLine history 每次 DATA_EXTEND=一条命令（PS 日志清了也有精确时间线） ③C:\Users\<user> 目录 CREATE（parent=Users MFT ref 512）=首次交互登录（wmiexec 不触发）。

## §3 NTFS 深化

- **ADS**: Sleuth Kit `fls -r img | grep ":"`（条目 `66-128-4: file:stream`）→ `istat img 66` 看 $DATA 命名属性 → `icat img 66-128-4` 抽; 活系统 `dir /r`/`Get-Content -Stream`; Zone.Identifier 是溯源第一站; pytsk3 遍历 type==NTFS_DATA 且 name!="(default)"
- **timestomping**: SI（0x10，可改）早于 FN（0x30，系统维护）=回拨; 文件名 UTF-16LE——`strings -el $MFT` 必跑
- MFT offset 定向 dump 删除文件见 `disk-memory-forensics.md` §3

## §4 反取证

**日志被清后 10 替代源**: USN $J / SAM 键 last_modified（账号创建时间）/PS history / Prefetch / MFT / Defender MPLog（独立通道常漏清）/RDP 日志/WMI 仓库 OBJECTS.DATA/浏览器 SQLite/注册表时间戳。Security.evtx 1102=清日志动作本身被记录。

- **MPLog**: `ProgramData\...\Support\MPLog-*.log` grep DETECTION/THREAT/ASR; DetectionHistory 二进制 strings 提 SHA256+路径; "Block PSExec&WMI"/"Block lsass credential stealing" 命中=攻击尝试
- **安全擦除指纹**（恢复前先查，判断可行性）: cipher /w→`EFSTMPWP` 目录; sdelete→`.ZZZ` 扩展; BleachBit→`~BleachBit*.tmp`。已覆写→转 $Recycle.Bin/$LogFile/VSS/MFT resident
- **certutil/bitsadmin LOTL**: `bitsadmin /transfer`+`certutil -decode`=%TEMP% 批处理标配; 内存按 **UEsD**（=base64("PK\x03")）扫传输中/已删 base64 ZIP; psxview 找隐藏进程

## §5 内存凭证顺序

以下都是 volatility 软件的子命令（即 `$(dirname $PYTHON_CMD)/vol -f mem.raw` 命令的子命令，全部内置无需安装）: windows.clipboard（CF_UNICODETEXT 最近复制——最先跑）→ windows.hashdump / windows.cachedump（volatility 子命令——提取凭据哈希）→ windows.dumpfiles --pid <lsass PID> dump 出 lsass.dmp 后 **`$(dirname $PYTHON_CMD)/pypykatz lsa minidump lsass.dmp`**（pypykatz 是纯 python 凭据提取工具，$PYTHON_CMD 环境已装; 它提取的"wdigest 明文"指内存中的 WDigest 认证缓存——wdigest 是 Windows 协议名不是命令; mimikatz 是 Windows 目标机上运行的工具）→ windows.registry.printkey → windows.memmap --pid <PID> --dump（volatility 子命令，dump 进程内存）+ strings（macOS 系统自带命令）（**`-e l` UTF-16LE 必跑**，Windows 宽字符 ASCII strings 漏一半）→ windows.netscan/pstree/dlllist。实战: TrueCrypt 密码: volatility 2 有 truecryptsummary 子命令可以直接读出，但 volatility 3 没有移植它——改用 dump 全内存后 python 按 TC 密钥结构（find 设备句柄+头部 magic 'TRUE'）搜索，或 strings 找挂载密码; wireshark 进程→memmap dump+`$(dirname $PYTHON_CMD)/binwalk` 分离 pcap。UEsD 内存扫 ZIP 见 §4。**无内存镜像只有 config 蜜罐目录时**: `$(dirname $PYTHON_CMD)/pypykatz registry local --sam SAM --system SYSTEM`（提取 NTLM 哈希; mimikatz 在目标机 Windows 上运行）。

## §6 杂项五则

回收站 $R=内容/$I=元数据（UTF-16 原路径+时间）; OEMInformation SupportURL=C2 后门 IOC; hosts 行尾空白藏数据（xxd tail）; .contact 的 `<c:Notes>`; 遥测 imprbeacons.dat（CIP/geo_*/COUNTRY）。WinZip AES: zip2john + hashcat -m 13600（-a 6 '?d?d?d?d' 混合）; ZipCrypto 场景用 bkcrack（见 disk-memory §4）。

## §7 关联文件

- `forensics-methodology.md` — 总入口
- `disk-memory-forensics.md` — 磁盘/内存/平台（KAPE、Docker、MFT dump）
- `network-forensics.md` — pcap 侧（NTLMv2/SMB3/TLS）
- `$SHARED_DIR/knowledge-base/ad-domain-attacks.md` — AD 攻击
