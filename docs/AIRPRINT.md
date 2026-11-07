# iPhone / AirPrint 的配置与验收

驱动转换、IPP 打印与 mDNS 发现是三个环节。能打开 CUPS 网页不代表 iPhone 一定能发现打印机；能发现也不代表 USB 打印已经通过。

## 1. 基本条件

- iPhone 与服务器所在网络允许互通、UDP 5353 mDNS 组播未被 AP 隔离或访客 VLAN 阻断。
- 手机能访问 `http://服务器IP:631/`，服务器 TCP 631 可达。
- 队列已共享，支持 PDF/图像经 CUPS 转换到本驱动。
- 广播出的主机名可以解析为手机能到达的服务器 LAN 地址。

本项目没有为每一台手机写死 IP，也不依赖单播推送脚本。操作系统通常通过 mDNS 发现 AirPrint 服务。

## 2. 原生系统的 CUPS

```bash
sudo apt-get install -y avahi-daemon avahi-utils
sudo systemctl enable --now avahi-daemon
sudo bash configure-printer.sh --update --share
sudo cupsctl Browsing=Yes BrowseLocalProtocols=dnssd \
  BrowseDNSSDSubTypes=_cups,_print,_universal
```

## 3. Docker 使用宿主机 Avahi/D-Bus

宿主机启用 `avahi-daemon` 后，增加 D-Bus socket 挂载。本仓库已提供可选 Compose override：

```bash
sudo apt-get install -y avahi-daemon avahi-utils
sudo systemctl enable --now avahi-daemon
docker compose -f compose.yaml -f compose.airprint.yaml up -d --build
bash configure-printer.sh --container lj2268-cups --update --share
docker exec lj2268-cups cupsctl Browsing=Yes BrowseLocalProtocols=dnssd \
  BrowseDNSSDSubTypes=_cups,_print,_universal
```

挂载为 `/run/dbus/system_bus_socket:/run/dbus/system_bus_socket:ro`，来自宿主机；不是在容器内创建一个空 socket。host 网络、D-Bus 挂载及 CUPS 的 DNS-SD 选项共同构成已验证方案。

## 4. 固定可访问的 mDNS 主机名

容器随机主机名或多个 LAN IPv4 地址可能导致广播中使用错误目标。选择当前局域网内唯一的名称，例如 `my-lj2268.local`，让它指向实际服务器 LAN IPv4；不要复制旧设备地址。

```bash
docker exec lj2268-cups cupsctl DNSSDHostName=my-lj2268.local
```

在宿主机创建 `/etc/systemd/system/cups-airprint-hostname.service`，将 `192.168.1.50` 改成自己的固定 LAN IP：

```ini
[Unit]
Description=Publish reachable IPv4 hostname for CUPS AirPrint
Requires=avahi-daemon.service
PartOf=avahi-daemon.service
After=avahi-daemon.service

[Service]
Type=simple
ExecStart=/usr/bin/avahi-publish-address -f -R my-lj2268.local 192.168.1.50
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cups-airprint-hostname.service
avahi-resolve-host-name -4 my-lj2268.local
avahi-browse -rt _ipp._tcp
```

`-R` 仅禁止反向地址记录；仍发布正向主机名。实机上用 `/etc/avahi/hosts` 给同一地址增加名字曾遇到反向 PTR 冲突，改为以上正向发布后正常。

确认 CUPS 接受该主机名。若 `ServerAlias` 限制了名称，应按现有配置追加此名称；不要为了方便无条件把所有服务器都设为 `ServerAlias *`。

## 5. 这次实机遇到的关键问题

1. **多地址的广播源错误**：AC 所需 `6.7.8.9/32` 曾与 LAN IP 同在物理网口，抓包见到不合适的 mDNS 源地址。实机将此 AC 地址保留在 loopback `lo`，LAN IP 留在网口后改善。此项是该多地址环境的专用修复，不是所有机器都必须配置的地址。
2. **DNS-SD 名称不可达**：使用可解析为正确 LAN IPv4 的 `.local` 名称，而非容器内部地址。
3. **手机缓存旧队列 URI**：手机曾使用 `/printers/Lenovo-LJ2268`，实际队列是 `Lenovo_LJ2268`。两者是不同 URI；最终保留了指向同一 USB 打印机的兼容队列，手机才成功打印。
4. **界面可访问但仍搜不到**：逐项验证 IPP、TXT、主机名和 mDNS。不能把能打开 631 当作发现功能已经正常。

新设备建议从一开始固定一个队列名。只在确有旧客户端兼容需求时增加别名队列，避免同一打印机无故出现多个入口。

## 6. iPhone 验收

退出“选择打印机”后重新进入，必要时关闭 Wi-Fi 数秒再连接。选中打印机后，明确提交一页，观察 CUPS 日志、过滤器是否成功及实际纸面。最后再检查重启后的发现能力。

诊断示例：

```bash
ip -4 addr
ip route get 手机IP
avahi-resolve-host-name -4 my-lj2268.local
avahi-browse -rt _ipp._tcp
docker exec lj2268-cups lpstat -t
docker exec lj2268-cups tail -n 100 /var/log/cups/error_log
```

如需临时打开调试日志：`docker exec lj2268-cups cupsctl LogLevel=debug`；排查后恢复 `LogLevel=info`。HTTPS 管理和 IPP 发现、打印分别检查，不必为了手机发现而关闭加密。
