# 联想 LJ2268 Linux 打印驱动

让 LJ2268 USB 打印机通过 Linux 上的 CUPS 打印，也可配合 CUPS 共享给 iPhone。提供已编译的 C 驱动，不需要自己写代码。

## 先弄清楚：CUPS 网页能导入什么？

**网页能导入 PPD，但 PPD 不是完整驱动。** 它告诉 CUPS 该用什么纸张和转换程序；真正处理打印内容的程序也必须装好。

所以安装顺序是：**安装驱动成品 → 在 CUPS 网页添加打印机 → 选择或导入 PPD。**

如果 CUPS 在 Docker 中，驱动也要装在容器镜像里。安装在宿主机上，不会自动进入容器。

## 我应该下载哪个文件？

到 [Release 下载页](https://github.com/neekin/lenovo_lj2268_for_linux/releases/latest)。成品 `.deb` 面向 Debian 12 / Ubuntu 22.04 及更新的 CUPS 2.x 环境；旧系统可使用 Docker 或源码编译。

| 使用方式 | 下载内容 |
| --- | --- |
| CUPS 直接装在 Debian/Ubuntu 上 | 对应 CPU 的 `.deb` 安装包 |
| 用本项目的 Docker 部署，或需要完整文件 | `Lenovo-LJ2268-linux-v1.1.1.zip` |
| 需要在网页手动导入 PPD | `Lenovo-LJ2268.ppd`；前提是驱动程序已安装 |

不知道 CPU 类型时，在运行 CUPS 的那台 Linux 设备执行 `uname -m`：

| 显示结果 | 安装包后缀 |
| --- | --- |
| `armv7l`，例如这次使用的 32 位海思盒子 | `armhf.deb` |
| `aarch64` / `arm64` | `arm64.deb` |
| `x86_64`，常见 Intel/AMD 电脑和 NAS | `amd64.deb` |

## 方式一：Debian/Ubuntu 直接安装

例如 x86_64 设备下载了 `lenovo-lj2268_1.1.1_amd64.deb`：

```bash
sudo apt install ./lenovo-lj2268_1.1.1_amd64.deb
```

ARM 设备换成自己下载的 `armhf` 或 `arm64` 文件。安装包会放好程序和 PPD，**不会自动打印，也不会改已有队列**。

接好打印机 USB、开机，然后按下方“在 CUPS 网页添加打印机”操作。

如果提示 glibc 版本过旧，请使用配套 Docker，或者按[源码安装说明](docs/DEVELOPER_INSTALL.md)在目标系统编译。

## 方式二：Docker 部署

在 Linux 设备上解压完整 ZIP，进入解压后的项目目录：

```bash
cp .env.example .env
```

编辑 `.env`，把 `CUPS_PASSWORD` 改成自己的管理密码。然后：

```bash
docker compose -f compose.yaml -f compose.prebuilt.yaml up -d --build
```

这个方案把**已编译的 C 驱动**装进镜像，不在设备上编译驱动。

如果已经有自己的 `cups` 容器，请按 [已有容器升级步骤](docs/DOCKER.md#已有-cups-容器使用编译好的驱动)处理，保留原来的配置卷和队列。

## 在 CUPS 网页添加打印机

1. 打开 `https://运行CUPS的设备IP:631/admin/`，登录自己的管理员账号。
2. 选择 **Administration → Add Printer**，选 USB 列表中的 **Lenovo LJ2268**。
3. 填写打印机名称；需要让其他设备打印时勾选共享。
4. 型号里选择 **Lenovo LJ2268**。如果列表里没有，点 **Provide a PPD File**，上传下载包中的 `ppd/Lenovo-LJ2268.ppd`。
5. 设为 **A4、600dpi、灰度**，保存后再打印一页测试。

详细操作步骤和常见提示见 [CUPS 使用说明](docs/CUPS.md)。iPhone 搜索和共享设置另见 [AirPrint 说明](docs/AIRPRINT.md)。

## 左右留白不一样怎么办？

C 版从 v1.1.1 起支持水平校准，**默认不移动页面**。按[位置校准步骤](docs/ALIGNMENT.md)测量并设置即可；本次设备最终使用的左移约 0.5 mm 是示例值。

## 验证到什么程度？

- 新 C 版在 ARMv7、ARM64、x86_64 上，与原 Python 版进行了同一光栅输入的完整字节对比。
- 安装、CUPS 转换、Docker、异常输入与内存检查由自动化测试覆盖，[结果见 Actions](https://github.com/neekin/lenovo_lj2268_for_linux/actions)。
- Python 版和新版 C 均已在 ARMv7＋USB LJ2268 上实际出纸；C 版中英文文字、细线、网点及水平校准已确认正常。iPhone 实际出纸此前在 Python 版验证，升级 C 后保留同一 AirPrint 配置。
- 主要目标是 A4、600dpi。**16K 暂不支持**，LJ2268W 和其他型号不宣称经过实机验证。

## 其他说明

- [Docker 部署与已有容器升级](docs/DOCKER.md)
- [iPhone / AirPrint 搜不到或打印慢](docs/AIRPRINT.md)
- [换设备迁移](docs/MIGRATION.md)
- [C 与 Python 的速度、内存和一致性结果](docs/C_DRIVER.md)
- [源码编译和命令行安装](docs/DEVELOPER_INSTALL.md)
- [协议细节](docs/PROTOCOL.md)、[第三方源码与许可证](THIRD_PARTY.md)

预编译 C 程序需要兼容的 Linux/glibc 环境，当前发布产物引用到 glibc 2.34；源码和许可证完整提供。源码安装脚本仍默认 Python，明确传入 `--driver c` 才切换 C 版本。
