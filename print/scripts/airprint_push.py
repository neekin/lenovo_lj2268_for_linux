#!/usr/bin/env python3
"""
AirPrint 自动追踪单播推送器 + 查询应答器。

背景：
  路由器对手机方向的组播做了过滤（IGMP Snooping），盒子发出的 mDNS 组播
  应答/公告永远到不了 iPhone，但 iPhone 的查询能到盒子（组播只出不进）。
  avahi 只会用组播回应，所以 iPhone 永远收不到。

本脚本做两件事（均为单播，绕开组播过滤）：
  1. 监听 5353 上的 mDNS 查询：一旦发现有人在查 _ipp/_universal/hi3798mv100，
     把该来源记为"推送目标"，并向其【查询源地址:端口】单播回一份
     与查询匹配的完整应答（PTR/SRV/TXT/A，回显问题段）。
  2. 每 PUSH_INTERVAL 秒向所有最近活跃的目标的 5353 端口单播推送
     完整公告（RFC 6762 被动缓存）。

记录全部不压缩：无偏移依赖，可自由拼进任何报文（约 670 字节，UDP 无压力）。
无需 root：5353 用 SO_REUSEADDR/SO_REUSEPORT 与 avahi 共存。
"""

import os
import re
import socket
import struct
import subprocess
import time
import select

IFACE = os.environ.get('AIRPRINT_IFACE', 'wlan0')
QUEUE = os.environ.get('AIRPRINT_QUEUE', 'Lenovo-LJ2268')
SVC_LABEL = os.environ.get('AIRPRINT_NAME', 'AirPrint Lenovo LJ2268')
STYPE = '_ipp._tcp.local'
SUBTYPE = '_universal._sub._ipp._tcp.local'
SVC_NAME = SVC_LABEL + '.' + STYPE
PORT = 631
TTL = 4500
PUSH_INTERVAL = 15
REBUILD_INTERVAL = 60  # IP / UUID / IPv6 前缀都可能变，定期重建记录
TARGET_ACTIVE_WINDOW = 1800  # 目标多久没发查询就停止推送
# 静态种子目标：无论是否发过查询都推送（手机 IP，逗号分隔；不给则为空）
SEED_TARGETS = [t.strip() for t in
                os.environ.get('AIRPRINT_SEEDS', '192.168.1.30,192.168.1.35').split(',')
                if t.strip()]

# 探测失败时的回退值
FALLBACK_UUID = '0aae3f45-e6f5-3e9b-5afe-5f389701a6c0'
FALLBACK_IP = '192.168.1.31'

try:
    IFINDEX = socket.if_nametoindex(IFACE)
except OSError:
    sys.exit('网卡 %s 不存在。用 AIRPRINT_IFACE=eth0 指定，或 ip link 看实际网卡名')


def detect_uuid():
    """向本机 CUPS 查询队列的 printer-uuid；失败返回 None。"""
    try:
        out = subprocess.check_output(
            ['ipptool', '-tv', 'ipp://localhost:631/printers/' + QUEUE,
             'get-printer-attributes.test'],
            stderr=subprocess.DEVNULL, timeout=15).decode('utf-8', 'replace')
        m = re.search(r'printer-uuid\s*\(uri\)\s*=\s*urn:uuid:(\S+)', out)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def detect_ip():
    try:
        out = subprocess.check_output(
            ['ip', '-4', '-o', 'addr', 'show', IFACE],
            stderr=subprocess.DEVNULL, timeout=5).decode()
        m = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)/', out)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def get_gua():
    try:
        out = subprocess.check_output(
            ['ip', '-6', 'addr', 'show', IFACE], timeout=3).decode()
        for ln in out.splitlines():
            ln = ln.strip()
            if ln.startswith('inet6 '):
                addr = ln.split()[1].split('/')[0]
                if not addr.startswith('fe80') and not addr.startswith('fd') \
                        and ':' in addr:
                    return addr
    except Exception:
        pass
    return None


_uuid = os.environ.get('AIRPRINT_UUID') or detect_uuid()
_ip = os.environ.get('AIRPRINT_IP') or detect_ip()
UUID = _uuid or FALLBACK_UUID
IP = _ip or FALLBACK_IP
# 用"探测是否成功"判断是否回退, 不能拿值去比: 探测值可能恰好等于回退值
USING_FALLBACK = (_uuid is None) or (_ip is None)
HOST = os.environ.get('AIRPRINT_HOST') or socket.gethostname() + '.local'
GUA = get_gua()


def enc_name(n):
    out = b''
    for label in n.split('.'):
        raw = label.encode()
        out += bytes([len(raw)]) + raw
    return out + b'\x00'


def rr(name, rtype, rdata):
    return enc_name(name) + struct.pack('!HHIH', rtype, 1, TTL, len(rdata)) + rdata


def txt_bytes():
    items = [
        b'txtvers=1',
        b'qtotal=1',
        b'rp=printers/' + QUEUE.encode(),
        b'ty=Lenovo LJ2268 (LHPL)',
        b'product=(Lenovo LJ2268)',
        b'printer-state=3',
        b'printer-type=0x900E',
        b'UUID=' + UUID.encode(),
        b'pdl=application/pdf,image/urf',
        b'URF=CP1,PQ3-4-5',
        b'Color=F',
        b'Duplex=F',
        b'priority=0',
        b'note=Home',
        b'adminurl=http://' + IP.encode() + b':631/printers/' + QUEUE.encode(),
    ]
    return b''.join(bytes([len(t)]) + t for t in items)


RECORDS = {}
ANNOUNCE = b''


def rebuild_records():
    """重建全部记录。IP / UUID / IPv6 前缀变化后调用一次即可生效。"""
    global RECORDS, ANNOUNCE, IP, UUID, GUA, HOST

    if not os.environ.get('AIRPRINT_IP'):
        i = detect_ip()
        if i:
            IP = i
    if not os.environ.get('AIRPRINT_UUID'):
        u = detect_uuid()
        if u:
            UUID = u
    GUA = get_gua()

    txt = txt_bytes()
    rec = {
        (STYPE, 12): rr(STYPE, 12, enc_name(SVC_NAME)),
        (SUBTYPE, 12): rr(SUBTYPE, 12, enc_name(SVC_NAME)),
        (SVC_NAME, 33): rr(SVC_NAME, 33,
                           struct.pack('!HHH', 0, 0, PORT) + enc_name(HOST)),
        (SVC_NAME, 16): rr(SVC_NAME, 16, txt),
        (HOST, 1): rr(HOST, 1, socket.inet_aton(IP)),
    }
    rec[(SVC_NAME, 255)] = rec[(SVC_NAME, 33)] + rec[(SVC_NAME, 16)]
    if GUA:
        rec[(HOST, 28)] = rr(HOST, 28, socket.inet_pton(socket.AF_INET6, GUA))
        rec[(HOST, 255)] = rec[(HOST, 1)] + rec[(HOST, 28)]
    RECORDS = rec

    # 公告里同时带 A 和 AAAA，纯 IPv6 客户端才能拿到地址
    ans = [rec[(STYPE, 12)], rec[(SUBTYPE, 12)],
           rec[(SVC_NAME, 33)], rec[(SVC_NAME, 16)], rec[(HOST, 1)]]
    if GUA:
        ans.append(rec[(HOST, 28)])
    ANNOUNCE = struct.pack('!HHHHHH', 0, 0x8400, 0, len(ans), 0, 0) + b''.join(ans)
    return ANNOUNCE


def parse_name(data, off):
    labels = []
    while True:
        if off >= len(data):
            raise IndexError
        l = data[off]
        if l == 0:
            off += 1
            break
        if l & 0xC0 == 0xC0:
            ptr = struct.unpack('!H', data[off:off + 2])[0] & 0x3FFF
            n, _ = parse_name(data, ptr)
            labels.append(n)
            off += 2
            break
        labels.append(data[off + 1:off + 1 + l].decode('utf-8', 'replace'))
        off += 1 + l
    return '.'.join(labels), off


def parse_query(data):
    """返回 (tid, questions原始字节, [(name, qtype)]) 或 None（非查询）"""
    if len(data) < 12:
        return None
    tid, flags, qd, _an, _ns, _ar = struct.unpack('!HHHHHH', data[:12])
    if flags & 0x8000 or qd == 0:
        return None
    off = 12
    qs = []
    for _ in range(qd):
        n, off = parse_name(data, off)
        qtype, _qclass = struct.unpack('!HH', data[off:off + 4])
        qs.append((n, qtype))
        off += 4
    return tid, data[12:off], qs


def build_response(tid, qsection, qs):
    answers = b''
    count = 0
    for name, qtype in qs:
        key = (name.lower(), qtype)
        if key in RECORDS:
            answers += RECORDS[key]
            count += 1
    if count == 0:
        return None
    return struct.pack('!HHHHHH', tid, 0x8400, len(qs), count, 0, 0) + \
        qsection + answers


INTEREST = ('ipp', 'universal', 'hi3798mv100', 'airprint')


def is_interesting(qs):
    for name, _ in qs:
        low = name.lower()
        if any(k in low for k in INTEREST):
            return True
    return False


def log(msg):
    print('[%s] %s' % (time.strftime('%H:%M:%S'), msg), flush=True)


def main():
    s4 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except OSError:
        pass
    s4.bind(('0.0.0.0', 5353))
    s4.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                  struct.pack('4s4s', socket.inet_aton('224.0.0.251'),
                              socket.inet_aton('0.0.0.0')))

    s6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    s6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except OSError:
        pass
    s6.bind(('::', 5353))
    s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_JOIN_GROUP,
                  socket.inet_pton(socket.AF_INET6, 'ff02::fb') +
                  struct.pack('@I', IFINDEX))

    rebuild_records()
    log('airprint_push 启动: iface=%s(%d) IP=%s GUA=%s UUID=%s 公告=%d字节'
        % (IFACE, IFINDEX, IP, GUA, UUID, len(ANNOUNCE)))
    if USING_FALLBACK:
        log('WARN: 自动探测失败，用的是回退值。请确认队列 %s 存在、ipptool/ip '
            '命令可用，或用 AIRPRINT_UUID / AIRPRINT_IP 手工指定' % QUEUE)

    targets = {}  # (family, addr) -> last_seen
    last_push = 0.0
    last_rebuild = time.time()

    while True:
        r, _, _ = select.select([s4, s6], [], [], 1)
        now = time.time()
        if now - last_rebuild >= REBUILD_INTERVAL:
            last_rebuild = now
            rebuild_records()
        for s in r:
            try:
                data, addr = s.recvfrom(9000)
            except OSError:
                continue
            src_ip = addr[0]
            if src_ip in (IP, GUA):
                continue
            parsed = parse_query(data)
            if not parsed:
                continue
            tid, qsection, qs = parsed
            if not is_interesting(qs):
                continue
            key = (s.family, src_ip)
            if key not in targets:
                log('新目标: %s (查询 %s)' % (src_ip, qs[0][0]))
            targets[key] = now

            resp = build_response(tid, qsection, qs)
            if resp:
                try:
                    if s.family == socket.AF_INET:
                        s.sendto(resp, (src_ip, addr[1]))
                    else:
                        scope = IFINDEX if src_ip.startswith('fe80') else 0
                        s.sendto(resp, (src_ip, addr[1], 0, scope))
                    log('已应答 %s:%d (%d字节) 问: %s'
                        % (src_ip, addr[1], len(resp), qs[0][0]))
                except OSError as e:
                    log('应答失败 %s: %s' % (src_ip, e))

        if now - last_push >= PUSH_INTERVAL:
            last_push = now
            expired = [k for k, seen in targets.items()
                       if now - seen > TARGET_ACTIVE_WINDOW]
            for k in expired:
                del targets[k]
            push_set = dict(targets)
            for tip in SEED_TARGETS:
                push_set[(socket.AF_INET, tip)] = now
            for (fam, tip) in push_set:
                try:
                    if fam == socket.AF_INET:
                        s4.sendto(ANNOUNCE, (tip, 5353))
                    else:
                        scope = IFINDEX if tip.startswith('fe80') else 0
                        s6.sendto(ANNOUNCE, (tip, 5353, 0, scope))
                except OSError as e:
                    log('推送失败 %s: %s' % (tip, e))
            if push_set:
                log('已向 %d 个目标周期推送' % len(push_set))


if __name__ == '__main__':
    main()
