# 磁盘与内存取证 (Disk & Memory Forensics)

> 磁盘镜像/内存 dump/文件系统恢复/加密卷/容器云取证时加载。
> 基础（Volatility 常用插件/挂载/carving/注册表 hive）见 `forensics-methodology.md` §3-§4，不重复。

## §1 内存 dump 专项

- **GIMP 帧缓冲扫描**（Volatility 失败兜底）: 按 RGB×显示器宽（1920/1366/1280/1024）当 stride 渲染 raw 像素——曾显示的桌面/浏览器截图显形; Python 批扫启发式 `10<mean<245 且 std>20`
- **勒索 key 恢复方法论**: 先验 zip 完整性→strings 快逆向定模式（AES-256-OFB+IV 前置典型）→Volatility Linux 插件失败即转 raw 扫描→锚串（enc_key.bin 路径）定位+页对齐 32B 候选→**魔术字节当 key oracle**（解多文件首块验 %PDF/PK/89PNG，多签名共过才留）→恢复数对账 zip 清单→metadata flag 当诱饵处理（全库 rg 唯一性复核）
- **内存样本两层解密**: 减 0x32→超长循环 XOR key（可达数百字节 ASCII art）; 勿信 strings 表（红鲱鱼），提取真实二进制逆向; key 藏样本 data 段大段可打印文本
- **LUKS 主密钥**: `aeskeyfind mem.elf` 检测 AES key schedule 结构→`cryptsetup luksAddKey --master-keyfile`→开卷。伴生 rsakeyfind/aesfix。适用 LUKS/dm-crypt/FileVault/BitLocker
- **VMware 快照**: `vmss2core -W snap.vmss snap.vmem` → memory.dmp

## §2 加密卷与 VM

- **TrueCrypt/VeraCrypt 识别**: 无魔术/高熵/尺寸 512 倍数/上下文线索; 挂载 `veracrypt -t -p pw vol.tc /mnt`（keyfile 加 -k; 旧 TC 加 --truecrypt）; 隐藏卷=第二密码; cryptsetup `--type tcrypt` 等价
- **OVA/VMDK**: OVA=TAR; **VMDK 7z 直读免挂载**（按路径抽 SAM/SYSTEM/NTUSER.DAT）; split sparse 需 grain directory→grain table→grain 手工遍历
- **VMDK/镜像关键文件**: config/{SAM,SYSTEM,SOFTWARE}、Users/*/NTUSER.DAT、AppData

## §3 文件系统恢复

| 文件系统 | 删除机制 | 恢复路径 |
|---|---|---|
| NTFS | MFT 记录 0x16 标志翻转 | mftparser --offset 定向 dump $DATA; resident<700B 内联; windows.mftscan 兜底 |
| FAT16/32 | 目录项首字节 0xE5+簇标 free | `fls -r -d` + `icat` 按簇链取; 空闲簇（FAT entry==0）扫描拼 data 区——boot sector 布局: bps@11/spc@13/reserved@14/nfats@16/rootent@17/spf@22 → data_start=root_dir+root_entries×32 |
| ext2/3/4 | 目录项移除，inode 孤立 | `e2fsck -y` 接回 /lost+found; debugfs `lsdel`; extundelete; ext2 无日志最可靠 |
| XFS | — | inode 内联 extent [startoff,startblock,blockcount] 直读 dd; `xfs_db -r -c 'inode N' -c print'`; 超 4 extent 走 B+tree |
| BTRFS | CoW 快照保留 | `btrfs subvolume list`→`mount -o subvol=@backup`; btrfs-find-root 找孤儿子卷 |
| APFS | CoW 快照 | 扫 `APSB` magic（-16 偏移读 XID）→`icat -f apfs -B <快照块>` 跨 XID 读同 inode 取投毒前值 |
| ZFS | label 可被清零 | strings 找 nvlist 残留→Fletcher4 重算修复→PBKDF2 参数 GPU 爆破（PyOpenCL ~24k/s） |

- **RAID 5**: 双盘 XOR 恢复第三盘 `bytes(a^b)`; 布局四型（left/right×a/symmetric）用 PGM 可视化判 parity 旋转; mdadm --build 仅 RAID0——RAID5 用 fusepy 自实现块映射; XFS 只读挂载加 `norecovery`
- **HFS+ Resource Fork**: HFSExplorer 看 catalog 双 fork; 010 Editor HFS 模板读 extent 分段 dd 拼接; .fseventsd（FSEventsParser）还原历史操作
- **tar 重名条目**: `--occurrence=N` 取第 N 个（默认解包只剩最后一个）; python tarfile 遍历替代
- **null 交织反 carving**: 隔位插 null 稀释魔术（尺寸≈2×是信号）——文件系统 extent 取原始块后 `data[0::2]`

## §4 归档修复与密码

- **ZIP 修复族**: ①filename length 双处修复（LFH@26+CDE@28 必须一致）②中央目录缺失→local header `PK\x03\x04` 迭代独立解（zlib raw -15）③字节反转双向归档（正反都是合法 zip）④IEND 后 overlay 魔术复原
- **XZ 头重建**: 尾部 `YZ` footer 反推——footer 的 stream_flags（EOF-6）拷来+本地重算 CRC32 拼 12B 头; 通用: 头坏先查尾字节找真签名
- **bkcrack**（ZipCrypto 已知明文）: ≥12B 已知明文（参照文件/可猜文件头）; `-C zip -c target -P known.zip -p k.txt`→`-k k0 k1 k2 -d out`; pkcrack 失败就换。坑点: ①构造明文包必须用与目标**相同的压缩软件**（WinRAR 压的目标用 7z 构造参照包直接报错——比对两 zip 同文件压缩后体积是否一致可预检）②"口令未找到"≠失败——`加密密钥已成功恢复`即可停（key 足以解密，无需密码）
- **伪加密**（无真实密码、只改了加密标志位）: ZIP 通用位标记（general purpose bit flag）bit0=1 即"加密"——伪加密通常只改**目录区**（CDE）加密位、数据区（LFH）仍为 0（真加密两处都置 1）——对比两处判真假。修复: 010 editor 手改回偶数 / `binwalk -e` 无视伪加密直接解 / macOS·Kali 部分解压器直接可开 / ZipCenOp.jar 批量改（副作用: 对真加密包会改成"CRC 校验错误"损坏态）。RAR 同理: 文件头块（0x74）HEAD_FLAGS 位标记改伪加密——具体偏移: 文件头第 24 字节 `PASSWORD_ENCRYPTED` 或第 11 字节 `BLOCK_HEADERS_ENCRYPTED`（010 Editor RAR 模板字段）置 1 即伪加密、置 0 解除。压缩包注释也藏密码（明文/反色/空格-tab 摩斯）
- **exrex 正则密码链**: `list(exrex.generate(regex))` 物化匹配串（每层个位数候选）→extract-hint-repeat 千层秒级
- **冷门**: FemtoZip（.model 共享字典+同构 corpus）/Brotli 无魔术试解法（逐库 decompress 不抛错即命中）

## §5 结构化存储取证

- **BSON**: 4B 小端 size 头修复缺失字节; bson.decode_all; {index,data:base64} 分块按 index 排序重建
- **SQLite 编辑历史重放**: diff 表（type/position/text）按 id 重放——**每个中间态查 flag**（先输后删的秘密）
- **SQLite varint**: 两版本 diff→serial type varint（≥13=串，len=(t-13)/2）定位被改字段→相邻载荷读隐藏字符
- **Kyoto Cabinet 探针法**: key 清零时逐个插入探针 key+kchashmgr set→xxd diff 看哪个槽位被覆写→恢复 key→槽位映射→按原序重排值。"黑盒存储探针写入+diff 逆推布局"通用思想

## §6 平台取证

- **KAPE triage**: 顺序 PowerShell 历史（最快）→Amcache（regipy recurse_subkeys，执行时间线+SHA1）→MFT resident（<700B 内联直 grep）→注册表 hive→minidump 环境变量 strings
- **Docker**: `docker save` 分层 tar——**后层删除的文件在早期层仍在**（.wh. whiteout 只是标记）; `docker history --no-trunc` 看 ARG/ENV secret; config JSON 保留全部 RUN; dive 逐层 diff; export 免运行抽 fs
- **云存储**: S3 版本控制桶 `list-object-versions`+`get-object --version-id` 恢复已删; gsutil/az 同理
- **Android**: adb pull/backup→abe.jar 解包; 高价值: shared_prefs/（硬编码 secret）、databases/（SQLite）、wpa_supplicant.conf（WiFi 密码）、packages.xml
- **GPT GUID 信道**: 分区 GUID 16B 任意值——非零 GUID 拼接常是压缩流（首 GUID 魔术定格式）
- **MD5 PDF 碰撞**: corkami/pocs `pdf.py`+fastcoll 一条命令; chosen-prefix 用 hashclash

## §6a 应用取证

- **浏览器 artifact**: Chrome History/Downloads（SQLite; **WebKit epoch 1601 微秒** `datetime(t/1000000-11644473600,'unixepoch')`）; Firefox places.sqlite（Unix 微秒）/formhistory; Local Storage=LevelDB（strings *.ldb）; **session restore**: recovery.jsonlz4 跳 8B 魔术头 lz4.block.decompress→windows[].tabs[].entries[-1].url
- **Chrome 密码**: Local State `os_crypt.encrypted_key`（b64→去 5B DPAPI 前缀→CryptUnprotectData）; Login Data password_value v10/v11 格式 nonce[3:15]/ct[15:-16]/tag[-16:] AES-GCM; Firefox 走 firepwd
- **git 三式**: gitdumper 暴露 .git; squash 恢复 `git reflog --all`+`git fsck --unreachable --no-reflogs`（gc 前 2 周孤儿存活）→`git show <hash>:path`; 损坏 blob 单字节爆破（期望 SHA-1 在 tree 里已知，git hash-object 验证）
- **KeePass v4**: 标准 keepass2john 不支持 KDBX4/Argon2——ivanmrsulja fork 或 keepass4brute; hashcat -m 13400; cewl 上下文字典; SSH key 在 Notes/附件字段
- **pyrasite**: 运行中进程源码恢复——pyrasite-shell <PID> 注入（ptrace_scope），globals() 直接读 secret，func_code 用 uncompyle6（≤3.8）/pycdc（3.9+，先 marshal.dump 落盘）; /proc/PID/fd 见 deleted 标记即此场景
- **Linux 攻击链四源**: auth.log "session opened"+.bash_history+`find /usr/bin -newer auth.log`+tshark tftp; 恶意样本常见 AES-ECB+同 key XOR 存 .enc

## §7 域环境与密码

- Firefox firepwd（key4.db+logins.json）/ SSH Accepted publickey 溯源（authorized_keys×auth.log）/ 哥斯拉流量 AES-ECB 解密后乱码先 gunzip
- **PGM 可视化**: `("P5 W H 255"; cat img) > x.pgm`——黑区=零、横纹=元数据/parity、均匀噪声=加密; RAID 盘序判定（子块求和矩阵对齐/裂缝）

## §8 关联文件

- `forensics-methodology.md` — 总入口/Volatility/日志
- `network-forensics.md` — pcap 侧（TLS key、SMB3、外发）
- `$SHARED_DIR/knowledge-base/ad-domain-attacks.md` — AD 攻击视角
- `mobile-analysis/knowledge-base/` — Android 逆向侧
