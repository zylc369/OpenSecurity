# AD 域渗透攻击链

隧道选型与未授权入口见 `$SHARED_DIR/knowledge-base/internal-pentest-methodology.md`。

## 1. 域信息收集

| 命令 | 用途 |
|------|------|
| `net view /domain` | 判断是否存在域 |
| `net time /domain` | 定位 DC（时间服务器） |
| `net user /domain` | 列域内用户 |
| `nltest /domain_trusts` | 域信任关系 |
| `setspn -q */*` | SPN 扫描（定位服务账号） |

## 2. 四大凭据/票据攻击

| 攻击 | 前置条件 | 效果 |
|------|---------|------|
| DCSync | 对域控有复制权限（管理员组/DC 账号） | mimikatz `lsadump::dcsync` 直接导出任意账号哈希（含 krbtgt） |
| Golden Ticket | krbtgt 哈希 | 伪造任意用户 TGT，全域持久化 |
| Silver Ticket | 服务账号 NTLM 哈希 | 伪造 TGS 仅限特定服务（不需与 KDC 交互） |
| Kerberoasting | 任意域账号 | 请求 SPN 服务 TGS → 离线爆破服务账号密码 |

## 3. 域漏洞

- **CVE-2020-1472 ZeroLogon**: 域控 Netlogon 置空密码 → DCSync 全域接管。
- **CVE-2021-42287 + sAMAccountName spoofing**: 域普通账号改名伪装域控获取特权票据。
- **CVE-2020-0688**: Exchange RCE 后利用（Exchange PowerShell 反序列化）。

## 4. 横向移动

- **PTH**（NTLM 哈希传递）/**PTK**（AES256 密钥）/**PTT**（票据传递）。
- 远程执行: PsExec、WMI、计划任务（at/schtasks）。
- 密码喷洒: nxc/CrackMapExec——用户名字典×弱密码字典（域成员密码常重合）。

## 5. 凭据收集

mimikatz（明文+哈希）｜Procdump 转储 lsass + 离线 mimikatz（绕杀软）｜Pillager（浏览器/Xshell 密码）。提权 CVE 速查见 internal-pentest-methodology.md §6（Linux）/§6a（Windows）。

## 6. 哈希离线破解（hashcat/john 收尾）

抓取产物 → -m 对照: Kerberoast TGS（`$(dirname $PYTHON_CMD)/GetUserSPNs.py -dc-ip DC -hashes :hash -outputfile`）→ 13100; AS-REP（`$(dirname $PYTHON_CMD)/GetNPUsers.py -no-pass`）→ 18200（两脚本均为 impacket 套件自带——impacket 随 $PYTHON_CMD 环境安装后全部 40+ 脚本位于 `$(dirname $PYTHON_CMD)/` 下，`ls $(dirname $PYTHON_CMD)/ | grep "\.py$"` 全列）; NTLM（secretsdump 第 4 列）→ 1000; NetNTLMv2（Responder）→ 5600; DCC2 域缓存 → 2100; WPA 握手 → 22000; bcrypt → 3200; Linux shadow $6$ → 1800。起步 `$WORDLISTS_DIR/rockyou.txt -r best64.rule`，不中再上掩码 -a 3（?u?l?l?l?l?l?l?d 型）/组合 -a 1/大规则（OneRuleToRuleThemAll）。实用: --show/--restore/-D 2/-w 3/-O。类型未知先 `$(dirname $PYTHON_CMD)/hashid HASH`。

john（CPU 首选，自动识别类型）: 同场景 --format=NT/krb5tgs/krb5asrep; **\*2john 链**提取文件密码: zip2john/rar2john/pdf2john.pl/ssh2john/keepass2john/office2john → john --wordlist=$WORDLISTS_DIR/rockyou.txt。规则梯度 --rules=best64→Jumbo→KoreLogic; --incremental/--mask/--fork=4/--session。GPU 用 hashcat，CPU/文件提取/盲跑用 john。与 §2 票据攻击互补——票据类直接用哈希不还原明文，本节还原密码供登录。。
