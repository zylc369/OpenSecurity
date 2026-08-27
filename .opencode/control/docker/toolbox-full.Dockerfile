# OpenSecurity 工具箱 full 层 —— core + ghidra + metasploit（低频大件; 调研 §3.2）
# 构建: docker build -f control/docker/toolbox-full.Dockerfile -t opensecurity/toolbox-full:latest control/docker
# （build context 为 control/docker; core Dockerfile 同目录）
FROM opensecurity/toolbox-core:latest

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ghidra metasploit-framework default-jre-headless \
    && rm -rf /var/lib/apt/lists/*

# ghidra headless 在降权下的运行配置（-Duser.home; JVM 内存上限由 wrapper 侧 _JAVA_OPTIONS 传）
ENV GHIDRA_INSTALL_DIR=/usr/share/ghidra
