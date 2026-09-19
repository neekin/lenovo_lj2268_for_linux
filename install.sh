#!/usr/bin/env bash
#
# Lenovo LJ2268 / LJ2268W  Linux 打印驱动安装
#
# 设计原则: 默认只做一件事 —— 装驱动 + 建队列。
#   不改全局 CUPS 配置、不改默认打印机、不碰 AirPrint。
#   (很多人是在已有的 CUPS 上加装这台打印机, 安装脚本不应该有副作用)
#
# 用法:
#   sudo ./install.sh                          # 只装驱动 (最小侵入)
#   sudo ./install.sh --airprint               # 额外开启共享 + AirPrint 广播
#   sudo ./install.sh --unicast 192.168.1.30           # mDNS 单播兜底 (手机 IP)
#   sudo ./install.sh --unicast 192.168.1.30,192.168.1.35   # 多个用逗号分隔
#   AIRPRINT_IFACE=eth0 sudo ./install.sh --airprint   # 网卡不是 wlan0 时
#   sudo ./install.sh --prebuilt               # 跳过编译, 用 prebuilt/ 的 armhf 二进制
#   sudo ./install.sh --queue LJ2268           # 自定义队列名
#   sudo ./install.sh --force                  # 同名队列已存在时覆盖
#   sudo ./install.sh --set-default            # 强制设为默认打印机
#   sudo ./install.sh usb://Lenovo/LJ2268?serial=XXX   # 手动指定设备 URI
#
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------- 0. 权限 (必须最先: sudo 重执行要求 $@ 还是原始参数) ----------
if [ "$(id -u)" -ne 0 ]; then
  echo "需要 root: 请以 sudo 运行 (CUPS 拒绝执行非 root 拥有的 filter)"
  exec sudo "$0" "$@"
fi

QUEUE="Lenovo-LJ2268"
USE_PREBUILT=0
ENABLE_AIRPRINT=0
UNICAST_IP=""
FORCE=0
SET_DEFAULT=0
DEVICE_URI=""

while [ $# -gt 0 ]; do
  case "$1" in
    --prebuilt)    USE_PREBUILT=1; shift ;;
    --airprint)    ENABLE_AIRPRINT=1; shift ;;
    --force)       FORCE=1; shift ;;
    --set-default) SET_DEFAULT=1; shift ;;
    --queue|-q)    shift; QUEUE="${1:?--queue 需要一个队列名}"; shift ;;
    --unicast)
      shift
      UNICAST_IP="${1:-}"
      [ -n "$UNICAST_IP" ] || { echo "错误: --unicast 后面要跟一个 iPhone 的 IP"; exit 1; }
      ENABLE_AIRPRINT=1; shift ;;
    -h|--help)     sed -n '2,20p' "$0"; exit 0 ;;
    usb://*)       DEVICE_URI="$1"; shift ;;
    *)             echo "未知参数: $1"; echo; sed -n '2,20p' "$0"; exit 1 ;;
  esac
done

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
ask_yn() { # ask_yn "提示" -> 0=是 1=否
  local r; read -rp "$1 [y/N] " r
  case "${r:-N}" in y|Y) return 0 ;; *) return 1 ;; esac
}

# ---------- 1. 依赖 ----------
say "检查依赖"
MISSING=""
command -v lpadmin  >/dev/null || MISSING="$MISSING cups"
command -v pdftoppm >/dev/null || MISSING="$MISSING poppler-utils"

# 逐个探测: 不能把多个 glob 一起喂给 ls —— 只要有一个路径不存在 ls 就整体返回非 0,
# 会把明明已安装的库误判成缺失
HAVE_JBIG=0
for f in /usr/lib/*/libjbig.so.0 /usr/lib/libjbig.so.0 /usr/lib64/libjbig.so.0; do
  [ -e "$f" ] && { HAVE_JBIG=1; break; }
done
[ "$HAVE_JBIG" = 1 ] || MISSING="$MISSING libjbig0"

if [ -n "$MISSING" ]; then
  echo "缺少依赖:$MISSING"
  if command -v apt-get >/dev/null && ask_yn "现在 apt 安装?"; then
    apt-get update -qq; apt-get install -y $MISSING
  else
    echo "请先手动安装后再重试"; exit 1
  fi
fi
command -v gcc >/dev/null || echo "  提示: 无 gcc, 将使用预编译二进制"

# ---------- 2. 编译 (复用 Makefile, 单一真相源) ----------
if [ "$USE_PREBUILT" = 1 ] || ! command -v gcc >/dev/null; then
  say "使用预编译二进制 (armhf)"
  BIN="$DIR/prebuilt/rastertolhpl-armhf"
  [ -f "$BIN" ] || { echo "prebuilt 二进制不存在, 且无法编译"; exit 1; }
else
  say "编译 rastertolhpl"
  cd "$DIR"
  if ! make >/tmp/lj2268_build.log 2>&1; then
    echo "编译失败, 输出如下:"; cat /tmp/lj2268_build.log; exit 1
  fi
  BIN="$DIR/rastertolhpl"
fi

# ---------- 3. 探测打印机 ----------
if [ -z "$DEVICE_URI" ]; then
  say "探测 USB 打印机"
  # 1) 按厂商名匹配
  #    set -e 下命令替换的退出状态会被继承, grep 无匹配(返回1)会直接终止脚本, 必须 || true
  DEVICE_URI="$(lpinfo -v 2>/dev/null | awk '/^direct usb:\/\// {print $NF}' \
               | grep -iE 'lenovo|lj2268' | head -1 || true)"
  # 2) 按 USB ID (17ef:5439 = Lenovo LJ2268) 兜底
  if [ -z "$DEVICE_URI" ] && command -v lsusb >/dev/null \
     && lsusb -d 17ef:5439 >/dev/null 2>&1; then
    DEVICE_URI="$(lpinfo -v 2>/dev/null | awk '/^direct usb:\/\// {print $NF}' | head -1 || true)"
  fi
  # 3) 仍未识别 -> 交给用户指定
  if [ -z "$DEVICE_URI" ]; then
    echo "未能自动识别。当前可用 USB 设备:"
    lpinfo -v 2>/dev/null | grep usb || echo "  (无)"
    if [ -t 0 ]; then read -rp "请输入要使用的 URI: " DEVICE_URI; fi
    [ -n "$DEVICE_URI" ] || { echo "已取消。用法: sudo $0 usb://..."; exit 1; }
  fi
fi
echo "  设备: $DEVICE_URI"

# ---------- 4. 同名队列保护 (别人的队列不能静默删) ----------
# lpstat -a 输出形如 "队列名 accepting requests since ...", 要取第一列再比对,
# 不能用 grep -qx 做整行精确匹配
if lpstat -a 2>/dev/null | awk '{print $1}' | grep -qx "$QUEUE"; then
  if [ "$FORCE" = 1 ]; then
    say "覆盖已存在的队列 $QUEUE"
    lpadmin -x "$QUEUE"
  else
    echo "错误: 队列 '$QUEUE' 已存在, 为避免破坏现有配置已中止。"
    echo "  覆盖它:   sudo $0 --force"
    echo "  换个名字: sudo $0 --queue LJ2268"
    exit 1
  fi
fi

# ---------- 5. 安装 filter + PPD ----------
say "安装 filter 与 PPD"
install -o root -g root -m 0755 "$BIN" /usr/lib/cups/filter/rastertolhpl
install -o root -g root -m 0644 "$DIR/ppd/LJ2268-lhpl.ppd" /usr/share/cups/model/LJ2268-lhpl.ppd

# ---------- 6. 建队列 ----------
say "创建打印队列 $QUEUE"
lpadmin -p "$QUEUE" -D "Lenovo LJ2268 (LHPL open driver)" -L "Home" \
        -P /usr/share/cups/model/LJ2268-lhpl.ppd -v "$DEVICE_URI" -E 2>/dev/null
cupsaccept "$QUEUE" 2>/dev/null || true
cupsenable "$QUEUE" 2>/dev/null || true

# 默认打印机: 只有原本一台队列都没有时才自动设; 已有环境不抢别人的默认
if [ "$SET_DEFAULT" = 1 ]; then
  lpadmin -d "$QUEUE"
  echo "  已设为默认打印机"
else
  EXISTING="$(lpstat -a 2>/dev/null | wc -l || true)"
  if [ "${EXISTING:-0}" -le 1 ]; then
    lpadmin -d "$QUEUE"
    echo "  当前无其他队列, 已设为默认打印机"
  else
    echo "  保留您原有的默认打印机。需要改的话: sudo lpadmin -d $QUEUE"
  fi
fi

if [ "$ENABLE_AIRPRINT" = 0 ]; then
  echo "  未开启共享 (保持您现有的 CUPS 配置不变)"
fi

sleep 2
# lpstat -p 在队列刚建时可能报 Invalid destination name, 其非 0 退出码会触发 set -e, 必须吃掉
lpstat -p "$QUEUE" 2>/dev/null || echo "  (队列刚建, 稍等片刻再查: lpstat -p $QUEUE)"

# ---------- 7. AirPrint (默认关闭, 需 --airprint 显式开启) ----------
if [ "$ENABLE_AIRPRINT" = 1 ]; then
  say "开启共享并安装 AirPrint 广播"
  # 队列级共享 + 631 对外监听。刻意不用 cupsctl --remote-admin: 那会开放远程管理
  lpadmin -p "$QUEUE" -o printer-is-shared=true
  cupsctl --share-printers --remote-any 2>/dev/null || true

  U="${SUDO_USER:-$USER}"
  H="$(getent passwd "$U" 2>/dev/null | cut -d: -f6)"
  if [ -n "$H" ] && [ -d "$H" ]; then
    RT="/run/user/$(id -u "$U")"
    as_u() { sudo -u "$U" XDG_RUNTIME_DIR="$RT" DBUS_SESSION_BUS_ADDRESS="unix:path=$RT/bus" "$@"; }
    install -o "$U" -m 0755 "$DIR/print/scripts/airprint_pub.py" "$H/airprint_pub.py"
    install -o "$U" -m 0755 "$DIR/print/scripts/airprint_push.py" "$H/airprint_push.py"
    install -o "$U" -m 0755 "$DIR/print/scripts/check_txt.py" "$H/check_txt.py"
    mkdir -p "$H/.config/systemd/user"
    install -o "$U" -m 0644 "$DIR/print/systemd/airprint.service" \
                            "$H/.config/systemd/user/airprint.service"
    install -o "$U" -m 0644 "$DIR/print/systemd/airprint-push.service" \
                            "$H/.config/systemd/user/airprint-push.service"

    # 队列名/网卡/种子目标用 drop-in 注入, 免得改动仓库里的 service 文件
    for svc in airprint.service airprint-push.service; do
      mkdir -p "$H/.config/systemd/user/$svc.d"
      cat > "$H/.config/systemd/user/$svc.d/env.conf" <<ENVEOF
[Service]
Environment=AIRPRINT_QUEUE=$QUEUE
Environment=AIRPRINT_IFACE=${AIRPRINT_IFACE:-wlan0}
Environment=AIRPRINT_SEEDS=$UNICAST_IP
ENVEOF
      chown "$U" "$H/.config/systemd/user/$svc.d" "$H/.config/systemd/user/$svc.d/env.conf"
    done

    as_u systemctl --user daemon-reload
    as_u systemctl --user enable --now airprint.service airprint-push.service
    loginctl enable-linger "$U" 2>/dev/null || true
    # systemctl is-active 对未激活服务返回非 0, 必须吃掉否则 set -e 会中断
    AIR="$(as_u systemctl --user is-active airprint.service || true)"
    PUSH="$(as_u systemctl --user is-active airprint-push.service || true)"
    echo "  airprint.service:      ${AIR:-inactive}"
    echo "  airprint-push.service: ${PUSH:-inactive}"
    [ -n "$UNICAST_IP" ] && echo "  单播种子目标: $UNICAST_IP"
  fi
fi

say "完成"
cat <<EOF
打印测试:
  lp -d $QUEUE test/hello.pdf
  lp -d $QUEUE <任意文件.pdf>
EOF
[ "$ENABLE_AIRPRINT" = 1 ] && cat <<EOF

iPhone / 局域网共享: 分享 → 打印 → 选择打印机 → AirPrint Lenovo LJ2268
EOF
exit 0
