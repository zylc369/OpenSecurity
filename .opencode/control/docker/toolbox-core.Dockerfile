# OpenSecurity 工具箱 core 层 —— 编译类安全工具的容器化（调研依据: control/docker/toolbox-design.md）
# 构建: ./docker-build-toolbox.sh（双架构; 单架构 --arch arm64|amd64）
# 双架构: kali-rolling 原生 arm64/amd64（Apple Silicon 无模拟损耗）
# 多阶段: builder 承载全部构建链（JDK/maven/gcc/ruby-dev），final 只含运行时——功能零损失瘦身
#   * mingw 只装 posix 变体（win32/posix 是 SEH 异常模型变体，命令同名同用法）
#   * openjdk-11（maven 拖入的双 JRE）随构建链消失; final 仅 openjdk-21-jre-headless
#   * 各 git clone 同层 rm .git
FROM kalilinux/kali-rolling AS builder

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    openjdk-21-jdk-headless maven build-essential \
    ruby ruby-dev rubygems-integration \
    git wget curl \
    && rm -rf /var/lib/apt/lists/*

# gems（纯 ruby）+ marshalsec（mvn 编译）+ pwndbg（venv 装依赖）
RUN gem install one_gadget seccomp-tools zsteg --no-document \
    && git clone --depth 1 https://github.com/mbechler/marshalsec /opt/marshalsec \
    && cd /opt/marshalsec \
    && JAVA_HOME=/usr/lib/jvm/java-21-openjdk-$(dpkg --print-architecture) mvn -q clean package -DskipTests \
    && rm -rf /opt/marshalsec/.git \
    && git clone --depth 1 https://github.com/pwndbg/pwndbg /opt/pwndbg \
    && cd /opt/pwndbg && ./setup.sh > /dev/null 2>&1 || true \
    ; rm -rf /opt/pwndbg/.git

# ── final: 运行时 ──
FROM kalilinux/kali-rolling

# builder 产物（路径与 builder 一致 → venv/入口自包含）
COPY --from=builder /var/lib/gems /var/lib/gems
COPY --from=builder /usr/local/bin/one_gadget /usr/local/bin/seccomp-tools /usr/local/bin/zsteg /usr/local/bin/zsteg-mask /usr/local/bin/zsteg-reflow /usr/local/bin/
COPY --from=builder /opt/marshalsec /opt/marshalsec
COPY --from=builder /opt/pwndbg /opt/pwndbg

# ── 工具清单（toolbox-design.md 实测/包确认; 陷阱修法已吸收）──
#   * one_gadget 分析 amd64 libc 需 binutils-multiarch（否则 UnsupportedArchitectureError）
#   * Sleuth Kit 全链需 e2fsprogs（mkfs/debugfs）
#   * hashcat CPU 模式需 pocl-opencl-icd（OpenCL CPU 设备）——由 hashcat 包依赖拉入
#   * outguess/stegdetect 已被 kali 移除——不装
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    steghide stegseek john hashcat nmap hydra medusa ncrack \
    sleuthkit e2fsprogs libimage-exiftool-perl tshark \
    gcc-mingw-w64-x86-64-posix g++-mingw-w64-x86-64-posix gcc-mingw-w64-i686-posix g++-mingw-w64-i686-posix \
    nasm radare2 binwalk \
    exploitdb netexec wpscan \
    sox imagemagick mupdf-tools boolector qemu-system-x86 icoutils \
    pcapfix xfsprogs cryptsetup btrfs-progs \
    dsniff gdb gdbserver openjdk-21-jre-headless smtp-user-enum upx-ucl bloodhound \
    ruby rubygems-integration binutils-multiarch \
    gdb-multiarch qemu-user libc6-amd64-cross \
    wordlists \
    git wget curl file procps p7zip-full unzip xz-utils util-linux \
    && setcap -r /usr/lib/nmap/nmap 2>/dev/null || true \
    && rm -rf /var/lib/apt/lists/*

# 入口脚本（引用 final 层的 java/gdb）
RUN printf '#!/bin/sh\n# 用法: marshalsec <Marshaller|jndi.工具类> [args]  例: marshalsec jndi.LDAPRefServer http://T/#Exploit 8088\nMC="$1"; shift\nexec java -cp "/opt/marshalsec/target/marshalsec-0.0.3-SNAPSHOT-all.jar:./" "marshalsec.$MC" "$@"\n' > /usr/local/bin/marshalsec \
    && chmod 755 /usr/local/bin/marshalsec \
    && printf '#!/bin/sh\nexport PWNDBG_NO_AUTOUPDATE=1\nexec gdb -ix /opt/pwndbg/gdbinit.py "$@"\n' > /usr/local/bin/gdb-pwndbg \
    && chmod 755 /usr/local/bin/gdb-pwndbg
ENV PWNDBG_NO_AUTOUPDATE=1

# PHPGGC（php 运行时 + git）
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends php-cli wget unzip \
    && git clone --depth 1 https://github.com/ambionics/phpggc /opt/phpggc \
    && rm -rf /opt/phpggc/.git \
    && ln -sf /opt/phpggc/phpggc /usr/local/bin/phpggc \
    && rm -rf /var/lib/apt/lists/*

# wpscan DB 预热（缺 DB 拒跑——build 期烘入; root 期 HOME 可写）
RUN wpscan --update || true

# ── 运行时降权 entrypoint（uid 无关）──
# root 启动 → passwd 注入 u$PUID → setpriv 降权 exec; HOME=/tmp/home 可写
RUN printf '%s\n' \
    '#!/bin/sh' \
    'PUID=${PUID:-1000}; PGID=${PGID:-1000}' \
    'grep -q ":$PUID:" /etc/passwd || echo "u$PUID:x:$PUID:$PGID::/tmp/home:/bin/sh" >> /etc/passwd' \
    'mkdir -p /tmp/home && chmod 1777 /tmp/home' \
    'exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups env HOME=/tmp/home "$@"' \
    > /ep.sh && chmod 755 /ep.sh

ENTRYPOINT ["/ep.sh"]
