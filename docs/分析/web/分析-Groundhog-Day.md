# 分析-Groundhog-Day

**题目：**
```
The Punxsutawney Orbital Weather Authority has been broadcasting the same forecast since 1993.

Every reading is fresh. Every date is February 2. The Bureau insists this is fine, and the groundhog has declined to comment.

Their public console is up. Have a look at where it gets its numbers.
```

**目标：** `https://odyssey.web.2026.sunshinectf.games/`（SunshineCTF 2026，子域经由同 CTF 已知题 TLS 证书 SAN 枚举发现）

## 攻击链

1. **信息收集**：页面 HTML 尾部注释泄露运维信息——console 启动时从 `http://127.0.0.1:8000/feed` 拉取 JSON，可用 `POST / + feed=<url>` 覆盖数据源（SSRF），且有 `feed-debug: source=... bytes=...` 回显 oracle。fetch 到的非 observation 内容全文回显（tape）。
2. **SSRF 探测**：fetcher = PycURL/libcurl 8.14.1，仅 GET、30s 总超时；scheme 校验为 `http://` 前缀（大小写不敏感），`https/ftp/file` 被拒，但 **`gopher://` 放行** → 任意字节 TCP（selector 中 CRLF→`%0d%0a`、空格→`%20` 百分号编码）。
3. **gopher POST 打内网 bureau 服务**（Flask/Werkzeug 3.1.8，同 localhost）：根路径"档案页"泄露 staff 端点：`GET /feed`、`GET /health`、`POST /report`（wkhtmltopdf 0.12.5 渲染 HTML→PDF，base64 回传）。
   - 巨坑：urlencoded body 的 `%XX` 序列被 libcurl 发送前**百分号解码** → CL 虚大 → Werkzeug 永久等 body → 表现为"挂起 30s 超时 0 字节"（非服务端 bug；JSON body 无 `%XX` 秒通）。
4. **/report 渲染原语**：原始请求体即完整 HTML 文档（无需合法 JSON）；wkhtmltopdf 0.12.5 (Qt 4.8.7) **JS 默认启用**。
5. **文件读取**：`<script>x=new XMLHttpRequest;x.open("GET","file:///flag.txt",false);x.send();document.write("<pre>"+x.responseText+"</pre>")</script>` → 文件内容进 PDF → base64 JSON 回传 → PDF 提取文本。
   - 注：file:// XHR 只放行普通文件（目录列举报 NETWORK_ERR）；`/proc/*` 读出空；接口 500 时回显 wkhtmltopdf stderr，可做存在性 oracle。

**Flag：** `sun{s1x_m0r3_w33ks_0f_g0ph3r_ssrf}`（`/flag.txt`，2026-09-27 实测提取）