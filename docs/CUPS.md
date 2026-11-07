# CUPS 安装驱动、添加队列和打印

## 1. 安装驱动文件

Debian/Ubuntu 原生 CUPS：

```bash
sudo bash install.sh
```

明确选择经过软件一致性验证的 C 版可用 `sudo bash install.sh --driver c`。PPD 和队列名不变；`sudo bash install.sh --driver python` 可回退。范围和限制见 [C_DRIVER.md](C_DRIVER.md)。

自动依赖是 `cups cups-client cups-filters ghostscript python3 python3-pil gcc libc6-dev`。其他发行版需自行安装同等依赖，再用 `sudo bash install.sh --no-deps`。本包支持 CUPS 2.x 的 PPD/filter 架构。

安装位置：

| 文件 | 位置 |
| --- | --- |
| Python filter | `cups-config --serverbin` 下的 `filter/rastertolkpl`，无该工具时探测常见 CUPS 路径 |
| 本机编译的 JBIG 库 | `/usr/local/lib/libjbigwrap.so` |
| 设备描述 | `/usr/share/ppd/lenovo/Lenovo-LJ2268.ppd` |
| USB 规则 | `/usr/share/cups/usb/lenovo-lj2268-unidir` |

安装器会在 `/var/tmp/lj2268-driver-backup.*` 备份覆盖前的同名文件。原生安装的 filter 由 root 拥有、可执行；PPD 和动态库可读。**在网页上传 PPD 不能替代安装 filter 和 `.so`。**

## 2. 添加打印机：命令行

USB 接到运行 CUPS 的机器，打印机开机：

```bash
sudo bash configure-printer.sh
```

脚本调用 `lpinfo -v`，只接受唯一匹配 `usb://Lenovo/LJ2268...` 的设备；没有或找到多台时中止，不会挑选无关打印机，也不会写死旧序列号。

```bash
lpinfo -v
sudo bash configure-printer.sh --uri 'usb://Lenovo/LJ2268?serial=实际序列号'
# 如需更新已有队列：
sudo bash configure-printer.sh --update --share --set-default
```

默认队列名 `Lenovo_LJ2268`；默认 A4、灰度。`--share` 开启该队列和局域网 CUPS 共享；`--set-default` 才会更换服务器默认打印机。已有队列需 `--update`，不会删除旧队列。

容器里对应为：

```bash
bash configure-printer.sh --container lj2268-cups --share --set-default
docker exec lj2268-cups lpinfo -v
docker exec lj2268-cups lpstat -t
```

## 3. 添加打印机：网页

1. 打开 `https://设备IP:631/admin/`，登录自己的 CUPS 管理员。
2. 进入 Administration → Add Printer，选择探测到的 Lenovo LJ2268 USB。
3. 填写名称，例如 `Lenovo_LJ2268`，需要共享时勾选 Share This Printer。
4. 型号选本包的 Lenovo LJ2268；若没有列出，选择提供 PPD，上传 `ppd/Lenovo-LJ2268.ppd`。
5. 设 A4、灰度、600dpi。不要选择通用 PCL/PostScript 或 IPP Everywhere：这台 USB 主机型打印机需要本包的格式转换。

若提示“需要升级/必须使用 https”，直接用 `https://设备IP:631/admin/`。容器内 `172.x.x.x` 地址不是给局域网客户端访问的地址。自签名证书需要在自己的设备上确认。

## 4. 验证

先确认队列状态，再由使用者明确提交测试页：

```bash
lpstat -t
lp -d Lenovo_LJ2268 tests/fixtures/hello.pdf
lpstat -W completed
journalctl -u cups -n 80 --no-pager
```

Docker：

```bash
docker exec lj2268-cups lpstat -t
docker logs --tail 100 lj2268-cups
docker exec lj2268-cups tail -n 100 /var/log/cups/error_log
```

日志中的 `completed` 只说明过滤器和后端完成处理，最终仍需确认纸面正常。当前实机已经验证过中英文文字、图形和 iPhone 打印。

## 5. 常见故障

- `Filter failed`：检查 Python、Pillow、`.so` 的 CPU 架构和依赖，以及 filter 权限；执行 `tests/selftest.py`。
- `No such file`：PPD 引用的是 `rastertolkpl`；仅复制 PPD、旧名 `rastertolhpl` 或挂错目录都会失败。
- 作业完成却无纸：需要核对 USB 与协议输出，不能只看发送成功；见 [协议说明](PROTOCOL.md)。
- 容器找不到 USB：检查 `/dev/bus/usb` 挂载及 `c 189:* rwm` 规则。
- 打印机改接路由器：先确认路由器提供 RAW/9100 等打印服务器；再把队列 URI 改为其地址，驱动仍在 CUPS 上运行。

命令语义参见 [OpenPrinting 官方管理文档](https://openprinting.github.io/cups/doc/admin.html)。
