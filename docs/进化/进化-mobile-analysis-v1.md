# mobile-analysis 进化

- 你安装的是 frida_srv_793 ，我怀疑你根本没有用`~/Documents/Codes/frida-scripts`里面的逻辑，安装随机名称的frida，我需要你确认一下，因为进程名中带frida特征太明显了。我创建mobile-analysis agent的时候就说明了，从frida-scripts移植逻辑，然后适配当前的被 AI 调用的架构。
```shell
MNA-AL00:/data/local/tmp # ps -A | grep frida_srv_793
root          4721     1 13137000 148520 poll_schedule_timeout.constprop.6 0 S frida_srv_793
MNA-AL00:/data/local/tmp # lsof -p 4721 | grep  -E 'TCP|UDP'
frida_srv_793  4721       root      8u     IPv4                          0t0      31930 TCP :29731->:0 (LISTEN)
```
- 在宿主机上，frida_srv_793你下载到哪里了？
- `readByteArray 在 NativePointer 上也不可用。Frida 17.x 可能确实改了 API。让我降级到稳定版本`，17.x版本最早是`May 18, 2025`出现的，我觉得这个应该不算是不稳定版本了。
    - `~/Documents/Codes/frida-scripts`里面用的就是frida的最新版本，记录了使用的经验、API、知识等等。之所以让你研究17.x的写法用法，是因为将近一年没有16.x的新版本，Frida 16.x可能已经都不再维护了！
    - 我在`vendor`目录下下载了frida main分支的最新代码。
    - 你必须要根据我之前的经验、知识，frida的代码，创建一整套17.x的编写经验、知识、沉淀脚本或沉淀脚本示例。
- 加固检测、脱壳方案，是否有可以沉淀的知识、经验、脚本？
- 移动端的知识、脚本，哪些需要沉淀，哪些需要更新、优化？