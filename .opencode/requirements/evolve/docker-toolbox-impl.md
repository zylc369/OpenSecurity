# 需求: Docker 工具箱实施（容器化工具安装 + wrapper 透明调用）

## §1 背景与目标

来源: docker-toolbox.md 调研报告（20 项实测）获用户认可后的落地。目标: 手动清单中 22 项编译类工具迁入容器镜像，AI 经 PATH wrapper 无感调用（与既有 wrapper 模式一致，知识库正文命令零改动）。

## §2 技术方案

- **双层镜像**: `zylc369/opensecurity-toolbox-core`（§3.1 的 22 项 + wordlists + qemu-user/gdb-multiarch + entrypoint 降权，~5.3GB）/ `zylc369/opensecurity-toolbox-full`（core + ghidra + metasploit，~9GB）。
- **Dockerfile 位置**: `control/docker/toolbox-core.Dockerfile`、`toolbox-full.Dockerfile`（full 以 core 为 FROM）。
- **entrypoint 降权**: root 启动 → passwd 注入 u$PUID → setpriv 降权（uid 无关，报告陷阱②修法）。HOME=/tmp/home。
- **DockerRecipe**（detect_tools.py 新配方类型）: `name/image/tool/wrapper 生成`。install 流程: docker 不存在→skip 提示; 镜像不存在→`docker build`（build 一次全层，非逐工具）; wrapper 落 BIN_DIR。
- **wrapper 规范**（报告 §6 蓝本）: `--name` 唯一 + trap kill（陷阱①）; `-e PUID/PGID`; `-v "$PWD":/work -w /work`; 参数绝对路径 `$PWD` 前缀重写为 `/work`; wordlists ro 挂载; `-i` stdin。
- **docker_manager.py 收口**: KNOWN_IMAGES 登记两镜像（控制台可见可拉）; DockerRecipe 的 docker 调用经其 `is_docker_installed`/`image_exists`（grep 唯一性不破——安装器属 detect_tools 自身安装逻辑，检测经 docker_manager）。
- **ghidra/msfvenom/nxc 等多工具共享镜像**: DockerRecipe 按 image 分组，build 幂等（image_exists 即跳过）。

## §3 实现规范

改动: `control/docker/*.Dockerfile` ×2 + entrypoint 脚本、`detect_tools.py`（DockerRecipe+wrapper 生成 ~150 行）、`docker_manager.py`（KNOWN_IMAGES 2 行）、`tool-dependency-index.md`（三分区）、KB 正文（容器工具口径，docker-toolbox.md 已就位作详细参考）。

### §3.1 实施步骤

1. **Dockerfile core + entrypoint**（~60 行）
   - 验证: `docker build` 成功 + entrypoint 降权 whoami 通过 + hashcat -I 设备可见
2. **Dockerfile full**（~10 行，FROM core）
   - 验证: build 成功 + ghidra headless import 冒烟
3. **DockerRecipe + wrapper 生成器**（detect_tools.py ~150 行）
   - 验证: `install --tool steghide` 生成 wrapper; 宿主机 `steghide extract` 全链复跑
4. **docker_manager KNOWN_IMAGES + EXTERNAL_TOOLS 注册**（~40 行）
   - 验证: scan 面容器工具 available; 控制台 import 面
5. **端到端矩阵验证**（steghide/hashcat/nxc/searchsploit/fls/qemu-gdb 每项一条命令）
   - 验证: 全部通过或降级记录
6. **index 三分区 + KB 正文口径 + progress.md**
   - 验证: grep 无"手动"残留矛盾; 计数对齐

## §4 验收标准

- 功能: 无 docker 机器 install 不报错只 skip; 有 docker 机器 `install`（或 `--tool X`）后容器工具 PATH 直呼; 退出码/文件属主/stdin 正确; 孤儿容器零（trap 生效）
- 回归: 既有 33 项二进制自动安装不受影响; docker_manager 既有消费方（事件库 ensure/控制台）零改动; scan CLI 行为不变
- 架构: 依赖方向不变; DockerRecipe 复用 ToolsInstaller 分发框架; 强类型 dataclass

## §5 与现有需求文档的关系

承接 auto-install-external-tools.md（二进制层）——本需求是第三层（容器层），三层齐全后手动清单仅剩 9 项原理性排除项。
