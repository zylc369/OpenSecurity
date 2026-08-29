# 字典使用指南（场景 → 字典 → 路径速查）

> 字典统一目录: 环境变量 `$WORDLISTS_DIR`（shell 注入，`echo $WORDLISTS_DIR` 可得）。
> 所有命令中字典路径一律写 `$WORDLISTS_DIR/xxx`，禁止写死绝对路径。
> 场景选型本表优先; 工具用法细节见各领域知识库。

---

## 1. 目录结构

```
$WORDLISTS_DIR/
├── seclists/          # 全集字典（danielmiessler/SecLists, ~6000 文件）
│   ├── Discovery/     #   目录爆破(Web-Content) + 子域名(DNS)
│   ├── Fuzzing/       #   注入 payload(SQLi/XSS/SSRF) + User-Agent + 参数名
│   ├── Passwords/     #   密码(rockyou 系/10-million 系) + 各服务默认口令(Default-Credentials)
│   ├── Usernames/     #   用户名
│   └── Web-Shells/    #   各语言 webshell 样本
├── rockyou.txt        # 通用密码爆破字典（1434 万条, 139MB）
└── cn/                # 中文环境精选
    ├── safety-devices/   # 144 个安全设备默认口令（海康/大华/防火墙/WAF 后台等, 中文特色）
    ├── top/              # 中文常用密码 top 系列（top100/top1000/top6000/wifi_top2000）
    └── login-creds/      # 登入账号密码组合
```

## 2. 速查表（场景 → 字典）

### 目录/路径爆破（ffuf / gobuster / feroxbuster）

| 场景 | 宿主命令写法 |
|---|---|
| 通用目录（首选） | `ffuf -w $WORDLISTS_DIR/seclists/Discovery/Web-Content/raft-medium-words.txt -u URL/FUZZ` |
| 大范围慢扫 | `... raft-large-words.txt` |
| 快速试探 | `... common.txt` |
| 扩展名发现 | `... web-extensions.txt`（配 `-e` 或 FUZZ 拼接） |
| API 端点 | `... api/ ...`（seclists Discovery/Web-Content/api/ 目录） |

### 子域名（subfinder 已收集后爆破 / dnsx 枚举）

| 场景 | 写法 |
|---|---|
| 10 万级全量 | `$WORDLISTS_DIR/seclists/Discovery/DNS/bitquark-subdomains-top100000.txt` |
| 通用集合 | `... Discovery/DNS/namelist.txt` |

### 密码爆破（hydra / hashcat / john / 容器 wrapper）

| 场景 | 写法 |
|---|---|
| 通用爆破首选 | `$WORDLISTS_DIR/rockyou.txt` |
| 精简快速（1 万） | `$WORDLISTS_DIR/seclists/Passwords/Common-Credentials/10-million-password-list-top-10000.txt` |
| 中文环境 | `$WORDLISTS_DIR/cn/top/top6000.txt`（或同目录其他 top 文件） |
| WIFI 爆破 | `$WORDLISTS_DIR/cn/top/wifi_top2000_passwd.txt` |
| 特定服务默认口令 | `$WORDLISTS_DIR/seclists/Passwords/Default-Credentials/`（按文件名选: ssh-betterdefaultpasslist.txt 等） |
| 安全设备后台 | `$WORDLISTS_DIR/cn/safety-devices/`（144 个文件按厂商/设备名选） |

### 注入 payload（sqlmap / ffuf / 手工 fuzz）

| 场景 | 写法 |
|---|---|
| SQLi 通用 | `$WORDLISTS_DIR/seclists/Fuzzing/Databases/SQLi/Generic-SQLi.txt` |
| SQLi 盲注（时间） | `... Generic-BlindSQLi.fuzzdb.txt`（`__TIME__` 占位符需替换为秒数） |
| 登录绕过 | `... MySQL-SQLi-Login-Bypass.fuzzdb.txt` |
| XSS | `$WORDLISTS_DIR/seclists/Fuzzing/XSS/`（Polyglots/ 里的终极 payload） |
| 隐藏参数名 | `$WORDLISTS_DIR/seclists/Discovery/Web-Content/burp-parameter-names.txt` |
| User-Agent 伪造 | `$WORDLISTS_DIR/seclists/Fuzzing/User-Agents/UserAgents.fuzz.txt` |

### 用户名（爆破用户列表）

| 场景 | 写法 |
|---|---|
| 通用 | `$WORDLISTS_DIR/seclists/Usernames/`（xato-net-10-million 系列按量取） |
| 中文登入组合 | `$WORDLISTS_DIR/cn/login-creds/` |

## 3. 容器内路径（hashcat/hydra/john 等 DockerRecipe wrapper）

宿主 `$WORDLISTS_DIR` 由 wrapper **自动挂载**进容器，两套路径等价:

| 宿主路径 | 容器内路径 |
|---|---|
| `$WORDLISTS_DIR/seclists/...` | `/usr/share/seclists/...`（kali 惯例路径, 精确挂载） |
| `$WORDLISTS_DIR/rockyou.txt` | `/usr/share/wordlists-host/rockyou.txt` |
| `$WORDLISTS_DIR/cn/...` | `/usr/share/wordlists-host/cn/...` |
| （镜像内置, 容器专属） | `/usr/share/wordlists/rockyou.txt.gz`（镜像 v1.0 起自带） |

例: `hydra -L /usr/share/seclists/Usernames/top-1000.txt -P /usr/share/wordlists-host/rockyou.txt ssh://TARGET`（容器 wrapper 内）。

## 4. 维护

- 安装/重装: `python $OPENCODE_ROOT/control/backend/services/detect_tools.py install --tool seclists|rockyou|cn-dicts`
- 检查完整: `ls $WORDLISTS_DIR/seclists/Discovery` 有输出即 seclists 就绪; `wc -l $WORDLISTS_DIR/rockyou.txt` ≈ 14344392
- cn/ 源在 git 仓库 `$OPENCODE_ROOT/wordlists/cn/`（跨机器可重现; install 复制到 $WORDLISTS_DIR）
