# OSINT 技术（开源情报）

> 分诊: 已有本地文件需提取/carving → forensics-methodology; 目标变成活体 HTTP 服务利用 → web 侧专题; 发现恶意样本 → malware-analysis。

## §1 社交媒体平台调查

### Twitter/X 账号追踪
- 数字 ID 永久: `https://x.com/i/user/<id>` 改名后仍可访问; 归档页 JSON-LD `"author":{"identifier":...}` 提 ID
- Snowflake 时间戳: `(id >> 22) + 1288834974657` = Unix ms
- 改名检测: 归档推文 t.co 短链重定向 URL 含发推时用户名; 同推文 ID 不同用户名可访问=改名
- Wayback CDX: `curl "http://web.archive.org/cdx/search/cdx?url=twitter.com/NAME*&output=json&fl=timestamp,original,statuscode"`; 也查 `pbs.twimg.com/profile_images/*`
- 免登录源: Nitter 实例（域名经常关停，用前验证）、`syndication.twitter.com/srv/timeline-profile/screen-name/NAME`、memory.lol

### Tumblr
- 存活: `curl -sI https://NAME.tumblr.com` 看 `x-tumblr-user` 头——API 401 不代表不可浏览
- 头像: `/avatar/512` 重定向 CDN; 头像是高频藏点（视觉隐写），下 512 逐区放大
- 帖子提取: 页面 HTML 内嵌 JSON，搜 `"content":[`

### BlueSky 公共 API
- 免认证 `public.api.bsky.app`: searchPosts（`?q=词&sort=latest`）/ searchActors / getProfile / getAuthorFeed / getPostThread（含回复）
- 网页过滤器: `from:user` `since:2025-01-01` `has:images`
- **检查目标帖的所有回复**——数据常在回复不在主帖

### Discord 服务器枚举
- 藏点位: 角色名 / 动图 emoji 中间短时帧 / message embeds / 服务器描述/贴纸/活动
- `curl -H "Authorization: $TOKEN" "https://discord.com/api/v10/guilds/ID/roles"`; `.../emojis`; `.../messages/search?content=词`
- 动图 emoji 下载 GIF 逐帧提取——短时帧正常速度不可见

### 游戏平台
- WoW: wowprogress.com / raider.io / Blizzard API（公会名+服务器→roster→角色名）; Steam: steamcommunity.com/id/name + steamid.io; Minecraft: NameMC（皮肤/改名历史/服务器）; Discord: discord.id
- 角色名跨平台复用率高; 公会追踪器缓存历史数据

## §2 用户名与跨平台链

### 跨平台枚举
- 工具: whatsmyname.app（741+ 站，API `/api/lookup?username=`）、namechk.com、Osint Industries（付费覆盖小众/健身平台）
- **假阳性表**（200 但无资料）: Telegram t.me 永远 200（标题 "View" vs "Contact" 辨真假）; TikTok 页含 "Couldn't find this account"; Smule 页含 "Not Found"; linkin.bio 重定向 Later 产品页; Instagram 登录墙无法判定
- 用户名结构信号: 尾数=邮编/出生年/电话区号/国家码（player44uk→+44）→与邮编库/号段表交叉定位
- 改名链循环: 用户名→Wayback→归档内 t.co/交叉引用→新名→全平台重枚举→循环

### 链式模式
- 流程: 线索提取用户名→枚举→平台 X 指向平台 Y→数据在链条末端
- 平台藏点位: Spotify=歌单名/描述/艺人 bio（描述藏 Base64+歌名首字母藏头）; Reddit=帖/评; SoundCloud=曲目描述; YouTube=unlisted（删帖残留链接）
- 非标准编码先试 Base58; 提示语（"secret" 类措辞）常暗示数据就在帖内

### Strava 健身定位
- `strava.com/athletes/<id>` 公开页; 活动地图 GPS 路线含起终点; **隐私区外路线形状仍可反推遮蔽点**; segment 排行榜暴露常活动区
- 信号: running/cycling/fitness/GPS; 健身应用=高价值目标（单次公开跑步泄漏居住街区）

## §3 图像分析与反向搜索

### 引擎选型与技巧
- 分工: Google Lens（**裁剪后最佳**: 地标/店招）、Google Images（最全）、TinEye（精确匹配）、Yandex（人脸/东欧）、**Baidu graph.baidu.com（中国场景: 蓝牌/简体中文/门楼）**、Bing
- 裁剪区域搜索: 全场景返回泛化结果，裁出最独特元素再搜→精确商家+地址→Maps 街景验证
- 反射文字（水面/玻璃）: `convert in.jpg -flop out.jpg` 水平翻转后读; 部分可读用引号搜 `"Aguas de Lind"` 补全地名; 歧义字母两变体分搜; 60-70% 可读即可定位

### 视觉隐写与元数据策略
- 视觉隐写=角落/边缘极小低对比文字（非二进制 stego）: 全分辨率+查所有角落; 头像是高频载体
- **Twitter 上传剥 EXIF**（别找）; **Tumblr 头像元数据比帖子图多**
- 识别辅助: 物体→角色/阵营; 硬件规格→厂商库; 报纸档案（loc.gov）日期范围+EXIF GPS 交叉

## §4 地理定位

### 特征体系
- 国家捷径: 汉字+蓝底牌=日本; 西里尔+宽林荫道=俄/CIS; 白 X 铁道口=加拿大; 黄菱形警示=美/加; 绿牌=德国; 棕旅游牌=法国; 红反光柱=荷兰
- 流程: 驾驶侧→脚本文字→路牌风格→路牌 OCR（城镇+道路编号）→走廊搜索→海岸/港口/桥梁匹配
- 基础设施地图: OpenRailwayMap / OpenInfraMap（电力线）多特征交叉+排除法
- 后苏联: 混凝土板楼+宽隔离带+苏维恩纪念碑; 车型反搜缩市场; 政府旗→联邦主体
- **品牌门店链**: 商家名→搜「品牌+locations」→分布×海岸/地形→精确分店
- 拉美巨型字母: 搜 `"letras monumentales" 城市名`; OSM tourism=attraction

### Street View 全景匹配
- 目标图=全景裁切（常无天空）→覆盖地图枚举区域全景→ORB 特征匹配评分（`ORB_create(5000)`+`BFMatcher(NORM_HAMMING)`+distance<50 计数）→**多指标融合**（特征+patch+颜色直方图）
- metadata 端点查覆盖; panoId 从页面 JS 提取; 稀疏覆盖区（格陵兰/冰岛）全枚举

### Maps 众包照片验证
- 以图搜图失败时有效（图是原创但同场景在游客照里）: 地名→Maps→地点 Photos tab→场景元素对比→确认
- **按名搜照片，非以图搜图**; 适用公园/广场/游客多地

### 多地点+次级编码
- N 张主题图各定位一地、各提一数字（钢琴键号等）→序列编码; **先全定位再解编码**; 编码方案从数据点推断（ASCII/MIDI/偏移）

### IP 归因
- 免 key: `ip-api.com/json/IP`、`ipinfo.io/IP/json`; ASN 判 VPN/托管; Windows 遥测 imprbeacons.dat 含 CIP; IP 段×电话前缀交叉

## §5 坐标编码三体系

| 体系 | 格式 | 精度 | 备注 |
|---|---|---|---|
| MGRS | `4V FH 246 677` | 可变 | 军事网格; 在线转换器→经纬度 |
| Plus Code | `H9G2+47X` | ~14m | 字符集 `23456789CFGHJMPQRVWX`+必有 `+`; **免费内建 Maps 无需 key**; 落点→详情面板读码 |
| What3Words | `word.word.word` | 3m | 相邻方格词无关; 语言特定; API 需 key（网页可用） |
- W3W 3m 精度: 入口 vs 停车场不同址; **相机位置 vs 拍摄对象**; 候选周围试 5-10 相邻方格
- W3W 精确定位: 微地标匹配（电线杆/护柱在街景找同款）、背景建筑三角定位、地理特征先缩范围

## §6 网络与基础设施侦察

### WHOIS 体系
- 关键字段: 注册人（常遮蔽）/创建时间（时间线关联）/NS（共享主机）/注册商
- 历史 WHOIS（隐私前）: SecurityTrails API（APIKEY 头）/WhoisXML/DomainTools
- 反向 WHOIS: WhoisXML API 按注册人邮箱/组织/电话搜全部域名
- IP WHOIS: NetName/OrgName/CIDR/abuse; ASN: `whois -h whois.radb.net AS12345` / bgp.tools

### Shodan 指纹去匿名化
- SSH host key 服务器唯一: `ssh-keyscan -t rsa target | ssh-keygen -lf - -E md5` → Shodan `ssh.fingerprint:"aa:bb:..."` → Tor/CDN 背后真实 IP
- 同理 `ssl.cert.fingerprint:"SHA256"`; Censys 同类; 规则: 加密身份（SSH key/TLS 证书）是跨代理持久标识

### Tor relay
- 40 hex=SHA-1（Tor 指纹）/64=SHA-256/32=MD5 长度速判
- `metrics.torproject.org/rs.html#simple/<FINGERPRINT>`: family 成员+first seen 时间序

### Google 侦察参数
- 图像 TBS: `&tbs=itp:face`（人脸——剥 logo/横幅）/`ic:trans`/`isz:l`/`isz:lt,islt:2mp`; 组合 `site:linkedin.com&tbm=isch&tbs=itp:face`
- Google Docs/Sheets 公开变体: `/export?format=csv`、`/pub`、`/gviz/tq?tqx=out:csv`、`/htmlview`; Sheet ID 稳定可重试

### 常识速查（指向既有专题）
- DNS TXT/CNAME/MX/AXFR 子域检查 → 区域榨取三路（ECS/NSEC/IXFR）补充
- 假服务 banner: 端口号≠服务——SYN 扫描只证开放; `nmap -sV -sC` 或 `nc host port` 读真 banner
- `.DS_Store` 泄漏目录文件名: `curl -sO target/.DS_Store && python3 -m dsstore .DS_Store`（路径发现见 web-methodology §2.2）
- Wayback CDX 通用: `web.archive.org/cdx/search/cdx?url=DOMAIN*&output=json`（Twitter 专项见 §1）
- WAF 源站直连/证书搜源站 → waf-bypass.md

## §7 仓库与代码侧
- 藏点位: issue 评论/PR review/commit message/wiki 历史——`gh api repos/O/R/issues/comments`
- **作者邮箱→登录名**: `git shortlog -sne`; `git log --format="%an <%ae>%n%cn <%ce>" | sort -u`; `gh api users/U/events/public --paginate | jq -r '.[] | .payload.commits[]?.author.email'`; 补充 .mailmap/CONTRIBUTORS/GPG 签名; 每个邮箱当目标服务候选登录名直接试
- .git 目录暴露恢复——工具 gitdumper/GitTools（与取证侧 git 重建同一技术，此处用于收集目标公开信息）

## §8 编码与隐写
- Unicode 同形字隐写: 异块同形字符（Cyrillic а/U+0430 等）混入文本，ASCII=0/同形字=1 每 8 bit 一字节; **跳过平台自动插入的 U+2019 智能引号**; 与零宽系互补——同形字可见但视觉相同
- TTF 字形轮廓 diff: cmap 重映射混淆（显示"5"实际 U+E042）但**形状不变**——`ttx -t glyf -g -d out font.ttf` dump 轮廓×标准字体参考库 diff; 参考库建一次全场景复用; GSUB 连字隐写同属字体侧

## §9 杂项
- Telegram bot: 浏览器历史 `LIKE '%t.me/%'` 发现→/start→验证问题答案在取证材料里（4781 改名/MRU/Shellbags）→回复泄漏凭据/隐藏服务
- FEC 资金链（限定美国）: fec.gov/data; 501(c)(4) 匿名层→最大组织捐赠者→领导层
- 跨挑战容器 IP 复用（CTF-only）: 同子网共享; 弱题泄漏 REMOTE_ADDR→强题 md5(IP) 路径
