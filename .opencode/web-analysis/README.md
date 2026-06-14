# web-analysis

Web 安全分析 Agent 的专属目录。

## 目录结构

```
web-analysis/
├── README.md                 # 本文件
└── knowledge-base/           # 知识库（按需加载）
    ├── web-methodology.md    # Web 安全分析方法论
    ├── web-vulnerabilities.md # Web 漏洞模式速查
    └── cache-poisoning.md    # Web Cache Poisoning 专题
```

## 与共享目录的关系

Web analysis 可引用 `$SHARED_DIR`（binary-analysis/）下的通用工具：

- `$SHARED_DIR/scripts/web_render.py` — Playwright 无头浏览器渲染
- `$SHARED_DIR/knowledge-base/` — 通用知识库

依赖方向：web-analysis → $SHARED_DIR（单向，禁止反向依赖）。
