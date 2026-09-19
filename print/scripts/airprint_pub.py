#!/usr/bin/env python3
"""
AirPrint DNS-SD publisher for shared CUPS queue (Lenovo LJ2268, LHPL open driver).

为什么需要它：
  iOS 打印中心只认带 _universal._sub._ipp._tcp 子类型的服务。
  本机打印机是 CMD:GDI 主机型，走经典驱动队列，故由本脚本补发子类型。

协议栈必须留 UNSPEC（重要，曾经踩反过）：
  接口要收窄（避免 iPhone 拿到 docker0 这类不可达地址），但协议栈不能收窄成 IPv4-only：
  实测某些网络 IPv4 组播几乎不通，邻居服务全靠 IPv6 组播互通，只发 IPv4 会彻底搜不到。
  默认 AVAHI_PROTO_UNSPEC(-1)，让 avahi 在该接口上同时发 IPv4 + IPv6。
  确需单栈用环境变量：AIRPRINT_PROTO=0(IPv4) / 1(IPv6)。

必须自动重连（重要）：
  avahi-daemon 一旦重启，会清空所有已注册的 entry group，本服务的广播就消失了。
  而且 CUPS 自己那条记录太长，avahi 日志会报
  "not fitting in legacy unicast packet, dropping" —— 单播查询时拿不到完整响应。
  所以这里每隔 REFRESH 秒完整重发一次（Reset + Commit），既能自动恢复，
  又能周期性刷新公告，便于 iOS 的被动缓存拿到记录。

为什么 TXT 里必须有 URF（实测结论，曾走过弯路）：
  iOS 的 AirPrint 选择器要求 pdl 含 image/urf 且有 URF 键，否则根本不列出打印机
  （macOS 无此过滤，所以"Mac 能看到但 iPhone 看不到"就是缺 URF 的典型症状）。
  实测 iOS 18/26 在 pdl 同时含 application/pdf 时发送的是 PDF，无需 urftopdf，
  CUPS 直接走 rastertolhpl 即可。URF 键只用于通过 iOS 的列表验证。

为什么 UUID 必须与 CUPS 队列的 printer-uuid 一致：
  iOS 会用 TXT 的 UUID 与 IPP Get-Printer-Attributes 返回的 printer-uuid 做匹配，
  不一致时可能忽略该服务（表现为选中即报"缺少打印机的软件"）。

  【本脚本已自动探测，无需手工同步】每次发公告都会重新向本机 CUPS 查询
  printer-uuid，队列被 lpadmin -x 重建导致 UUID 变化时，最多 REFRESH 秒后自动跟上。
  手工指定用环境变量 AIRPRINT_UUID=...；探测失败则回落 FALLBACK_UUID。
  手工核实命令：
    ipptool -tv ipp://localhost:631/printers/<队列名> get-printer-attributes.test \\
      | grep printer-uuid
  （注意必须带 -tv，否则 ipptool 静默无输出）

为什么去掉 TLS=1.2：
  声明 TLS 会让 iOS 优先走 ipps(631/TLS)，而本机 CUPS 只有自签名证书，
  iOS 不信任 → 失败。本机只有明文 ipp，故不声明。

权限优势：直接调 avahi 的 D-Bus 接口，普通用户即可，无需 root。
"""

import dbus
import time
import os
import re
import subprocess
import sys

AVAHI_NAME = "org.freedesktop.Avahi"
PATH_SERVER = "/"
IFACE_SERVER = "org.freedesktop.Avahi.Server"
IFACE_ENTRY_GROUP = "org.freedesktop.Avahi.EntryGroup"
DOMAIN = ""

AVAHI_IF_UNSPEC = -1
AVAHI_PROTO_UNSPEC = -1      # 双栈：IPv4 + IPv6
AVAHI_PROTO_INET = 0
AVAHI_PROTO_INET6 = 1

IFACE_NAME = os.environ.get("AIRPRINT_IFACE", "wlan0")
PROTO = int(os.environ.get("AIRPRINT_PROTO", str(AVAHI_PROTO_UNSPEC)))
REFRESH = int(os.environ.get("AIRPRINT_REFRESH", "60"))
NAME = os.environ.get("AIRPRINT_NAME", "AirPrint Lenovo LJ2268")
QUEUE = os.environ.get("AIRPRINT_QUEUE", "Lenovo-LJ2268")
STYPE = "_ipp._tcp"
SUBTYPE = "_universal._sub._ipp._tcp"
PORT = 631
RP = "printers/" + QUEUE

# 探测失败时的回退值（换新设备时改这里，或直接设环境变量）
FALLBACK_UUID = "0aae3f45-e6f5-3e9b-5afe-5f389701a6c0"
FALLBACK_IP = "192.168.1.31"


def detect_uuid():
    """向本机 CUPS 查询队列的 printer-uuid；失败返回 None。"""
    try:
        out = subprocess.check_output(
            ["ipptool", "-tv", "ipp://localhost:631/printers/" + QUEUE,
             "get-printer-attributes.test"],
            stderr=subprocess.DEVNULL, timeout=15).decode("utf-8", "replace")
        m = re.search(r"printer-uuid\s*\(uri\)\s*=\s*urn:uuid:(\S+)", out)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def detect_ip():
    """取 IFACE_NAME 上的 IPv4；失败返回 None。"""
    try:
        out = subprocess.check_output(
            ["ip", "-4", "-o", "addr", "show", IFACE_NAME],
            stderr=subprocess.DEVNULL, timeout=5).decode()
        m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)/", out)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def build_txt(uuid, ip):
    return [
        "txtvers=1",
        "qtotal=1",
        "rp=" + RP,
        "ty=Lenovo LJ2268 (LHPL)",
        "product=(Lenovo LJ2268)",
        "printer-state=3",
        "printer-type=0x900E",
        # 必须与 CUPS 队列的 printer-uuid 一致（已自动探测）
        "UUID=" + uuid,
        # iOS AirPrint 列表要求 pdl 含 image/urf 且有 URF 键，否则不显示
        "pdl=application/pdf,image/urf",
        "URF=CP1,PQ3-4-5",
        "Color=F",
        "Duplex=F",
        "priority=0",
        "note=Home",
        "adminurl=http://%s:631/%s" % (ip, RP),
    ]

PROTO_NAME = {AVAHI_PROTO_UNSPEC: "IPv4+IPv6", AVAHI_PROTO_INET: "IPv4",
              AVAHI_PROTO_INET6: "IPv6"}.get(PROTO, str(PROTO))


class Publisher:
    def __init__(self):
        self.bus = dbus.SystemBus()
        self.server = None
        self.group = None
        self.ifindex = AVAHI_IF_UNSPEC
        _uuid = os.environ.get("AIRPRINT_UUID") or detect_uuid()
        _ip = os.environ.get("AIRPRINT_IP") or detect_ip()
        self.uuid = _uuid or FALLBACK_UUID
        self.ip = _ip or FALLBACK_IP
        # 用"探测是否成功"判断是否用了回退值; 不能拿值去比 —— 探测值可能恰好等于回退值
        self.using_fallback = (_uuid is None) or (_ip is None)

    def refresh_facts(self):
        """每次发公告前重新探测: 队列重建换了 UUID、DHCP 换了 IP 都能自动跟上。"""
        if not os.environ.get("AIRPRINT_UUID"):
            u = detect_uuid()
            if u and u != self.uuid:
                print("[%s] printer-uuid 变化: %s -> %s"
                      % (time.strftime("%H:%M:%S"), self.uuid, u), flush=True)
                self.uuid = u
        if not os.environ.get("AIRPRINT_IP"):
            i = detect_ip()
            if i:
                self.ip = i

    def connect(self):
        self.server = dbus.Interface(
            self.bus.get_object(AVAHI_NAME, PATH_SERVER), IFACE_SERVER)
        try:
            self.ifindex = int(self.server.GetNetworkInterfaceIndexByName(IFACE_NAME))
        except Exception as e:
            print("WARN: cannot resolve iface %s (%s), using all" % (IFACE_NAME, e), flush=True)
            self.ifindex = AVAHI_IF_UNSPEC

    def publish(self):
        # 先释放上一个 group，否则反复注册会产生 "xxx (2)" 这类重复服务
        if self.group is not None:
            for method in ("Reset", "Free"):
                try:
                    getattr(self.group, method)()
                except Exception:
                    pass
            self.group = None

        self.refresh_facts()
        txt_array = dbus.Array(
            [dbus.Array([dbus.Byte(c) for c in t.encode()], signature="y")
             for t in build_txt(self.uuid, self.ip)],
            signature="ay",
        )
        # 每次都新建 entry group：avahi 重启后旧的已失效，Reset 会抛异常
        gpath = self.server.EntryGroupNew()
        self.group = dbus.Interface(
            self.bus.get_object(AVAHI_NAME, gpath), IFACE_ENTRY_GROUP)
        self.group.AddService(
            self.ifindex, PROTO, 0, NAME, STYPE, DOMAIN, DOMAIN,
            dbus.UInt16(PORT), txt_array,
        )
        self.group.AddServiceSubtype(
            self.ifindex, PROTO, 0, NAME, STYPE, DOMAIN, SUBTYPE,
        )
        self.group.Commit()

    def run(self):
        self.connect()
        self.publish()
        print("PUBLISHED: %s  iface=%s  proto=%s  refresh=%ss  (no TLS, PDF+URF)"
              % (NAME, IFACE_NAME, PROTO_NAME, REFRESH), flush=True)
        print("  queue=%s  ip=%s  uuid=%s" % (QUEUE, self.ip, self.uuid), flush=True)
        if self.using_fallback:
            print("  WARN: 自动探测失败，用的是回退值。请确认队列 %s 存在、"
                  "ipptool/ip 命令可用，或用 AIRPRINT_UUID / AIRPRINT_IP 手工指定"
                  % QUEUE, flush=True)
        while True:
            time.sleep(REFRESH)
            try:
                self.publish()
                print("[%s] re-announced" % time.strftime("%H:%M:%S"), flush=True)
            except Exception as e:
                print("[%s] republish failed (%s), reconnecting"
                      % (time.strftime("%H:%M:%S"), e), flush=True)
                try:
                    self.connect()
                    self.publish()
                    print("[%s] reconnected and republished" % time.strftime("%H:%M:%S"),
                          flush=True)
                except Exception as e2:
                    print("[%s] still failing: %s" % (time.strftime("%H:%M:%S"), e2),
                          flush=True)


if __name__ == "__main__":
    Publisher().run()
