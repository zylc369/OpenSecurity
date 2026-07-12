<domain_sources>

## 领域：二进制分析

### 优先来源

1. **NVD（国家漏洞数据库）** — `https://nvd.nist.gov/vuln/detail/<CVE-ID>`
   主要的 CVE 详情：受影响版本、CVSS、参考链接。直接使用 `webfetch` 配合 CVE URL。
   机器可读 REST API 入口：`https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=<CVE-ID>`（比 HTML 更适合 agent）。

2. **Exploit-DB** — `https://www.exploit-db.com/exploits/<id>`
   可用的 PoC 漏洞利用代码。交叉比对 NVD 参考链接获取 ID。

3. **IDA Pro / Hex-Rays 文档** — `https://docs.hex-rays.com/`
   IDAPython API、类型库、处理器模块。使用 `websearch` 搜索 "IDAPython <api_name>"。

4. **Ghidra 文档** — `https://ghidra.re/ghidra_docs/api/`
   备用反编译器文档、脚本 API（Ghidra Javadoc API）。

5. **Packers/Protectors 识别** — `https://github.com/horsicq/Detect-It-Easy`
   壳签名（UPX、Themida、VMProtect、Enigma）。使用 `websearch` 搜索壳名 + "unpack script"。

6. **CVE 详情（CVE.org）** — `https://www.cve.org/CVERecord?id=<CVE-ID>`
   NVD 的替代来源，有时描述更清晰。

7. **VirusTotal** — `https://www.virustotal.com/`
   哈希查询、AV 检测、行为分析、PE 结构。二进制分析必查。

8. **MalwareBazaar** — `https://bazaar.abuse.ch/`
   免费恶意样本库，按家族/哈希下载。

9. **Frida 文档** — `https://frida.re/docs/home/`
   动态插桩事实标准（hook native 函数必备）。

10. **MITRE ATT&CK** — `https://attack.mitre.org/`
    技术 ID（T-ID）对照，行为归因必备。

11. **CISA KEV** — `https://www.cisa.gov/known-exploited-vulnerabilities-catalog`
    实战在利用 CVE 列表。

12. **YARA** — `https://yara.readthedocs.io/`
    规则与签名引擎。

### 查询术语约定

- 始终包含二进制格式/架构：`"PE32+ x64"`、`"ELF ARM64"`、`"Mach-O"`
- 已知时包含壳/编译器：`"UPX packed"`、`"Go binary"`、`"Rust binary"`
- 针对 IDA 特性问题：`"IDAPython <version>"`、`"Hex-Rays decompiler annotation"`
- 针对未知函数：包含调用点上下文（`"called from main"`、`"after stdio init"`）
- 二进制特征：`"imports ws2_32"`、`"entropy > 7.0"`、`"section .rsrc RWX"`
- 利用技术：`"ROP chain"`、`"heap spray"`、`"UAF"`、`"type confusion"`
- 行为特征：`"IOCs"`、`"MITRE T<id>"`
</domain_sources>
