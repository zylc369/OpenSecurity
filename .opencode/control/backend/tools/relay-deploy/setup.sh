#!/usr/bin/env bash
# relayd 一键部署（目标: 搬瓦工级 VPS，CentOS/Ubuntu 通用; systemd 裸进程，无 Docker/nginx）
# 用法: 在 OpenSecurity 仓库 backend 目录执行
#   bash tools/relay-deploy/setup.sh <VPS_IP或hostname>
# 前置: ssh 免密可登录 root; VPS 可访问 PyPI（或 --offline 用本地打包）
set -euo pipefail

REMOTE="${1:?用法: setup.sh <VPS_IP> [SSH_USER=root]}"
USER="${2:-root}"
DEST="/opt/remote-relayd"
ENVFILE="/etc/remote-relayd/relay.env"

echo "==> 1/6 同步代码（services/remote_* + 入口）"
ssh "$USER@$REMOTE" "mkdir -p $DEST/venv $DEST/services/remote_relayd"
scp services/remote_crypto.py services/remote_signal.py "$USER@$REMOTE:$DEST/services/" >/dev/null
scp services/remote_relayd/*.py "$USER@$REMOTE:$DEST/services/remote_relayd/" >/dev/null
ssh "$USER@$REMOTE" "cd $DEST && touch services/__init__.py && rm -rf services/remote_relayd/__pycache__"

echo "==> 2/6 检测 Python >= 3.9"
PY=$(ssh "$USER@$REMOTE" '
for c in python3.12 python3.11 python3.10 python3.9 python3; do
  command -v $c >/dev/null 2>&1 && $c -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" 2>/dev/null && { echo $c; exit 0; }
done; exit 1') || {
  echo "!! 未找到 Python>=3.9——请先安装（CentOS: dnf install python3.11; Ubuntu: apt install python3.10-venv）"; exit 1; }

echo "==> 3/6 venv + 依赖（cryptography/msgpack）"
ssh "$USER@$REMOTE" "$PY -m venv $DEST/venv && $DEST/venv/bin/pip install -q --upgrade cryptography msgpack"

echo "==> 4/6 PSK 配置"
ssh "$USER@$REMOTE" "mkdir -p /etc/remote-relayd /var/log/remote-relayd"
if ! ssh "$USER@$REMOTE" "test -s $ENVFILE"; then
  PSK=$(ssh "$USER@$REMOTE" "cd $DEST && $DEST/venv/bin/python -m services.remote_relayd genkey")
  ssh "$USER@$REMOTE" "printf 'REMOTE_RELAY_PSK=%s\nREMOTE_RELAY_PORT=41000\n' '$PSK' > $ENVFILE && chmod 600 $ENVFILE"
  echo "    已生成新 PSK（$ENVFILE）——复制到 MacBook/MacMini 的 .ai_env（RELAY_PSK）:"
  echo "    $PSK"
else
  echo "    沿用已有 $ENVFILE"
fi

echo "==> 5/6 systemd 服务"
scp tools/relay-deploy/remote-relayd.service "$USER@$REMOTE:/etc/systemd/system/" >/dev/null
ssh "$USER@$REMOTE" "systemctl daemon-reload && systemctl enable --now remote-relayd"

echo "==> 6/6 防火墙（TCP/UDP 41000）"
ssh "$USER@$REMOTE" '
if command -v firewall-cmd >/dev/null 2>&1; then
  firewall-cmd --add-port=41000/tcp --add-port=41000/udp --permanent && firewall-cmd --reload
elif command -v ufw >/dev/null 2>&1; then
  ufw allow 41000/tcp && ufw allow 41000/udp
else
  echo "    （无 firewalld/ufw——确认云安全组放行 41000 TCP+UDP）"
fi'

echo "✅ 完成。状态: ssh $USER@$REMOTE systemctl status remote-relayd"
echo "   日志: ssh $USER@$REMOTE tail -f /var/log/remote-relayd/relayd.log"
