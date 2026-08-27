# OpenSecurity 工具箱 core 层 —— 编译类安全工具的容器化（调研依据: knowledge-base/docker-toolbox.md）
# 构建: docker build -f control/docker/toolbox-core.Dockerfile -t opensecurity/toolbox-core:latest control/docker
# 双架构: kali-rolling 原生 arm64/amd64（Apple Silicon 无模拟损耗）
FROM kalilinux/kali-rolling

# ── 工具清单（调研 §3.1 实测/包确认 22 项 + 支撑件）──
# 陷阱修法已吸收:
#   * one_gadget 分析 amd64 libc 需 binutils-multiarch（否则 UnsupportedArchitectureError）
#   * Sleuth Kit 全链需 e2fsprogs（mkfs/debugfs）
#   * hashcat CPU 模式需 pocl-opencl-icd（OpenCL CPU 设备）
#   * outguess/stegdetect 已被 kali 移除——不装（维持手动）
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    steghide stegseek john hashcat nmap hydra medusa ncrack \
    sleuthkit e2fsprogs libimage-exiftool-perl tshark \
    mingw-w64 nasm radare2 binwalk \
    exploitdb netexec wpscan \
    sox imagemagick mupdf-tools boolector qemu-system-x86 icoutils \
    pcapfix xfsprogs cryptsetup btrfs-progs \
    dsniff gdb gdbserver maven openjdk-21-jdk-headless smtp-user-enum upx-ucl bloodhound \
    ruby ruby-dev rubygems-integration build-essential binutils-multiarch \
    gdb-multiarch qemu-user libc6-amd64-cross \
    wordlists \
    git wget curl file procps p7zip-full unzip xz-utils util-linux \
    && gem install one_gadget seccomp-tools zsteg --no-document \
    && rm -rf /var/lib/apt/lists/*

# PHPGGC（php 运行时 + git）
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends php-cli wget unzip \
    && git clone --depth 1 https://github.com/ambionics/phpggc /opt/phpggc \
    && ln -sf /opt/phpggc/phpggc /usr/local/bin/phpggc \
    && rm -rf /var/lib/apt/lists/*

# pwndbg（gdb 插件——堆调试）
RUN git clone --depth 1 https://github.com/pwndbg/pwndbg /opt/pwndbg \
    && cd /opt/pwndbg && ./setup.sh > /dev/null 2>&1 || true \
    && printf '#!/bin/sh\nexport PWNDBG_NO_AUTOUPDATE=1\nexec gdb -ix /opt/pwndbg/gdbinit.py "$@"\n' > /usr/local/bin/gdb-pwndbg \
    && chmod 755 /usr/local/bin/gdb-pwndbg
ENV PWNDBG_NO_AUTOUPDATE=1

# marshalsec（maven build）
RUN git clone --depth 1 https://github.com/mbechler/marshalsec /opt/marshalsec \
    && cd /opt/marshalsec \
    && JAVA_HOME=/usr/lib/jvm/java-21-openjdk-$(dpkg --print-architecture) mvn -q clean package -DskipTests \
    && printf '#!/bin/sh\n# 用法: marshalsec <Marshaller|jndi.工具类> [args]  例: marshalsec jndi.LDAPRefServer http://T/#Exploit 8088\nMC="$1"; shift\nexec java -cp "/opt/marshalsec/target/marshalsec-0.0.3-SNAPSHOT-all.jar:./" "marshalsec.$MC" "$@"\n' > /usr/local/bin/marshalsec \
    && chmod 755 /usr/local/bin/marshalsec

# wpscan DB 预热（缺 DB 拒跑——build 期烘入; root 期 HOME 可写）
RUN wpscan --update || true

# ── 运行时降权 entrypoint（uid 无关; 调研陷阱②修法）──
# root 启动 → passwd 注入 u$PUID → setpriv 降权 exec; HOME=/tmp/home 可写（陷阱③）
RUN printf '%s\n' \
    '#!/bin/sh' \
    'PUID=${PUID:-1000}; PGID=${PGID:-1000}' \
    'grep -q ":$PUID:" /etc/passwd || echo "u$PUID:x:$PUID:$PGID::/tmp/home:/bin/sh" >> /etc/passwd' \
    'mkdir -p /tmp/home && chmod 1777 /tmp/home' \
    'exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups env HOME=/tmp/home "$@"' \
    > /ep.sh && chmod 755 /ep.sh

ENTRYPOINT ["/ep.sh"]
