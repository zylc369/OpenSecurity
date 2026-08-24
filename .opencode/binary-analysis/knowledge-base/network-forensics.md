# 网络取证 (Network Forensics)

> 处理 pcap/pcapng（协议分析/加密流量解密/隐蔽信道/隧道重组）时加载。
> 基础侦察（tshark 常用过滤/export-objects/凭证 grep）见 `forensics-methodology.md` §2，不重复。

## §1 加密流量解密

| 协议 | 解密路径 |
|---|---|
| TLS | ①keylog（NSS 格式 `CLIENT_RANDOM <32B> <48B>`——素材里 .log/sslkeys.txt 或自抓）②RSA 私钥 `tls.keys_list:IP,443,http,key.pem`（仅 RSA kex; ECDHE 无效）③弱证书: handshake.type==11 抽证书→因子分解→rsatool 造 key ④私钥来源链: SMTP base64 附件 OCR/FTP/TFTP/chat 里找 `BEGIN RSA PRIVATE KEY` |
| TLS 无 key | coredump 掏 master key: OpenSSL ssl_session_st 里 master_key[48] 在 session_id[32] **前面**——握手抄 session ID→内存搜→前 48B; keylog 行 `RSA Session-ID:<hex> Master-Key:<hex>` |
| SMB3 | NTLMv2 抽取（messagetype==0x3 的 ntproofstr）→hashcat 5600→MD4/HMAC-MD5 推 session key→SP800-108 KDF（Label SMBC2SCipherKey/SMBS2CCipherKey+preauth_hash）→AES-128-GCM 解 Transform 头（[4:20]tag/[20:32]nonce/[20:52]AAD/[52:]密文） |
| WiFi | aircrack-ng（-a 1 WEP PTW/-a 2 WPA 字典）→airdecap-ng 出 *-dec.pcapng; 密钥来源: rom-0 路由器配置（HTTP 流量里 GET /rom-0→LZS 解压→WPA 密码）; 密钥轮换→分段解密逐段找提示; IPP job-name 是 flag 高发点 |
| RDP | pcap 里 PKCS12(.p12/.pfx) 传输（常 UDP/FTP）: `openssl pkcs12 -in c.p12 -nocerts -nodes -out key.pem`→Wireshark RSA keys（Protocol=tpkt, Port 3389） |
| RADIUS | `radius2john.pl cap.pcap`→john→Shared Secret 填 Wireshark→User-Password 自动解出 |
| RC4 流 | shellcode 256 轮 KSA 指纹; key=TCP 流首段固定长度突发（如 32B urandom）其后高熵流; 标准 RC4 解 |

## §2 隐蔽信道与外泄

**总原则**: 发送方可影响的任何元数据（包长/TTL/IPID/TCP窗口/QNAME长/请求顺序）都是信道——先画逐包元数据直方图，只落在可打印 ASCII 区间的分布即是暗号。

| 信道 | 提取 |
|---|---|
| ICMP payload 长度 | `chr(len(p[ICMP].payload))` 逐包（type==8）; frame.len 变体减基线（如 -42） |
| 包间隔时序 | 同接口同包两组离散间隔=二进制，阈值中点; 大 pcap 用 `io,phs` 找包最少的接口 |
| ICMP 往返时延 | icmp.seq 配对 req/rep; <200ms=填充/0.2-1s=0/>1s=1; 直方图双峰检测 |
| TCP flag 位 | 6 flag 位=0-63 恰好 base64 字母表; 荒谬 flag 组合+固定端口+包数 4 倍数 |
| DNS 尾字节 | qname 末字符拼接; 或 question 结构（12+qname+1+2+2）后的尾随 `0x30/0x31` 逐包 1 bit |
| DNS NOERROR oracle | 子域前缀逐位探测，NOERROR=前缀对 NXDOMAIN=错，O(n) 重建 |

**DNS 权威服务器榨取三路**: ECS 伪装（`dig +subnet=10.13.37.1/24`，leet/内网段全试）/ NSEC walking（响应 `NSEC <next>` 链式迭代枚举全区域）/ IXFR=0（diff 中旧新 SOA 之间=已删除记录，删掉的 TXT 常藏数据）。**AXFR 域传送操作**: 先 `dig +short @8.8.8.8 target NS` 拿目标自有 NS（第三方 NS 不算）→ 逐个 `dig +nocmd @ns1 target axfr` 试——允许则一次拿全区域记录。**DNS 当图数据库**（hxp 2017）: UUID 子域=节点、方向子域（up/down.UUID.domain）CNAME=边、TXT=节点数据——dnspython（勿 subprocess dig，慢）+激进去重缓存 BFS。
| ICMP payload 内容 | 字节旋转 `(b-shift)%256`→base64 等多层 |

## §3 隧道与多层

- **dnscat2 重组**: 单域名海量 hex/base32 标签; 每 chunk 剥 9B 协议头; 相邻比较去重传; 重组流按魔术识别
- **假协议流**: Wireshark 判 TLS 但 raw hex 是 PK 头——按字节不按 dissector 判断
- **多层 XOR**: key 藏带内协议（mDNS TXT 记录 rrname 含 key）; ZIP 内两等长流各解密后单流乱码→逐位取可打印的那路合并
- **Brotli 炸弹接缝**: 极端压缩比+全量解压 OOM→比较相邻块找周期破坏点（如 105B 周期）→只解异常块

## §4 AD/域协议取证

- **RID cycling**: Guest/null SMB 认证→bind `\pipe\lsarpc`→LsaOpenPolicy→LsaQueryInformationPolicy（域 SID）→LsaLookupSids 递增 RID 枚举域账号。检测: `smb2.cmd==1` 多认证+`dcerpc.cn_bind_to_str contains lsarpc`+顺序 RID
- **Timeroasting**: MS-SNTP 响应 68B=[0:48]salt/[48:52]RID(小端)/[52:68]HMAC-MD5; hashcat -m 31300 格式 `rid:$sntp-ms$<md5hex>$<salthex>`; 打机器账号（密码=小写主机名常见）; 全链 Guest→RID 枚举→SNTP 请求→离线爆破
- 衔接 `$SHARED_DIR/knowledge-base/ad-domain-attacks.md`（攻击视角）与 `internal-pentest-methodology.md`

## §5 pcap 文件层与重建

- **pcapfix 修复**: `pcapfix -d x.pcap`（也支持 pcapng）; 手工: 全局头 24B=magic(4)+ver(4)+tz(4)+sigfigs(4)+snaplen(4)+linktype(4); magic 微秒 `0xa1b2c3d4`/纳秒 `0xa1b23c4d` 小端
- **pcapng 自定义块**: 块=Type(4)+TotalLength(4)+Body+TotalLength(4); 标准类型 {0x0A0D0D0A,0x1..0x6} 之外 Wireshark 静默忽略——逐块解析拼 body（常 gzip）
- **校验和重建**: 缺字节 256 爆破+IP 头反码和验证（有效头代入后和 0）; TCP 校验和含伪头; 多字节用 seq+头结构缩空间
- **分卷归档重组**: 同尺寸文件集+一个小的尾片=分卷; 排序看 Apache 目录列表页的时间戳（非下载序）; 密码在另一 TCP 流聊天记录
- **HTTP 外发快速分诊**: 第一步 `--export-objects http,dir` 再深挖; multipart POST/异常 UA（DeadDropBot 类）/死投递模式

## §6 关联文件

- `forensics-methodology.md` — 取证总入口/基础 tshark（§2）
- `$SHARED_DIR/knowledge-base/steganography-forensics.md` — 媒体载体侧
- `$SHARED_DIR/knowledge-base/ad-domain-attacks.md` — AD 攻击全景
