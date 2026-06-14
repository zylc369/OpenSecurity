# 进化-python命令问题

## 疑问一

if (envInfo.venv_python) {
      envSection += `- BA_PYTHON: ${envInfo.venv_python}\n`;
    }
BA_PYTHON是python的虚拟环境目录，还是虚拟环境中的Python？如果它是虚拟环境中的python，那么为什么还需要系统Python？虚拟环境是在什么时候创建的？

如果创建虚拟环境需要系统pyhton，那么此处可能会有先后顺序。


## 疑问二

所有平台统一使用环境检测脚本（Windows 用 `python`，Linux/macOS 用 `python3`）

为什么不直接注入Python变量？

## 疑问三

```bash
# 检测全部工具（默认）
python3 detect_env.py --force

# 仅检测 binary-analysis 需要的工具
python3 detect_env.py --force --agent binary-analysis

# 仅检测 mobile-analysis 需要的工具
python3 detect_env.py --force --agent mobile-analysis
```

> **Windows 用户**：将上面的 `python3` 替换为 `python`。


为什么不直接注入Python变量？