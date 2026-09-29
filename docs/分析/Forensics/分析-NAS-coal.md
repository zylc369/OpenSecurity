# 分析-NAS-coal.md

- **题目：**`someone put coal in my gem collection :^(`
- 附件位置：当前工程下的`docs/分析/Forensics/Attachments/gem_collection.pptm`文件。

---

## 分析结果

**Flag: `sun{yup_issa_gem}`**

### 关键路径

1. `gem_collection.pptm` 为宏启用演示文稿（OpenXML ZIP 结构，63 个条目），其中 `ppt/vbaProject.bin` 是唯一 VBA 工程，内部仅一个模块 `MediaCache.bas`，过程 `RefreshCache()`。
2. `RefreshCache()` 拼接 `powershell.exe -NoProfile -EncodedCommand <base64>` 并 `Debug.Print`（只打印、不执行；即"coal"本体）。
3. Base64 按 **UTF-16LE** 解码（PowerShell `-EncodedCommand` 的标准编码）得到"投放配置"：

```powershell
$campaign = 'sun{yup_issa_gem}'
$source = 'https://gem-cache.example.invalid/coal.bin'
$destination = 'coal.bin'
[pscustomobject]@{Operation='download'; Campaign=$campaign; Source=$source; Destination=$destination}
```

4. `$campaign` 即 flag。`example.invalid` 为 RFC 2606 保留域名（不可解析），文件内也不存在真正的 `coal.bin` 嵌入体——纯粹叙事。

### 校验记录（防误判）

- **防 VBA stomping**：`pcodedmp` 解析 p-code，`LitStr 0x0248` 字符串常量与源码中的 base64 逐字一致，无隐藏第二版代码（排除"源码与执行体不一致"类陷阱）。
- **穷尽检查**：63 个 ZIP 条目全部排查——无其它 base64 载荷、无嵌入 PE（`PE\0\0`/`This program cannot`）/ZIP 子文件；所有 PNG/JPEG 尾部无附加数据（IEND/EOI 后 0 字节）；ZIP 无 comment、EOCD 后无数据。
- **字节级**：flag 17 字符纯 ASCII，UTF-16LE hex `730075006e007b00…6d007d00`。
- 幻灯片 5 残留作者文本框（dirty run）：`>mfw olevba oneshot chall`——印证预期解法即 `olevba` 一发 + base64 解码。

### 证据

- 附件 SHA-256：`929726804037cc9b2e8779814aabf88361a6f4035ca1d93803662bdee543e855`
- 工具：oletools/olevba 0.60.2（源码提取）、pcodedmp 1.2.6（p-code）、exiftool（辅助）
- 证据等级：**observed**（源码 / p-code / 原始字节三重一致）
