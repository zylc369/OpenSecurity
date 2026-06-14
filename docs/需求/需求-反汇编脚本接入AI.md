# 需求-反汇编脚本接入AI

`disassembler/dump_func_disasm.sh` 升级，要求：
1. 新增参数`--ai-decompiler`，参数可选，用于调用ai反编译输出的汇编文件，输出到汇编文件的相同目录，提示词：
```
反编译`[汇编文件绝对路径]`到`[汇编文件汇编文件所在目录的绝对路径]`目录中，输出语言为C/C++或Python，优先使用Python。Python通常能够等价的表达C/C++逻辑，Python不需要考虑较为复杂的内存申请、释放，它的库也很丰富、易于安装。**Python代码必须严格保持与原汇编代码的功能等价性。**
```
2. 需要调用@ai/opencode.py 中的run_opencode执行ai反编译功能。
3. 在ida pro的output中通过执行` exec(open("...").read())`@disassembler/dump_func_disasm.py 脚本，能够正确的调用run_opencode。
4. 在ida pro的output中的运行方式尽量简单。
5. 需求做完之后，告诉我如何运行。