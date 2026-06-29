# Reversing 方向源文档索引

> 创建: 2026-06-29

## 反混淆工具文档

| 文件 | 来源 | 覆盖技术 |
|------|------|---------|
| d810-readme.md | gitlab.com/eshard/d810 | D-810: Hex-Rays microcode 层反混淆插件，基于 Rolf Rolles 的 HexRaysDeob，用规则改写混淆等价变换。支持 OLLVM(指令替换/虚假控制流/平坦化)、MBA |
| hex-rays-microcode-api.md | hex-rays.com/blog | Hex-Rays microcode API vs 混淆编译器: microcode 中间表示原理，如何在 ctree 生成前改写规则 |
| hexraysdeob-readme.md | github.com/RolfRolles/HexRaysDeob | HexRaysDeob: D-810 的前身。⚠README 仅一句话，核心信息在源码注释中 |

## 符号恢复

| 文件 | 来源 | 覆盖技术 |
|------|------|---------|
| goresym-readme.md | github.com/mandiant/GoReSym | Go 符号恢复: pclntab 解析, moduledata, 函数名/类型/源文件恢复, -t/-d/-p 参数, runtime_modulesinit 签名扫描修复 |
| mandiant-golang-internals.md | mandiant.com/blog | Go 内部原理: pclntab 结构演进(1.2-1.20+), moduledata, GoReSym 工作原理, 符号恢复全流程 |

## IDA 版本变化

| 文件 | 来源 | 覆盖技术 |
|------|------|---------|
| ida90-release-notes.md | docs.hex-rays.com | IDA 9.0 重大变化: 移除 ida_struct/ida_enum(→ida_typeinf), ea_t→int, qstring→str, __EA64__=1单二进制, ida-plugin.json, idalib无头API, WASM/RISC-V/Golang/Rust FLIRT, Lumina |
