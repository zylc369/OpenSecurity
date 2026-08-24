# 古典密码

> 何时用：凯撒/移位、维吉尼亚、单表替换、无密钥古典、字母频率类。多数不需 sage，纯 Python + 频率分析。

## 1. 识别类型

| 密文特征 | 类型 |
|----------|------|
| 全字母，保持空格，看着像英文 | 凯撒/单表替换 |
| 均匀字母分布、无明显单词 | 维吉尼亚（多表） |
| 含数字/符号、按位置变换 | 其它（培根/Playfair/Hill/Affine） |
| Base64/32/58/85 | 编码（非密码），先解码再看 |
| 二进制/十六进制串 | 先转 bytes 再判 |

> **先做编码识别**：很多"密码"其实是 Base 系列编码或 ROT，先试解码。

## 2. 凯撒（移位，26 种）

```python
def caesar(s,k): return ''.join(chr((ord(c)-65+k)%26+65) if c.isalpha() else c for c in s.upper())
# 暴力 1~25，看哪个像英文
for k in range(26):
    print(k, caesar(ct,k))
```

## 3. ROT13 / ROT47

```python
import codecs
codecs.decode(ct, 'rot_13')
# ROT47 处理 ASCII 33-126
def rot47(s): return ''.join(chr(33+(ord(c)-33+47)%94) if 33<=ord(c)<=126 else c for c in s)
```

## 4. 维吉尼亚（Vigenère）

**破解流程**：
1. Kasiski / 重合指数（IC）求密钥长度 k。
2. 按 k 分组，每组做凯撒（频率分析）。

```python
# 重合指数判定密钥长度
def ic(s):
    from collections import Counter
    cnt = Counter(s); n = len(s)
    return sum(c*(c-1) for c in cnt.values()) / (n*(n-1))
# 英文 IC ≈ 0.0667；随机 ≈ 0.038。对每个候选长度 k，分组算 IC 接近 0.0667 即密钥长
```

**Kasiski 法（与 IC 互补）**：找密文中重复 3-5 gram 的出现位置，相邻距离的 GCD = 密钥长度（重复序列距离必为密钥长倍数）：
```python
from math import gcd
from functools import reduce
def kasiski(ct, min_seq=3):
    distances = []
    for seq_len in range(min_seq, 6):
        seen = {}
        for i in range(len(ct) - seq_len):
            seq = ct[i:i+seq_len]
            if seq in seen:
                for prev in seen[seq]: distances.append(i - prev)
                seen[seq].append(i)
            else: seen[seq] = [i]
    return reduce(gcd, distances) if distances else None
```

**已知明文推导密钥**（最常见场景——已知 flag 前缀）：`key[i] = (ct[i] - pt[i]) mod 26`。片段短于密钥则循环复现，观察重复周期确认完整密钥。

分好组后每组用频率分析（英文频率表逐 shift 打分：E=0.127 T=0.091 A=0.082，空格最频）。更精细用 chi-squared: score=Σ((观测%−期望%)²/期望%)，分值越低越像英文（对全部 26 位移算取最小）。IC 中间档参考: ≈0.045-0.055 → 短密钥（<10）多表；≈0.038-0.042 → 长密钥或随机。

**密钥不规范三种情况**：①密钥与消息等长不循环（需其他线索）②密钥来自主题相关词 ③密钥含重复字母 padding（IICCHHAA 而非 ICHA——推导出的密钥呈此类结构是正常现象，去重即真密钥）。

**密钥对称降维**：多维表密码中若 k2 = reverse(k1)（回文/镜像关系），加密只依赖镜像位对称和 `k1[i]+k1[kl-1-i]`，独立变量减半——已知明文 ≥ key_len/2 即约束全部和值。拿到多维表密码先检查密钥间代数对称关系。

工具：`pycipher`、在线 dcode.fr。

## 5. 单表替换

- 频率分析（字母 + 双字母 bigram/trigram）。
- 词模式匹配（已知明文样式时）。
- 工具：quipqiup.com、`substitution` 库。

### 5.1 变长同音替换（homophonic）

高频字母映射到多个长度 1-4 不等的码组拉平频率。特征：单字符频率非均匀又不像简单替换。

破解（n-gram 频率归并法）：
1. 算 1-6 gram 频率
2. **识别恒定频率组**：若 2-gram `8f`/`fk`/`kd` 各恰好出现 36 次且 4-gram `8fkd` 也是 36 次 → `8fkd` 是单一替换单元（同音码组整体出现，任意子串频率与整体相等）
3. 按**长度降序**迭代替换码组为单符号（防部分匹配）
4. 归约后成普通单表替换 → quipqiup/频率分析
5. 剩余歧义字符用已知答案 hash 离线爆破排列（`itertools.permutations` 验证 sha256）

### 5.2 多元组替换（bigram/trigram）

- **位置 mod n 分解**: shuffle[pos%n][char] 型 → 每个剩余类 pos≡k (mod n) 是独立单表替换，分组后频率分析/已知明文各各击破。识别: 分组后单组 IC 恢复正常
- **CP-SAT/OR-Tools**: 明文有结构（词表/NATO 音标/正则）时——每替换单元 IntVar + AllDifferent 单射 + flag 前缀 crib + AddAutomaton 正则约束 → 唯一解

## 6. 培根（Bacon，5-bit）

每 5 个符号一组，A/B 二选一 → 二进制 → 字母。常隐藏在两种字体/大小写里。

## 7. Playfair / Hill / Affine / Rail-Fence / Atbash / Polybius

| 类型 | 特征 | 解法 |
|------|------|------|
| Playfair | 双字母组、无 J | 字典/已知明文还原 5x5 |
| Hill | 矩阵加密、mod 26 | 求逆矩阵（mod 26） |
| Affine | `c=(a*m+b)%26` | 已知明文求 a,b。合法 a 仅 12 个（1,3,5,7,9,11,15,17,19,21,23,25，gcd(a,26)=1）→ 12×26=312 组合直接爆破 + chi-squared 英文打分筛。矩阵版 c=A·p+b (mod m) 且 m 非素: 选择明文差分消 b（c_i-c_0=A·(p_i-p_0)）→ A=E·D⁻¹；D 在 Z/mZ 可能不可逆 → 按素因子 CRT 拆到域上高斯消元再合并 |
| Rail-Fence | 按行重排 | 试栏数 |
| Atbash | A↔Z 1对1替换、题目名常藏谐音暗示 | 自逆：`chr(ord('Z')-(ord(c)-ord('A')))` |
| Polybius | 纯数字 1-5、长度偶数 | 5x5 网格坐标查表（I/J 同格）; **敲击码 Tap code 变体**: K 并入 C 格（行号+列号，敲击声/停顿分隔） |
| Nihilist | 两位数字组、可超过 55 | Polybius + 逐位加数字密钥；坐标减密钥后须落在 1-5（剪枝），明文重复字母处密文差直接泄漏密钥数字 |
| 网格置换 | 行/列独立打乱的矩阵替换 | 行列置换可交换，密钥空间 (n!)² 而非 (n²)!；5x5 = 120×120 = 14400 毫秒级暴力 + 词表过滤 |
| Pigpen/猪圈 | 几何符号（网格位置派生字形） | 符号映射 Pigpen 网格位置（题面常暗示 Peanuts/共济会）; dcode.fr 有专用解码器 |
| 键盘移位 | 密文像"邻键按错"的英文 | QWERTY 布局整体左/右移 N 位; dCode Keyboard Shift Cipher 自动模式 |

**ROT-N 大数**：`N mod 26` 即有效位移，正反两方向都试（1337 mod 26 = 25 = 反向 ROT1）。

**维吉尼亚家族与 Delastelle 系冷门变体**（识别为"多表/棋盘系古典密码"后按此清单对号，全部 pycipher 一键解 / dcode.fr 搜索密码名）: Autokey（密钥=短关键词+明文自身延续，非循环）｜Beaufort（加密=解密对等运算，密表反向，Hagelin M-209 机用）｜Porta（加解密同过程，密钥字母成对映射半表）｜Running Key（密钥为长文本书页而非循环短词，密钥与明文都含英文统计——双文本统计攻击）｜Bifid（Polybius 坐标全部行坐标先写+列坐标后写再重组成字母——扩散，密文仍字母）｜Trifid（3×3×3 三方阵版 Bifid，坐标三位数字）｜Four-Square（四个 5×5 矩阵双字母替换，对角明文矩阵+对角密钥矩阵）｜Checkerboard/Straddle Checkerboard（棋盘数字替换，Straddle 用两个未分配数字作行号扩展，常再叠一层加法密钥）｜Fractionated Morse（明文→摩尔斯 `. - x` 三元组→按密钥字母序查 26 组合表）｜Bazeries（数字→英文单词（如 2333="two thousand..."）取不重复字母生成密钥矩阵 + 按数字位分组反序）｜Digrafid（3×9 双密钥方阵，字母对→三位数字）｜Grandpré（8×8 单词方阵，同字母多坐标）｜图形密码族变体: 标准银河字母/圣堂武士 Templar/夏多（曲折+数字转纸指示）——与猪圈同族，dcode.fr 图形解码器逐一试。

## 8. XOR 攻击族

### 8.1 多字节循环 XOR（密钥未知）

原理：密钥长 k 分解为 k 个独立单字节 XOR（按位置 mod k 分组）。

**定密钥长（逐列评分法）**：对每个候选 kl，每列（`ct[col::kl]`）在 256 候选中取最优英文得分，总分最高的 kl 即密钥长。评分：空格 0x20 最高频 + 小写字母。
```python
def score_english(data):
    from collections import Counter
    freq = Counter(data)
    return freq.get(ord(' '), 0) + sum(freq.get(c, 0) for c in range(97, 123))
```
备选定长法：密文与自身按候选长度移位 XOR，大量 0x00（低熵）→ 移位量 = 密钥长。密文 >100 字节时可靠；更短用已知明文前缀 XOR 出密钥片段。

### 8.2 已知明文/文件头恢复密钥

- 已知明文片段（flag 前缀）与密文对应位置 XOR = 密钥片段，假设密钥循环解密全部
- **文件头锚点法**：文件声称某格式但 `file` 显示 "data" → 头部 XOR 期望 magic、尾部 XOR trailer 得密钥首尾片段。锚点表：PDF `%PDF-1.`/`%%EOF`；PNG `\x89PNG\r\n\x1a\n`/`IEND\xaeB\x60\x82`；ZIP `PK\x03\x04`/`PK\x05\x06`；JPEG `\xff\xd8\xff\xe0`/`\xff\xd9`；ELF `\x7fELF`；GIF `GIF89a`/`\x3b`。长度 N 的密钥只需 N 字节已知明文（位置 mod N 确定即可，不必连续）。头部 XOR 结果呈可读 ASCII/重复模式 → 重复 XOR 密钥

### 8.3 级联 XOR（c[i] = p[i]^c[i-1]）

仅首字节未知：256 暴力首字节，其余确定性递推，可打印 ASCII（32≤b<127）过滤唯一确定。

### 8.4 OTP 密钥重用（two-time pad）

`C1^C2 = P1^P2`（密钥消去）。已知 P1 → `P2 = C1^C2^P1`。无已知明文用 crib dragging：猜测词在 C1^C2 上滑动，可打印输出处交替猜测两侧内容扩展。多条密文（many-time pad）两两组合；空格与字母 XOR 改变大小写特性可定位空格（space correlation）。

### 8.5 特化 XOR 场景

- **位置索引叠加**: `c[i]=p[i]^key[i%k]^i`（或 `^(i&0xff)`）。症状: 已知前缀恢复的"key"逐位 +1 递增。破解: 先 `(enc[i]^i)^known[i]` 剥索引再按重复密钥法，密钥长 2-32 遍历+可打印过滤
- **2 的幂旋转位隔离**：S^ROTR(S,k) 且全部 k 是 2 的幂时奇偶位永不混合，N bit 恢复降为 2 bit 暴力（4 候选状态验证所有帧）
- **纯 XOR 线性结构自反转**：无密钥、每输出字节 = 同块输入字节的 XOR 树 → GF(2) 线性系统直接构造逆变换（其余 lane XOR 重建目标 lane），无需暴力
- **确定性密钥流 + 负载均衡后端**：密钥流每连接重置无 nonce → 已知明文恢复密钥流；多后端时须重连到同一后端（已知明文加密结果一致即匹配）
- **弱校验折叠**：比较逻辑把多字节 XOR/求和折叠成单字节再比对 → 固定响应 1/256 通过率，期望 ~256 次爆破

### 8.6 RC4

加解密同一操作（KSA 置换 S 盒 + PRGA 生成密钥流 XOR）。已知密钥即可解；密钥常短/来自简单字符串。手写实现约 20 行（S=list(range(256)) 双指针交换）。

## 9. 多阶段自定义编码逆序还原

逆向拿到串联加密阶段（大小写交换→XOR→加减常量→循环移位），解密按**相反顺序**逐阶段取逆：
- XOR：自逆
- 加/减 K：减/加 K（mod 256）
- 循环左移 N bit：`((x << (8-N)) | (x >> N)) & 0xFF`
- 大小写交换：自逆
- 乘法 mod 256：乘模逆（仅奇数可逆）

纪律：加密 A→B→C，解密 C⁻¹→B⁻¹→A⁻¹；单字节先跑正向+逆向验证对得上再批量。

## 10. 冷门/中文圈编码识别表

| 密文特征 | 编码 | 解法 |
|---|---|---|
| 只有 A/B 两种字符 | 培根（5 位组） | 二进制转字母 |
| 汉字+数字 | 当铺密码 | 按字形数出头笔画对应数字 |
| 只有 ADFGVX 六字母 | ADFGVX | 6x6 Polybius + 列置换 |
| 只有 01248 | 云影密码 | 0 分隔组，组内相加映射 1-26 |
| `\x54\x68` 形式 | shellcode | 去 `\x` 按 hex 解 |
| `[]()!+` | JSFuck | 还原后 eval。**jother 变体**: 字符集扩为 `!+()[]{}` 八字符构造匿名函数——同族解码法; **ppencode**: Perl 代码全转英文单词流（纯语义单词但不可读）|
| Ook./cat. 等替换符 | Brainfuck 变形 | 还原 `+-<>.,[]` 再解。**主题词变体**（meme 词表 5-8 个词替换指令）: Counter 频率映射——最高频词=+/-（值定义词）、成对短词=>/<、行尾词=.（输出）、同行首尾词对=[]; 映射错时对调 +/- 或 >/< 再试 |
| 文件只含空白或 S/T/L 三字符 | Whitespace | 栈式 VM: `S S`+符号+二进制+`L`=PUSH（S=0/T=1）、`T L S S`=输出字符、`L L L`=EXIT; 可见字符是空白符的字母替换; vii5ard.github.io/whitespace 在线解释器 |
| 中文/韩文/藏文字符墙（无语义、低方差） | base65536 族 | 每字符 2 字节→Unicode 码点子集; npm/pip base65536 解码; 变体 base1024/2048/4096/32768 逐个试 |
| CJK 乱码（UTF-16 端序错配 mojibake） | 编解码端序互换 | `fixed = mojibake.encode('utf-16-be').decode('utf-16-le')`（或反向）; 识别: 文本变"日文"+题面提 translation/endian |
| 题名暗示字节比（如 1.5x）+数字 nibble | BCD | 每字节高低 nibble 各编码一位十进制数字: `''.join(f'{b>>4}{b&0xf}' for b in data)` 得数字串→两位一组 chr() 转 ASCII |
| 三位数一组 | 八进制 | int(x, 8) |
| 八位数一组 | 二进制 | int(x, 2) |
| 同心圆转盘/N 位值汉明距恒 1 | 格雷码 | `gray = n ^ (n>>1)` 生成序列; **循环性**: 解出结果整体偏移（如 ROT-4）时旋转格雷码起点同样位数仍合法; 二叉树路径变体: '0'→j*2+1、'1'→j*2+2，解码从索引回溯（奇=左/偶=右）再反转 |
| 题面提 4042/UTF-9 | UTF-9（RFC 4042 愚人节） | 9bit 组: MSB=连续位（1=后续还有）、低 8 位=数据; 多组拼接 8 位段成码点。愚人节 RFC 族（1149/2549/4042）偶见于题面 |
| TOP/KEK 词+! 后缀 | TOPKEK（CTF 专用） | KEK=0、TOP=1、每个 `!` 多重复一次该 bit; 8 位分组转 ASCII |
| 牛眼中心（3 同心圆）+六边形点阵 | MaxiCode（UPS 物流码） | 标准 QR 解码器全失败; zxing（Java）原生支持: `java -cp javase.jar:core.jar com.google.zxing.client.j2se.CommandLineRunner img.gif`，或在线条码解码器 |
| `0041000B91` 前缀 hex 行 | GSM SMS-SUBMIT PDU | smspdu 库解析+UDH `05000301XXYY` 分片重组 |
| 行首数字/字母表长度字符+含空格，字符集无 `+/` 且行首像长度标记（如 `59FQA9R!I<R![22...`） | UUencode | 每行首字符 chr 减 32=该行字节数; CyberChef From Uuencode / `uudecode` |
| 像 base64 但用 `+-` 而非 `+/`（如 `DNalVNrhMK4JiMqxjN4Jx`） | XXencode | UUencode 的可打印安全变体（同一映射换字符集）; CyberChef From XXencode |
| `=B4=F7` 形式 `=`+两 hex 三字节组（中文邮件正文常见） | Quoted-printable | `python -c "import quopri;print(quopri.decodestring(s))"` / CyberChef From Quoted Printable |
| `%uFF0C` 形式 `%u`+4 hex（JS escape 产物） | JavaScript escape/unescape | `urllib.parse.unquote(s.encode().decode('unicode_escape'))` 或 CyberChef Unescape String; 与 URL 编码 `%XX` 区分: `%u` 前缀=escape 专用 |
| 两位数字串（键位+击次，如 33532141=flag） | 手机键盘密码 | 2=abc/3=def/4=ghi/5=jkl/6=mno/7=pqrs/8=tuv/9=wxyz; 两位一组 (键, 次数): 33=3 键第 3 击=f、53=5 键第 3 击=l; 也可"同键连击+停顿分隔"形态（22=b、7777=s）。**电脑键盘变体**: 字母→QWE 布局映射（Q→A 位移）/键盘坐标/环绕方位，题面提"键盘"或密文全在键盘同一排时试 |

杂项：二进制长度整除 7 → 补 0 凑 8 位；整除 5 → 培根；能开方 → 二维码。utf-8 与 unicode(UCS-2) 的 base64 不同，CyberChef 只认 utf-8。每字符与 ASCII 差固定值 → 减偏移。旗语照片：两臂姿势按 8 方位表映射（J/# 姿势切换字母/数字模式）。2 倍长编码+高 nibble 随机：忽略高 nibble 重组低 nibble。**图像条带移位**：像素条带移位是视觉版凯撒；给两份同尺寸图（原+移位）时逐行/列对比求偏移量序列，偏移量常直接 chr() 成 ASCII（图像有水平/垂直剪切伪影是指纹）。

## 11. 多层编码链逐层剥离

单词二进制（ZERO/ONE/TRUE/FALSE 全英文单词文件，检查单词数被 8 整除）→ 二进制 → ASCII → base64 → Morse 逐层剥。每剥一层重新做编码识别（长度整除性/字符集/可打印性），不假设层数。解出明文常需人工修正形近字符（O→_、补花括号）。组合 base64→XOR、hex→XOR、ROT13→base64 常见，已知明文前缀定 XOR 密钥。

**歧义优先级**: 数据全 hex 字符（0-9a-f）且长度为偶 → **先按 hex 解再考虑 base64**（hex 字符集是 base64 子集，base64 也接受这些字符，走错路浪费一层）。中途出现 troll flag（假 flag）直接忽略——找 "keep decoding"/"REAL_DATA_FOLLOWS:" 类标记继续剥。

**跨资源链变体**: 每跳指向外部资源（GitHub Gist/Pastebin 的 URL），每跳编码不同（base64 URL→hex URL→ROT13 flag）; 题面提 trail/breadcrumbs/scavenger hunt。上下文线索（诗文/注释/文件名，如 "Three letters follow" 暗示 3 字符编码名 hex）提示下一层编码类型。PNG 无明显视觉隐写时也可能是 Piet 程序——npiet 直接执行。esolang 多层链常见: Piet→base64→Malbolge、BF→Ook→Whitespace; 载体也可嵌视频缩略图（BF 输出 YouTube URL→yt-dlp --write-thumbnail 抽图→裁边框→npiet）。

**自动链式解码器**: 25+ 层编码手剥不现实——循环尝试解码器清单直到全部失败: base64/base32/base16/zlib/bz2/rot13/hex/二进制串/EBCDIC(cp500)，每个 try-except 成功即换层（上限 50 层）; 可加 esolang 检测（纯 `+-<>[].,` = BF）。

## 11a. 历史机械密码

**书本密码（book cipher）**：密文是"步进数"序列，从参考文本起始位逐次前进取字符。暴力全部起始位（数万），用**输出字符集约束**早剪枝（一处非法即淘汰）——56k 候选常只剩 3-4 个。

**Lorenz SZ40/42（Tunny）**：12 轮（χ×5 每步进位周期 41/31/29/26/23；Ψ×5 条件步进周期 43-59；μ61/μ37 控制步进），加密 `ct=pt^χ^Ψ`（5-bit ITA2，A=24...T=1，27=FIGS 31=LTRS）。**Δ 攻击**：已知明文得密钥流 → 差分 `Δk[i]=key[i]^key[i+1]`（Ψ 仅 ~25% 步进 → Δk 偏向 Δχ）→ 每个 χ 轮按周期分相位多数投票恢复 Δχ → 积分得 χ（起始 0/1 两候选，循环一致性校验）→ 密钥流减 χ 得 Ψ（ΔΨ 全 5 bit 为 0 = 未步进）→ 步进模式恢复 μ61/μ37 → 剩余歧义暴力（2^5×2^5×61×37≈231 万）。注意：步进来自机械轮不是 LFSR，勿用 B-M。

## 12. 通用工具

- **CyberChef**（本地无则 webfetch 查用法，或用 Python 实现）：Base/ROT/古典全覆盖。
- **dcode.fr**：识别 + 解多种古典。
- **xortool**：多字节 XOR 自动定密钥长+破解（`xortool ct.bin -b` 爆破长度；`-c 20` 假设最频字符为空格）。
- **Ciphey**：全自动编码/密码识别解密（pip install ciphey）。
- Python：`pycipher` 库。

## 决策

```
看着像编码（Base/HEX）？ → 先解码（冷门编码查 §10 表）
密文是 XOR 过的文件（file 报 data）？ → §8.2 文件头锚点法
多字节 XOR 密钥未知？ → §8.1 逐列评分
两份密文同密钥？ → §8.4 two-time pad
单表、字频像英文？ → 凯撒/替换/频率（频率被拉平 → §5.1 同音）
多表、IC≈0.038？ → 维吉尼亚（Kasiski+IC 求长 → 分组频率；已知前缀直接推导密钥）
纯数字 1-5 偶数长？ → Polybius（可超 55 → Nihilist）
两种符号混排？ → 培根/摩尔斯
按位置重排？ → Rail-Fence/列置换；网格行列打乱 → (n!)² 暴力（§7 表）
纯 XOR 构成的自定义分组密码？ → §8.5 线性自反转
两份图像一份有剪切伪影？ → 图像条带移位（§10 杂项）
```

## 注意

- CTF flag 可能藏在古典密码解码后的"中间结果"里（题目故意多套一层）。
- 密文含非字母符号常是有意线索（如分隔符指示分组）。
- 不要忽视题目给的 hint（题目名、描述常暗示密码类型）。
