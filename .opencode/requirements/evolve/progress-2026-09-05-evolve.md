# 进化流程进度（2026-09-05 会话）
- Phase 0-1 ✅（复盘+方案确认：A/B/E）
- Phase 2 ✅ 三份需求文档（2026-09-05-{A,B,E}-*.md）
- Phase 3 ✅（3 轮：修复 5 处→复检→纯审计零问题）
- Phase 4 ✅（执行计划+架构图）
- Phase 4.5 ✅（web-analysis.md 展开 384 行 <450）
- Phase 5 进行中：A1✅(llm-perception-verification.md 75行) A2✅(索引+触发规则) B1✅(web-methodology §9, 445→463行) B2✅(无清单记录关闭) E1✅(E1-portable-matrix.md 60工具矩阵)
- 待做：E2(hashcat配方打样)→E3(wrapper路由)→E4(批量迁移)→E5(deps同步)→E6(whisper模型生命周期)→E7(文档同步)→E8(收尾验收)；A/B 的 §4 回归验证（需案例文件路径）
- Phase 6 未开始
## 关键定位信息（下会话直接用）
- detect_tools 安装器：~/.opencode 安装脚本体系（python），装到 ~/bw-security-analysis/bin + tools/
- wrapper 生成器：产出 "# Docker wrapper (auto-generated)" 头的 sh（60个）
- deps 检测后端：控制台 python /api/deps
- whisper 模型现状：~/.cache/whisper 运行时自下载（5个模型 6.8GB）
- brew hashcat 已装(7.1.2, Metal 373.7)——E8 迁移时卸载

## Phase 5 E2 完成（2026-09-05）
- UrlRecipe 扩展: src_names/entries 字段 + SF /download 资产名推断 + tree 分支（_install_url/_install_tree 签名扩展）
- 替换 3 个 DockerRecipe → 便携配方: ffmpeg(osxexperts arm/jvs linux 双架构/gyan win/evermeet x64+Rosetta)、ffprobe(evermeet)、exiftool(SF 官方树+win 单 exe)、ghidra-headless(官方 zip+prereq java，本机未装待验)
- 修复 3 个实现 bug: asset 全平台覆盖误伤、entry 误让 win 走 tree、src_names .exe 全平台生效（_find_file nt 分支本就自动加 .exe）
- 本机实测: exiftool 13.59 ✓ / ffprobe 9.0.1(Rosetta) ✓ / ffmpeg 7.1 arm64 原生 ✓ —— 旧 docker wrapper 已被替换，镜像保留可回滚
- hashcat 按用户指示推迟（win=官方便携/mac=保留 brew/linux=docker 方案已定稿在案）
