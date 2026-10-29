# OpenSecurity 工具箱 full 层 —— core + ghidra + metasploit（低频大件; 调研 §3.2）
# 构建: ./docker-build-toolbox.sh（full 由脚本按架构自动传 CORE_REF）
# （build context 为 control/docker; core Dockerfile 同目录）
# CORE_REF: 按目标架构传基座 tag（默认 arm64; amd64 构建时 --build-arg CORE_REF=...:amd64）
ARG CORE_REF=zylc369/opensecurity-toolbox-core:arm64
FROM ${CORE_REF}

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ghidra metasploit-framework \
    && rm -rf /var/lib/apt/lists/*

# ghidra headless 在降权下的运行配置（-Duser.home; JVM 内存上限由 wrapper 侧 _JAVA_OPTIONS 传）
ENV GHIDRA_INSTALL_DIR=/usr/share/ghidra
