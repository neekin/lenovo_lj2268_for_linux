# Lenovo LJ2268 Linux / CUPS 驱动与迁移工具

[![Linux validation](https://github.com/neekin/lenovo_lj2268_for_linux/actions/workflows/validate.yml/badge.svg)](https://github.com/neekin/lenovo_lj2268_for_linux/actions/workflows/validate.yml)

供 **Lenovo LJ2268 USB 打印机**使用的社区驱动。将 CUPS raster 转为 LHPL/JBIG 数据，提供安装脚本、Docker 镜像构建、CUPS 配置、AirPrint 和换设备迁移文档。

当前发布以实际运行过的 **Python 3＋原生 C JBIG 库**为基础：Python 组织协议，Pillow 加速灰度处理，JBIG 压缩由 C 执行。它替代本仓库早期的实验性 C/PDF 实现。旧实现仍可从 Git 历史查阅；两者不能只按实现语言比较正确性和性能。

现另提供接收相同 CUPS raster 的 **修正后 C 版**。安装时用 `--driver c` 明确选择；默认仍保留 Python 版。完整字节一致性范围、速度数据、Docker 选择和回退方法见 [C 驱动说明](docs/C_DRIVER.md)。

## 验证范围

| 环境 | 验证内容 |
| --- | --- |
| Linux ARMv7/armhf＋CUPS 2.4.10 容器＋USB LJ2268 | 已实际出纸；中英文和 iPhone AirPrint 打印已由使用者确认 |
| Ubuntu 24.04 x86_64 | GitHub Actions 原生编译、安装、离线编码、PDF 转换、队列配置和 Docker 构建；结果见上方 CI |
| Ubuntu 24.04 ARM64 | 同上，使用 `ubuntu-24.04-arm` 原生运行器；结果见上方 CI |
| LJ2268W、其他纸型、其他打印机及复杂多页作业 | 不宣称全面实机验证 |

CI 不能验证 USB 硬件、出纸质量和手机能否收到 mDNS。支持目标为 **Linux＋CUPS 2.x**；不是 Windows/macOS 安装包，也不适用于 CUPS 3 的无 PPD 驱动流程。

## 系统上直接安装

Debian/Ubuntu，打印机可以稍后再连接：

```bash
git clone https://github.com/neekin/lenovo_lj2268_for_linux.git
cd lenovo_lj2268_for_linux
sudo bash install.sh
# 接好 USB 并开机后创建队列；不会自动打印。
sudo bash configure-printer.sh
```

安装器会安装依赖、在当前设备编译 JBIG 库、执行离线检查、备份已有同名驱动文件，然后安装 filter、PPD 和 USB 兼容规则。**驱动安装与创建队列是两个独立步骤。**

```bash
# 同名队列存在时，明确要求更新；不会先删除队列。
sudo bash configure-printer.sh --update
# 需要共享或设为默认打印机时明确指定。
sudo bash configure-printer.sh --update --share --set-default
```

## 使用 Docker

适合新设备上已有 Docker 的情况，镜像构建时在容器内部编译，避免宿主机和容器的 libc 不匹配：

```bash
cp .env.example .env
# 编辑 .env，设置自己的 CUPS_PASSWORD。
docker compose up -d --build
bash configure-printer.sh --container lj2268-cups --share --set-default
```

管理入口通常为 `https://设备IP:631/admin/`；账号和密码来自自己的 `.env`。驱动在镜像内，配置和队列数据在 `data/` 中。宿主机 631 端口需要可用。

**只添加驱动到现有容器**，请用 [Docker 文档](docs/DOCKER.md) 的持久挂载方案；不要仅 `docker cp` 到容器可写层后就当作备份完成。

## 文档

- [在 CUPS 网页和命令行安装、添加打印机与验证](docs/CUPS.md)
- [Docker 部署、权限、持久化、镜像下载和开机自启](docs/DOCKER.md)
- [iPhone / AirPrint 配置及“搜不到”的排查](docs/AIRPRINT.md)
- [打印性能、USB 等待优化、Python 与旧 C 实现](docs/PERFORMANCE.md)
- [新版 C 的一致性验证、速度、安装和回退](docs/C_DRIVER.md)
- [换设备迁移、备份与恢复](docs/MIGRATION.md)
- [协议与验证边界](docs/PROTOCOL.md)
- [第三方源码和许可证](THIRD_PARTY.md)

## 文件

`rastertolkpl` 是 Python filter；`source/` 提供 C 包装器和完整 JBIG-KIT 编译源码；`ppd/` 是 CUPS 设备描述；`usb/` 是仅针对 `17ef:5439` 的 USB 单向规则。`prebuilt/linux-armv7-glibc/` 保存实机使用的 32 位 ARM 库。

`build-native.sh`、`install.sh`、`configure-printer.sh` 均支持 `bash` 调用，不依赖解压工具是否保留可执行位。其他架构优先现场编译，不能把 ARMv7 `.so` 直接复制过去。

包内另含 Actions 原生构建的 ARM64、x86_64 库及构建来源记录。已有系统依赖时可用 `sudo bash install.sh --no-deps --prebuilt`，安装器按 CPU 选择文件并先执行加载和编码检查。若 libc 不兼容，应改用源码编译，不能保证每个旧发行版都可运行 Ubuntu 24.04 构建产物。

默认安装不打印测试页、不创建管理员账号、不更换默认打印机，也不会自动套用旧设备的固定 IP 或 mDNS 主机名。AirPrint 需按文档另行配置和在手机上验收。
