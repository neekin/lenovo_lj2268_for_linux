#!/usr/bin/env python3
"""从局域网任一台机器验证 AirPrint 记录是否在播、TXT 内容对不对。

用法:
    python3 check_txt.py                            # 默认查 AirPrint Lenovo LJ2268
    AIRPRINT_NAME='My Printer' python3 check_txt.py # 换服务名
    AIRPRINT_KEYWORD=LJ2268 python3 check_txt.py    # 换匹配关键字
"""
import os
import socket
import struct
import sys
import time

MCAST_GRP = '224.0.0.251'
MCAST_PORT = 5353
NAME = os.environ.get('AIRPRINT_NAME', 'AirPrint Lenovo LJ2268') + '._ipp._tcp.local'
KEYWORD = os.environ.get('AIRPRINT_KEYWORD', 'LJ2268')

def enc_name(name):
    out = b''
    for label in name.split('.'):
        out += bytes([len(label)]) + label.encode()
    return out + b'\x00'

def question(qname, qtype):
    return enc_name(qname) + struct.pack('>HH', qtype, 0x8001)  # QU bit

# Query: PTR for subtype browse + TXT/SRV for instance
pkt = struct.pack('>HHHHHH', 0, 0, 3, 0, 0, 0)
pkt += question('_universal._sub._ipp._tcp.local', 12)   # PTR
pkt += question(NAME, 16)                                 # TXT
pkt += question(NAME, 33)                                 # SRV

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
s.bind(('', 0))
s.settimeout(3.0)
s.sendto(pkt, (MCAST_GRP, MCAST_PORT))

def read_name(data, off):
    labels = []
    end = None
    while True:
        l = data[off]
        if l == 0:
            off += 1
            break
        if l & 0xC0 == 0xC0:
            ptr = struct.unpack('>H', data[off:off+2])[0] & 0x3FFF
            if end is None:
                end = off + 2
            off = ptr
            continue
        off += 1
        labels.append(data[off:off+l].decode('utf-8', 'replace'))
        off += l
    if end is None:
        end = off
    return '.'.join(labels), end

found = {}
deadline = time.time() + 4
while time.time() < deadline:
    try:
        data, addr = s.recvfrom(4096)
    except socket.timeout:
        break
    qid, flags, qd, an, ns, ar = struct.unpack('>HHHHHH', data[:12])
    off = 12
    for _ in range(qd):
        _, off = read_name(data, off)
        off += 4
    for _ in range(an + ar):
        try:
            nm, off = read_name(data, off)
            rtype, rclass, ttl, rlen = struct.unpack('>HHIH', data[off:off+10])
            # careful: rclass is 2 bytes, ttl 4, rdlen 2 => off+10
            rdata_off = off + 10
        except Exception:
            break
        rdata = data[rdata_off:rdata_off+rlen]
        if rtype == 16 and 'LJ2268' in nm:
            txt = []
            i = 0
            while i < len(rdata):
                l = rdata[i]
                txt.append(rdata[i+1:i+1+l].decode('utf-8', 'replace'))
                i += 1 + l
            found.setdefault(nm, {})['TXT'] = txt
            found[nm]['from'] = f'{addr[0]}:{addr[1]}'
        elif rtype == 33 and KEYWORD in nm:
            prio, weight, port = struct.unpack('>HHH', rdata[:6])
            target, _ = read_name(data, rdata_off + 6)
            found.setdefault(nm, {})['SRV'] = f'{target}:{port}'
        elif rtype == 12:
            target, _ = read_name(data, rdata_off)
            if KEYWORD in target:
                found.setdefault(target, {})['PTR_from'] = f'{addr[0]}'
        off = rdata_off + rlen

if not found:
    print('NO ANSWER (no PTR/TXT/SRV received)')
    sys.exit(1)
for nm, info in found.items():
    print('SERVICE:', nm)
    for k in ('PTR_from', 'from', 'SRV', 'TXT'):
        if k in info:
            print(f'  {k}:', info[k])
