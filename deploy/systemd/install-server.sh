#!/usr/bin/env bash
set -euo pipefail

# 用法：sudo bash deploy/systemd/install-server.sh /path/to/SelfShare
SOURCE_DIR="${1:-$(cd "$(dirname "$0")/../.." && pwd)}"
INSTALL_DIR=/opt/selfshare
DATA_DIR=/var/lib/selfshare
CONFIG_DIR=/etc/selfshare

if [[ $EUID -ne 0 ]]; then
  echo "请使用 root 运行：sudo bash $0 $SOURCE_DIR" >&2
  exit 1
fi

id selfshare >/dev/null 2>&1 || \
  useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin selfshare

install -d -o root -g root -m 0755 "$INSTALL_DIR"
install -d -o selfshare -g selfshare -m 0750 "$DATA_DIR"
install -d -o root -g selfshare -m 0750 "$CONFIG_DIR"

# 只复制运行所需文件，避免把测试数据和构建缓存放进 /opt。
install -m 0755 "$SOURCE_DIR/selfshare.py" "$INSTALL_DIR/selfshare.py"
rm -rf "$INSTALL_DIR/selfshare"
cp -a "$SOURCE_DIR/selfshare" "$INSTALL_DIR/selfshare"
find "$INSTALL_DIR/selfshare" -type f -exec chmod 0644 {} +
find "$INSTALL_DIR/selfshare" -type d -exec chmod 0755 {} +
install -m 0644 "$SOURCE_DIR/README.md" "$INSTALL_DIR/README.md"

if [[ ! -f "$CONFIG_DIR/server.env" ]]; then
  install -o root -g selfshare -m 0640 \
    "$SOURCE_DIR/deploy/systemd/server.env.example" "$CONFIG_DIR/server.env"
fi
install -o root -g root -m 0644 \
  "$SOURCE_DIR/deploy/systemd/selfshare-server.service" \
  /etc/systemd/system/selfshare-server.service

systemctl daemon-reload
systemctl enable --now selfshare-server.service
systemctl --no-pager --full status selfshare-server.service

echo
printf '安装完成。\n  配置：%s/server.env\n  数据：%s\n  日志：journalctl -u selfshare-server -f\n' \
  "$CONFIG_DIR" "$DATA_DIR"
