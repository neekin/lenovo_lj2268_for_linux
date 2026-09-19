#!/usr/bin/env python3
"""AF_PACKET mDNS sniffer — logs all port-5353 traffic on wlan0.
Usage: sudo python3 /tmp/mdns_sniff.py [seconds]
"""
import socket, struct, sys, time

DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 60
IFACE = 'wlan0'

def read_name(data, off):
    labels, jumps = [], 0
    end = None
    while jumps < 10:
        if off >= len(data):
            break
        l = data[off]
        if l == 0:
            off += 1
            break
        if l & 0xC0 == 0xC0:
            if end is None:
                end = off + 2
            off = struct.unpack('>H', data[off:off+2])[0] & 0x3FFF
            jumps += 1
            continue
        off += 1
        labels.append(data[off:off+l].decode('utf-8', 'replace'))
        off += l
    if end is None:
        end = off
    return '.'.join(labels), end

def parse_mdns(payload, src, dst):
    try:
        qid, flags, qd, an, ns, ar = struct.unpack('>HHHHHH', payload[:12])
    except Exception:
        return None
    qr = 'R' if flags & 0x8000 else 'Q'
    parts = []
    off = 12
    try:
        for _ in range(qd):
            nm, off = read_name(payload, off)
            qtype = struct.unpack('>H', payload[off:off+2])[0]
            off += 4
            parts.append(f'Q:{nm}(t{qtype})')
        total_rr = an + ns + ar
        for _ in range(total_rr):
            nm, off = read_name(payload, off)
            rtype, _rc, _ttl, rlen = struct.unpack('>HHIH', payload[off:off+10])
            off += 10 + rlen
            parts.append(f'RR:{nm}(t{rtype})')
    except Exception:
        parts.append('...parse-err')
    mcast = 'MC' if (dst.startswith('224.') or dst.lower().startswith('ff')) else 'UC'
    return f'{qr} {mcast} {src}->{dst} qd={qd} an={an} {" ".join(parts[:4])}'

s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
s.bind((IFACE, 0))
s.settimeout(1.0)
print(f'sniffing {IFACE} for {DURATION}s ...', flush=True)
end_t = time.time() + DURATION
seen = 0
while time.time() < end_t:
    try:
        frame, _ = s.recvfrom(4096)
    except socket.timeout:
        continue
    if len(frame) < 34:
        continue
    etype = struct.unpack('>H', frame[12:14])[0]
    if etype == 0x0800:  # IPv4
        ihl = (frame[14] & 0x0F) * 4
        proto = frame[23]
        if proto != 17:
            continue
        src = '.'.join(str(b) for b in frame[26:30])
        dst = '.'.join(str(b) for b in frame[30:34])
        sport, dport = struct.unpack('>HH', frame[14+ihl:18+ihl])
        if 5353 not in (sport, dport):
            continue
        udplen = struct.unpack('>H', frame[16+ihl:18+ihl])[0]
        payload = frame[14+ihl+8: 14+ihl+udplen]
    elif etype == 0x86DD:  # IPv6
        nh = frame[20]
        if nh != 17:
            continue
        src = socket.inet_ntop(socket.AF_INET6, frame[22:38])
        dst = socket.inet_ntop(socket.AF_INET6, frame[38:54])
        sport, dport = struct.unpack('>HH', frame[54:56])
        if 5353 not in (sport, dport):
            continue
        udplen = struct.unpack('>H', frame[52:54])[0]
        payload = frame[54:54+udplen]
    else:
        continue
    if dst.startswith('224.0.0.') is False and 'fb' not in dst and dport != 5353:
        continue
    line = parse_mdns(payload, src, dst)
    if line:
        seen += 1
        print(f'[{time.strftime("%H:%M:%S")}] {line}', flush=True)
print(f'done, {seen} mdns packets', flush=True)
