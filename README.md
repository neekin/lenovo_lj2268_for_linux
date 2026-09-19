# Lenovo LJ2268 / LJ2268W —— Linux 打印驱动（LHPL 开源实现）

联想 LJ2268 是 **GDI 主机型打印机**（IEEE 1284 Device ID 里写着 `CMD:GDI`），
不认 PCL、不认 PostScript，渲染完全依赖厂商私有驱动。官方只出 Windows / macOS 驱动，
**从未提供 Linux 版本**。

本驱动通过逆向官方 macOS 驱动（`LNTHR6Z` 二进制）得到私有 **LHPL** 协议，
用 C + 标准 JBIG1 重写实现，已在 **armhf（海思 hi3798mv100）+ CUPS 2.3.1** 上实测出纸，
并接入 AirPrint 供 iPhone 直接打印。

---

## 目录结构

```
LJ2268_linux/
├── README.md              本文档
├── PROTOCOL.md            LHPL 协议逆向规格（逐字段）
├── Makefile               编译 / 安装 / 测试
├── install.sh             一键安装（默认只装驱动；AirPrint 需 --airprint）
├── src/
│   ├── rastertolhpl.c     驱动源码（单一文件）
│   ├── jbig.h             jbigkit 头文件（随包提供，免去装 dev 包）
│   └── jbig_ar.h
├── ppd/
│   ├── LJ2268-lhpl.ppd              成品 PPD（cupsFilter 指向本驱动，默认 A4/600dpi）
│   └── Lenovo-LJ2268.ppd.macos-orig 官方 macOS PPD 原始版（对照参考）
├── print/                     可选：把队列包装成 iPhone 可用的 AirPrint 打印机
│   ├── README.md              部署步骤 + 7 条根因清单 + 排查工具箱
│   ├── scripts/
│   │   ├── airprint_pub.py    经 avahi D-Bus 注册精简 mDNS 记录（双栈 + 自动重连）
│   │   ├── airprint_push.py   单播兜底：应答 5353 查询 + 周期推送公告
│   │   ├── check_txt.py       验证工具：查 TXT 内容对不对
│   │   └── mdns_sniff.py      诊断工具：抓全部 mDNS 流量（需 sudo）
│   └── systemd/               两个用户级 systemd 单元
├── test/
│   ├── hello.pdf           最小文本页
│   ├── calibration-box.pdf 可打印区方框页（校验四边留白是否对称）
│   └── ruler-mm.pdf        毫米刻度页（需要时量偏移）
└── prebuilt/
    └── rastertolhpl-armhf  已编译好的 armhf 二进制
```

---

## 一、最快路径

```bash
sudo apt install -y gcc libc6-dev libjbig0 poppler-utils cups
cd LJ2268_linux
make && sudo make install        # 只装驱动
lp -d Lenovo-LJ2268 test/hello.pdf     # 应出纸
```

装完后若要 iPhone 打印，另跑一次：`sudo ./install.sh --airprint`。

`make` 会**自动探测** libjbig 的链接方式（有 dev 包就用 `-ljbig`，只有运行时库就直连
`libjbig.so.0`），`sudo make install` 会**自动探测** USB 打印机 URI 并完成安装。
两者都在失败时给出明确提示，不需要手工传参。

已在 **armhf（海思 hi3798mv100）+ Ubuntu + CUPS 2.3.1** 上跑通：
新编译产物、prebuilt 二进制、实际安装的 filter 三者 md5 完全一致（`eedf7afab455cc8ebd4dc7ee317f70a8`）。

### 需要手工指定时的参数

```bash
sudo make install DEVICE_URI="usb://Lenovo/LJ2268?serial=XXXX"
sudo make install QUEUE=LJ2268          # 改队列名（默认 Lenovo-LJ2268）
lpinfo -v | grep usb                    # 查可用设备 URI
```

---

## 二、编译

### 依赖

| 类型 | 包 | 用途 |
|---|---|---|
| 编译 | `gcc`、`libc6-dev` | 编译驱动 |
| 编译 | libjbig 头文件 | **已随包放在 `src/`**，无需 `libjbig-dev` |
| 运行 | `libjbig0`（`libjbig.so.0`） | JBIG1 压缩 |
| 运行 | `poppler-utils`（`pdftoppm`） | PDF → 1bit 位图 |
| 运行 | `cups` | 打印系统 |

```bash
sudo apt install -y gcc libc6-dev libjbig0 poppler-utils cups
```

### 手工编译命令

等价的裸 gcc 命令，供你在别的平台上参考：

```bash
# A. 系统有 libjbig-dev
gcc -O2 -o rastertolhpl src/rastertolhpl.c -ljbig -lm

# B. 只有运行时库（Debian/Ubuntu 常见，也是本项目的实际情况）
gcc -O2 -o rastertolhpl src/rastertolhpl.c \
    /usr/lib/arm-linux-gnueabihf/libjbig.so.0 -lm
```

> **注意 A 会失败的情形**：系统只有 `libjbig.so.0` 而没有 `libjbig.so`（未装 dev 包）时，
> `-ljbig` 报 `cannot find -ljbig`。这正是 `make` 自动探测要解决的问题。
> 非 armhf 平台把 `.so` 路径换成 `ls /usr/lib/*/libjbig.so.0` 的实际结果。

头文件无需安装 `libjbig-dev`：`src/jbig.h` 随包提供，而 `#include "jbig.h"` 会优先在
**源文件所在目录**查找，因此自动命中包内版本。

---

## 二之二、支持的平台

驱动是**纯 ANSI C + libjbig**，无汇编、无平台特有调用，因此 CPU 架构不是障碍。

| 平台 | 可用性 | 说明 |
|---|---|---|
| armhf（32 位 ARM，如海思 hi3798mv100、S905 跑 32 位系统） | ✅ | **直接用 `prebuilt/rastertolhpl-armhf`**，或现场 `make` |
| aarch64 / arm64（**S905 / S905L / S912 跑 64 位系统**、RK3399、树莓派 4/5） | ✅ | 现场 `make` 即可，**预编译的 armhf 二进制不可用于 64 位系统** |
| x86 / x86_64 台式机、NAS | ✅ | 现场 `make` |
| 树莓派 2/3（32 位） | ✅ | armhf 同路径 |

`Makefile` 会自动在 `/usr/lib/*/libjbig.so.0` 等位置探测链接库，
所以 aarch64 的 `/usr/lib/aarch64-linux-gnu/libjbig.so.0`、x86_64 的
`/usr/lib/x86_64-linux-gnu/libjbig.so.0` 都能自动命中，**不需要改 Makefile**。

### 32/64 位安全性（已实测）

页头字段一律用 `put_u16_le()` / `put_u32_le()` **显式逐字节小端写入**，
不依赖本机字节序和 ABI。曾在 armhf(ILP32) 与 arm64(LP64) 上分别编译同一份源码并比对产物：

- `width_bits` / `rows` / `raw_bytes` / `xdpi` / 纸宽 / 纸高 → **两者完全相同**
- 唯一的字节差异来自两台机器 poppler 版本不同导致的 JBIG 压缩体积差（渲染微差），与架构无关

> 早期版本用 `memcpy(hdr+2, &unsigned_long_val, 4)` 写字段，在 32 位 ARM 上**歪打正着**
> （`long` 恰好 4 字节 + 小端）；到 LP64 上 `long` 变成 8 字节，只能靠小端凑巧成立，
> 在大端机器上会静默出错。现已改为显式定宽写入。

### ⚠ 系统层面的硬要求（比架构更关键）

必须是**完整的 Linux 发行版**（Debian / Ubuntu / Armbian 等），有 `apt` 和 `systemd`。

以下**不行**，因为它们没有 CUPS 也无法安装：

- **EmuELEC / CoreELEC / LibreELEC** —— 只读 squashfs、无 apt、无 CUPS。这类系统专为复古游戏 emulator 设计，别指望它能当打印服务器
- **Android** —— 无 CUPS
- 原厂电视盒子固件（刷机前的 Android 系统）

所以 S905 盒子要当打印服务器，**先刷 Armbian**（不要刷 EmuELEC）。若同一台盒子既要玩复古游戏又要打印，只能二选一：Armbian 上也能跑游戏模拟器，但 EmuELEC 的体验更好。

---

## 三、安装

> **设计原则：默认只装驱动，不碰你现有的 CUPS 配置。**
> 不改全局 `cupsd.conf`、不开 631 对外监听、不改默认打印机、不装 AirPrint。
> 因为多数人是在**已有的 CUPS 上加装这台打印机**，安装脚本不应该有副作用。
> 共享 / AirPrint 是独立的可选项，需要时显式加 `--airprint`。

### 方式一：`make install`（推荐）

```bash
make && sudo make install
```

依次完成：依赖检查（root / cups / pdftoppm）→ 安装 filter 与 PPD → 探测 USB 设备 → 建队列。

**不会**开启共享或 AirPrint；**不会**删除已有队列。

### 方式二：`install.sh`（多了依赖自愈 + 可选 AirPrint）

```bash
cd LJ2268_linux
sudo ./install.sh                # 只装驱动，与 make install 等价
sudo ./install.sh --airprint     # 另开共享 + AirPrint 广播
```

比 `make install` 多的是：缺依赖时询问是否 `apt` 补齐，以及可选的 AirPrint。
内部仍调用同一个 Makefile 编译，不存在两套逻辑。

参数：

```bash
sudo ./install.sh --prebuilt                   # 跳过编译，用 prebuilt/ 的 armhf 二进制
sudo ./install.sh --queue LJ2268               # 自定义队列名（默认 Lenovo-LJ2268）
sudo ./install.sh --force                      # 同名队列已存在时覆盖
sudo ./install.sh --set-default                # 设为默认打印机
sudo ./install.sh --airprint                   # 开启共享 + AirPrint 广播
sudo ./install.sh --unicast 192.168.1.30       # AirPrint 再加 mDNS 单播兜底
sudo ./install.sh "usb://Lenovo/LJ2268?serial=XXXX"    # 手动指定设备 URI
```

### 对已有 CUPS 的保护（默认行为）

| 场景 | 行为 |
|---|---|
| 已存在同名队列 | **报错中止**，不删除。提示用 `--force` 覆盖或 `--queue` 改名 |
| 已有其他队列 | **不抢默认打印机**，只在"一台队列都没有"时才设为默认 |
| 未加 `--airprint` | 完全不执行 `cupsctl`，全局配置零改动 |
| `--airprint` 时 | 只做最小共享（`printer-is-shared` + `cupsctl --share-printers --remote-any`），**刻意不含 `--remote-admin`**（避免开放远程管理） |

### 方式三：全手动（想完全掌控每一步时）

```bash
# 1) 安装 filter（必须 root 拥有，否则 CUPS 拒绝执行）
sudo install -o root -g root -m 0755 rastertolhpl /usr/lib/cups/filter/rastertolhpl

# 2) 安装 PPD
sudo install -o root -g root -m 0644 ppd/LJ2268-lhpl.ppd /usr/share/cups/model/LJ2268-lhpl.ppd

# 3) 建队列（-P 用 PPD 文件路径；-m 不接受裸 .ppd 路径）
sudo lpadmin -p Lenovo-LJ2268 -D "Lenovo LJ2268 (LHPL open driver)" -L "Home" \
             -P /usr/share/cups/model/LJ2268-lhpl.ppd \
             -v "usb://Lenovo/LJ2268?serial=VP00338633VP20070701" -E
sudo cupsaccept Lenovo-LJ2268; sudo cupsenable Lenovo-LJ2268
sudo lpadmin -d Lenovo-LJ2268
sudo lpadmin -p Lenovo-LJ2268 -o printer-is-shared=true
```

设备 URI 用 `lpinfo -v | grep -i lenovo` 查。

### 验证

```bash
lp -d Lenovo-LJ2268 test/hello.pdf     # 应出纸
lp -d Lenovo-LJ2268 test/calibration-box.pdf   # 方框页，检查四边留白是否均匀
lpstat -p Lenovo-LJ2268                # 应为 idle
```

---

## 四、iPhone / AirPrint（可选）

驱动本身与 AirPrint 无关 —— 只想从 Linux 打印的话这章可以跳过。
想让 iPhone 直接打印，需要额外补两层：

1. **mDNS 记录**：CUPS 只给 IPP Everywhere（driverless）队列自动注册
   `_universal._sub._ipp._tcp` 子类型。LJ2268 是 GDI 主机型、走经典驱动队列，
   必须自己补发该子类型，否则 iOS 打印选择器压根不显示。
2. **单播兜底**：很多路由器对手机方向做了组播过滤（IGMP Snooping）——
   手机发的查询盒子收得到，盒子发的组播手机收不到。

脚本和排错手册都在 **[`print/`](print/README.md)**（含 7 条根因清单）。
这里只放入口。

### 安装

```bash
sudo ./install.sh --airprint                          # 只补 mDNS 记录
sudo ./install.sh --airprint --unicast 192.168.1.30   # 再加单播兜底（填手机 IP）
AIRPRINT_IFACE=eth0 sudo ./install.sh --airprint      # 网卡不是 wlan0 时
```

会额外做三件事：开启队列共享 + 631 对外监听（**刻意不开** `--remote-admin`）、
部署 `airprint_pub.py` 与 `airprint_push.py` 两个用户级 systemd 服务、
把队列名/网卡/种子 IP 写进 service 的 drop-in。

不用 `install.sh` 时的手动部署步骤见 `print/README.md`。

### 三个必须知道的点

| 点 | 说明 |
|---|---|
| **URF 必须宣告** | TXT 的 `pdl` 要含 `image/urf` 且要有 `URF=` 键，否则 iPhone **根本不列出**（macOS 没这个过滤，所以"Mac 能看到、iPhone 看不到"就是这个原因）。实测 iOS 在 `pdl` 同时含 `application/pdf` 时**发的就是 PDF**，所以本机没有 `urftopdf` 也无妨 |
| **UUID 要匹配** | TXT 的 `UUID=` 必须等于队列的 `printer-uuid`，否则选中即报"缺少打印机的软件"。**脚本已自动探测**，队列被重建导致 UUID 变化后最多 60 秒自动跟上，无需手工同步 |
| **PPD 里 filter 写相对名** | `*cupsFilter` 写绝对路径会让 CUPS 报 `cups-missing-filter-warning`，可能诱发 iOS 的"缺少软件"判定。本包 PPD 已用相对名 `rastertolhpl` |

### 验证

```bash
python3 print/scripts/check_txt.py      # 应看到 TXT 含 pdl=application/pdf,image/urf、URF=、UUID=
avahi-browse -r -t _universal._sub._ipp._tcp   # 子类型必须能查到
ipptool -tv ipp://localhost:631/printers/<队列名> get-printer-attributes.test \
  | grep printer-state-reasons          # 应为 none（注意 ipptool 必须带 -tv，否则无输出）
```

### 停用

```bash
systemctl --user disable --now airprint.service airprint-push.service
rm -rf ~/.config/systemd/user/airprint.service.d ~/.config/systemd/user/airprint-push.service.d
```

---

## 五、可调参数（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `LHPL_MARGIN_MM` | 4.1998 | 单侧不可打印边距，用于行数计算和裁切 |
| `LHPL_OFFSET_X_MM` | 0 | 横向微调（正=内容右移）。换机器/换纸路不对称时才用 |
| `LHPL_OFFSET_Y_MM` | 0 | 纵向微调 |

改完重新编译即可。**只有在方框页实测四边明显不对称时才需要动**，默认无需修改。

---

## 五、排错速查

| 现象 | 原因 | 处理 |
|---|---|---|
| `lpstat` 显示 completed 但不出纸 | 用错驱动（Gutenprint/PCL） | 必须本驱动；`CMD:GDI` 机型不吃通用语言 |
| `has insecure permissions (0100755/uid=1000)` | filter 非 root 拥有 | `install -o root -g root -m 0755` 装到 `/usr/lib/cups/filter/` |
| `lpadmin: Unable to copy PPD file` | 用了 `-m` 传 PPD 路径 | 改用 `-P`（大写） |
| 内容只占纸宽一半 | 页头 X 分辨率字段写错位 | 字段在 **[36:38]**，不是 [38:40]（见 PROTOCOL.md） |
| iPhone 列表里没有 | TXT 缺 `image/urf` / `URF` 键；或 `UUID` 与队列 `printer-uuid` 不一致 | 见 [`print/README.md`](print/README.md) 根因清单第 2、3 条 |
| iPhone 选中即报"缺少打印机的软件" | 同上 UUID 不匹配；或 `printer-state-reasons` 非 none | 清单第 3、5 条；PPD 的 `*cupsFilter` 要写相对名 `rastertolhpl` |
| iPhone 完全搜不到 | 路由器组播过滤（手机组播只出不进） | 清单第 4 条：靠 `airprint_push.py` 单播兜底，根治要调路由器 |
| iPhone 完全搜不到 | 不同 WiFi / AP 隔离 / 不同网段 | 确认同一 SSID 同网段；`avahi-browse -r -t _ipp._tcp` 看地址是否为真实网卡 |
| 631 只听 127.0.0.1 | 未开共享 | `sudo ./install.sh --airprint`（或 `cupsctl --share-printers --remote-any`） |
| 打印空白 | `pdftoppm` 缺失或渲染失败 | `apt install poppler-utils`，手动跑一遍看 stderr |
| 编译报 `cannot find -ljbig` | 直接手敲 gcc，且无 dev 包 | 改用 `make`（自动降级直连 `libjbig.so.0`），或 `apt install libjbig-dev` |
| 编译报找不到 jbig.h | 把源码挪离了 `src/` | `#include "jbig.h"` 按源文件所在目录查找，勿移动；或加 `-I src` |
| 提示"队列已存在"后中止 | 保护已有配置的正常行为 | `--force` 覆盖，或 `--queue` 换个名字装第二个队列 |

---

## 七、验证结论（实测）

- 官方驱动位图与本驱动位图，用墨量阈值测首个实质内容起点：
  **官方 y=936 / x=102，本驱动 y=936 / x=102，偏差 0px** —— 落位逐像素一致。
- 页头全部字段与官方逐字节吻合（A4@600：5120×6818、600dpi、2099×2970）。
- 页头末字节疑似校验和（算法未解出），**实测打印机不校验**，自算值照收。
- 位图压缩为**标准 JBIG1**，能被 `jbgtopbm` 正确解码。
