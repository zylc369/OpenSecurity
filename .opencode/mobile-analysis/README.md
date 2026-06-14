# Mobile Analysis — 移动端分析工具与知识库

## 目录结构

```
mobile-analysis/
├── README.md              # 本文件
├── scripts/               # 移动端特有脚本（预留）
│   └── registry.json      # 沉淀脚本注册表
└── knowledge-base/        # 知识库（按需加载）
    ├── android-tools.md       # Android 工具安装 + CLI 参考
    ├── ios-tools.md           # iOS 工具安装 + CLI 参考
    ├── mobile-methodology.md  # 移动端分析方法论（多路径分析决策）
    ├── mobile-frida.md        # 移动端 Frida（安全部署 + Hook）
    └── mobile-patterns.md     # 常见安全模式（证书固定、root 检测等）
```

## 变量约定

| 变量 | 含义 | 说明 |
|------|------|------|
| `$AGENT_DIR` | 本 Agent 的专属目录 | 由 Plugin 注入，指向 mobile-analysis 所在目录 |
| `$SHARED_DIR` | 共享分析能力目录 | 由 Plugin 注入，指向 binary-analysis 所在目录 |

**依赖方向**: `$AGENT_DIR/` 只读引用 `$SHARED_DIR/` 下的文件，不修改。

## 共享资源引用

- IDA Pro 脚本: `$SHARED_DIR/query.py`、`$SHARED_DIR/scripts/initial_analysis.py`
- 通用 Frida 模板: `$SHARED_DIR/knowledge-base/frida-hook-templates.md`
- 通用 Unicorn 模板: `$SHARED_DIR/knowledge-base/unicorn-templates.md`
- IDAPython 编码规范: `$SHARED_DIR/knowledge-base/idapython-conventions.md`
