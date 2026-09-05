# E1 便携版可行性矩阵（60 个 docker wrapper 逐工具审计）
判定：✓=官方便携包三平台可得；△=部分平台可得/功能受限；✗=无便携版必须 docker
## 第一批（性能敏感，优先迁移）
| 工具 | win | linux | macos | 备注 |
|------|-----|-------|-------|------|
| hashcat | ✓官方 .7z | ✓官方 .7z | ✓官方 .7z（Metal 内置）| 打样对象 |
| john-jumbo | ✓社区 winx64 | ✓官方推荐构建 | △稀缺(brew 为主) | mac 回落 docker |
| ffmpeg/ffprobe | ✓gyan.dev | ✓johnvansickle 静态 | ✓evermeet | 三平台全便携 |
| hydra/medusa/ncrack/ghidra-headless/gdb/r2/qemu-* | △逐个核 | △ | △ | 二批核 |
## 第二批（取证/隐写，多为 Python/脚本生态）
| 工具 | 判定 | 备注 |
|------|------|------|
| binwalk-full/stegseek/testdisk/photorec/foremost/pcapfix | ✗ Linux 原生为主 | 保留 docker |
| exiftool/sox/mutool/convert(imagemagick)/upx/nasm | ✓ 官方单二进制多平台 | 三批迁（本就接近便携）|
| aleapp/ccupp/marshalsec/phpggc/wpscan/zsteg 等 | △ perl/ruby/java 生态依赖 | 逐个定 |
| nmap | △ win 需 npcap 驱动(要权限) | win 回落 docker；mac/linux 有便携源码构建 |
| tshark | △ mac 为 .pkg 安装器 | 本期保 docker+过滤器修补，便携列四批 |
## 三级回落策略（全局）
便携(tools/) → docker（现有 wrapper 兜底）→ 明确报错+install.sh 指引
## 待 Phase 5 步骤 2-4 逐工具核实下载 URL+SHA256（本矩阵为路由级判定）
