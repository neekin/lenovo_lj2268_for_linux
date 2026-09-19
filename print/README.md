# AirPrint 桥接方案 — GDI 打印机 (Lenovo LJ2268) 供 iPhone 打印

在 Linux 服务器（hi3798mv100, Ubuntu, 192.168.1.31）上把一台 **GDI 主机型打印机**
（Lenovo LJ2268，LHPL 开源驱动 `rastertolhpl`）包装成 **AirPrint 打印机**，
让 iPhone 能原生发现并打印。2026-09-19 实测：iPhone 发现 → 提交 → 出纸 全链路打通。

## 架构

```
iPhone ──mDNS 发现──> avahi (记录由 airprint_pub.py 经 D-Bus 注册)
   │                        │
   │                        └──(组播应答，部分路由器跨频段/跨AP会丢)──┐
   │                                                             │
   ├──单播兜底──> airprint_push.py (监听 5353，对查询做单播应答，   |
   │             并周期向学习到的/种子目标单播推送公告)  <─────────┘
   │
   └──IPP 631──> CUPS 队列 Lenovo-LJ2268 ──> rastertolhpl ──> USB 打印机
```

| 文件 | 作用 |
|---|---|
| `scripts/airprint_pub.py` | 经 avahi D-Bus 注册精简 mDNS 记录（60s 刷新），是发现记录的"正式来源" |
| `scripts/airprint_push.py` | 单播兜底：应答任何 5353 查询（回源单播），每 15s 向种子+学习目标推送完整公告 |
| `systemd/airprint.service` | pub 的用户级 systemd 服务 |
| `systemd/airprint-push.service` | push 的用户级 systemd 服务 |
| `scripts/check_txt.py` | 验证工具：从局域网任一台机器查 TXT，确认记录内容 |
| `scripts/mdns_sniff.py` | 诊断工具：服务器上 `sudo python3 mdns_sniff.py 60` 抓全部 mDNS 流量 |

## 踩过的坑（根因清单，换设备时全部适用）

1. **CUPS 默认共享记录太长**：cupsd 自动注册的 TXT 很大，超过 mDNS legacy
   unicast 512 字节限制会被 avahi 丢弃（日志见 "not fitting in legacy unicast
   packet"）。→ 用 `airprint_pub.py` 手工注册精简记录，并停用 cups-browsed。
   手写的 `/etc/avahi/services/*.service` 静态文件也不好维护（曾因缺 URF 出错被删）。

2. **iOS 列表要求 URF**：TXT 必须含 `pdl=application/pdf,image/urf` 和 `URF=...`
   键，否则 iPhone 打印选择器**根本不显示**打印机；macOS 没有这个过滤
   （"Mac 能看到但 iPhone 看不到" = 缺 URF）。实测 iOS 会发 PDF（不是 URF），
   本机没有 urftopdf 也无所谓，CUPS 的 `rastertolhpl` 直接处理 PDF。

3. **UUID 必须与 CUPS 队列的 printer-uuid 一致**：队列一旦删除重建
   （`lpadmin -x` 后重建），`printer-uuid` 会重新生成。TXT 里的 `UUID=` 与 IPP
   应答不一致时，iPhone 选中打印机立刻报"缺少打印机的软件"。

   **已自动化**：两个脚本每次发公告都会重新向本机 CUPS 查询 `printer-uuid`
   （`ipptool -tv ... get-printer-attributes.test`），队列重建后最多 60 秒自动跟上，
   不需要手工同步。同理本机 IPv4 也会重新探测（DHCP 换地址自动跟上）。
   手工干预只在探测失败时才有必要：设 `AIRPRINT_UUID` / `AIRPRINT_IP` 环境变量，
   或改脚本顶部的 `FALLBACK_UUID` / `FALLBACK_IP`。启动时若用了回退值会打 WARN。

4. **路由器组播不可靠**：双频路由（2.4G/5G）跨频段、跨 AP 的组播转发经常丢包。
   手机"能发出查询但收不到组播应答"。→ `airprint_push.py` 对所有查询做
   **单播应答**（回源地址），并周期向 `SEED_TARGETS`（手机 IP）单播推送公告。

5. **PPD 过滤器绝对路径误报**：`*cupsFilter` 里写绝对路径
   `/usr/lib/cups/filter/rastertolhpl` 会让 CUPS 2.3 误报
   `cups-missing-filter-warning`（printer-state-reasons 非 none，可能诱发 iOS
   的"缺少软件"判定）。→ 改成相对名 `rastertolhpl`：
   ```bash
   sudo sed -i 's|/usr/lib/cups/filter/rastertolhpl|rastertolhpl|' /etc/cups/ppd/<队列名>.ppd
   sudo systemctl restart cups
   # 验证：ipptool -tv ipp://localhost/printers/<队列名> \
   #   /usr/share/cups/ipptool/get-printer-attributes.test | grep printer-state-reasons
   # 应输出 none
   ```

6. **iOS 会缓存打印机的"坏判定"**：改完服务器后 iPhone 仍报旧错，需
   重启手机（或开关 Wi-Fi）清除 mDNS 缓存和打印机验证缓存。

7. GDI 渲染慢：600dpi 软件光栅化一页约 15-20 秒，属正常，耐心等或考虑 300dpi。

## 换新设备的部署步骤

### 1. 装基础组件和驱动

```bash
sudo apt install cups avahi-daemon python3-dbus
# GDI 驱动 rastertolhpl 按打印机型号自行安装到 /usr/lib/cups/filter/
```

### 2. 建 CUPS 队列

```bash
# 确认 USB 设备名
lpinfo -v | grep usb
# 建队列（PPD 用对应驱动生成）
sudo lpadmin -p Lenovo-LJ2268 -E -v "usb://Lenovo/LJ2268?serial=XXX" -P /path/to/lj2268.ppd
sudo cupsenable Lenovo-LJ2268 && sudo cupsaccept Lenovo-LJ2268
```

`/etc/cups/cupsd.conf` 要点：`Port 631`、`<Location />` 允许局域网
（`Allow all` 或 `Allow 192.168.1.0/24`）、打印操作不强制认证。
停用 cups-browsed（避免 CUPS 自己再注册一份超长记录）：

```bash
sudo systemctl disable --now cups-browsed
```

### 3. 确认 printer-uuid（脚本会自动探测，这一步只是核对）

```bash
ipptool -tv ipp://localhost:631/printers/Lenovo-LJ2268 \
  /usr/share/cups/ipptool/get-printer-attributes.test | grep printer-uuid
# 输出形如 urn:uuid:0aae3f45-e6f5-3e9b-5afe-5f389701a6c0
```

脚本每次发公告都会自动查询该值，**正常情况下不用手工填**。
只在自动探测失败（启动日志出现 `WARN: 自动探测失败`）时才用
`AIRPRINT_UUID=...` 环境变量指定。注意 `ipptool` 必须带 `-tv`，
不带的话它静默无输出，很容易误判成"命令坏了"。

### 4. 设备相关参数（用环境变量，不要改脚本）

| 变量 | 默认 | 说明 |
|---|---|---|
| `AIRPRINT_QUEUE` | `Lenovo-LJ2268` | CUPS 队列名，决定 `rp=` 和查哪个队列的 UUID |
| `AIRPRINT_NAME` | `AirPrint Lenovo LJ2268` | 服务显示名 |
| `AIRPRINT_IFACE` | `wlan0` | 网卡名（有线改 `eth0`） |
| `AIRPRINT_SEEDS` | 空 | 单播兜底的种子目标（手机 IP，逗号分隔，可多个） |
| `AIRPRINT_IP` / `AIRPRINT_UUID` | 自动探测 | 探测失败时的手工兜底 |

用 `install.sh --airprint` 部署时，这些会被写进 systemd 的 drop-in
（`~/.config/systemd/user/<service>.d/env.conf`），**不用改仓库里的脚本**。
手动部署的话自己建同样的 drop-in，或者在 shell 里 export 后直接跑脚本。

### 5. 部署脚本和 systemd 服务

```bash
cp scripts/airprint_pub.py scripts/airprint_push.py scripts/check_txt.py ~/
mkdir -p ~/.config/systemd/user
cp systemd/airprint.service systemd/airprint-push.service ~/.config/systemd/user/

# 队列名/网卡/种子目标用 drop-in 注入，不改动仓库里的脚本
mkdir -p ~/.config/systemd/user/airprint.service.d \
         ~/.config/systemd/user/airprint-push.service.d
cat > ~/.config/systemd/user/airprint.service.d/env.conf <<EOF
[Service]
Environment=AIRPRINT_QUEUE=Lenovo-LJ2268
Environment=AIRPRINT_IFACE=wlan0
Environment=AIRPRINT_SEEDS=192.168.1.30
EOF
cp ~/.config/systemd/user/airprint.service.d/env.conf \
   ~/.config/systemd/user/airprint-push.service.d/env.conf

systemctl --user daemon-reload
systemctl --user enable --now airprint.service airprint-push.service
# 开机自启（不登录也运行）：
sudo loginctl enable-linger $USER
```

注意：两个脚本都监听 UDP 5353 与 avahi 共存（SO_REUSEPORT），互不冲突。
systemd 单元里的 `ExecStart` 用 `%h` 展开家目录，换用户名不用改。

### 6. 验证

从局域网**另一台机器**（Mac/另一台 Linux）：

```bash
python3 scripts/check_txt.py
# 期望：能解析出 PTR/SRV/TXT，且 TXT 含：
#   pdl=application/pdf,image/urf
#   URF=CP1,PQ3-4-5
#   UUID=<与 ipptool 查到的一致>
#   rp=printers/<队列名>
```

iPhone：打开 打印 → 选择打印机 → 应能看到该打印机 → 打印测试页。
若不显示：开关 Wi-Fi 或重启手机再试；仍不行用下面的排查工具。

## 排查工具箱

```bash
# mDNS 全量抓包（服务器上，60 秒内复现手机操作）
sudo python3 scripts/mdns_sniff.py 60
# 看手机查询是否到达、应答是组播还是单播(MC/UC)

# CUPS 访问/错误日志（看 iPhone 的 IPP 流程走到哪一步）
tail -20 /var/log/cups/access_log     # Validate-Job→Create-Job→Send-Document→Cancel-Job?
grep 'Job NNN' /var/log/cups/error_log # 任务时间线、过滤器是否执行

# IPP 属性检查
ipptool -tv ipp://localhost/printers/<队列名> \
  /usr/share/cups/ipptool/get-printer-attributes.test

# 队列状态
lpstat -p -l && lpstat -W completed -o
```

典型症状对照：
| 症状 | 原因 |
|---|---|
| iPhone 列表里没有 | TXT 缺 `image/urf`/`URF` 键（坑 2） |
| 选中即报"缺少打印机的软件" | TXT UUID 与队列 printer-uuid 不一致（坑 3），或 printer-state-reasons 非 none（坑 5） |
| Mac 能看到、iPhone 看不到 | 同上，macOS 过滤更宽松 |
| 时好时坏、换网络后失效 | 路由器组播问题（坑 4），靠 push.py 单播兜底，根治需调路由器 IGMP/双频设置 |
| 提交后 10-20 秒被取消 | iOS 等不及（渲染慢），实际可能在打，等一页打完再操作 |

## 停用 / 卸载

```bash
systemctl --user disable --now airprint.service airprint-push.service
rm -rf ~/.config/systemd/user/airprint.service \
       ~/.config/systemd/user/airprint-push.service \
       ~/.config/systemd/user/airprint.service.d \
       ~/.config/systemd/user/airprint-push.service.d \
       ~/airprint_pub.py ~/airprint_push.py
systemctl --user daemon-reload
```

只是想临时停一下就 `systemctl --user stop ...`，`Restart=always` 不会在手动 stop 后拉起。

## 当前设备快照（2026-09-20 更新）

- 服务器：ubuntu@hi3798mv100 (192.168.1.31, wlan0, 2.4G SSID 86170919)
- 队列：Lenovo-LJ2268，device `usb://Lenovo/LJ2268?serial=VP00338633VP20070701`
- printer-uuid：`0aae3f45-e6f5-3e9b-5afe-5f389701a6c0`
- mDNS 服务：`AirPrint Lenovo LJ2268._ipp._tcp.local`，子类型
  `_universal._sub._ipp._tcp`，SRV → hi3798mv100.local:631
- push 种子目标：192.168.1.30, 192.168.1.35（iPhone）
- 服务日志：`journalctl --user -u airprint.service`、`-u airprint-push.service`
- `printer-state-reasons` 已为 `none`（坑 5 已修：PPD 的 `*cupsFilter` 改成了
  相对名 `rastertolhpl`，交付包里的 PPD 也已同步修正）
- 交付包根目录的 `install.sh --airprint` 会自动完成本文第 2、5 步
