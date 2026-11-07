# Docker 部署与已有容器迁移

## 新设备：构建带驱动的镜像

先安装并启动 Docker Engine 和 Compose 插件。以下命令在 Linux 宿主机、项目目录执行：

```bash
cp .env.example .env
# 设置自己的管理员密码，避免使用示例值。
docker compose up -d --build
bash configure-printer.sh --container lj2268-cups --share --set-default
```

Dockerfile 的构建阶段在对应 CPU 架构的 CUPS 基础镜像中编译，运行阶段只复制驱动、库、PPD、USB 规则。基础镜像必须发布目标架构版本。可在 `.env` 中用 `CUPS_IMAGE` 指定可访问的兼容镜像或固定 digest；本项目不写死第三方加速器地址。

`.env` 的 `LJ2268_DRIVER=python` 为默认值，改成 `c` 后重新构建可选用新版 C 光栅 filter；回退时改回 `python` 再重建。详见 [C 驱动](C_DRIVER.md)。

Compose 使用 host 网络和 `restart: unless-stopped`。USB 是设备号可变化的热插拔设备，映射 `/dev/bus/usb` 并使用设备 cgroup 规则，不写死 Bus/Device 编号。

| 数据 | 持久化位置 |
| --- | --- |
| CUPS 配置、队列、PPD | `data/config` → `/etc/cups` |
| 队列工作目录 | `data/spool` → `/var/spool/cups` |
| 驱动和优化规则 | 自定义镜像中，重建镜像可从源码恢复 |
| 管理账号设置 | 自己的 `.env`，不得提交到公开仓库 |

管理地址 `https://设备IP:631/admin/`。 host 网络无需配置 `ports: 631:631`；已有其他 CUPS 占用 631 时，应先确定保留哪一个服务。本项目不会停止现有服务。

旧 Linux 内核可能缺少 Docker 发布端口所需的 iptables `raw` 表。实机使用 host 模式避开了已遇到的 bridge 端口发布失败；host 模式也便于局域网 mDNS，但 AirPrint 仍需要 [额外配置](AIRPRINT.md)。

## 已有 CUPS 容器：持久挂载驱动

容器名以下假设为 `cups`。在与目标容器相同的架构和兼容 libc 环境中生成文件：

```bash
sudo bash install.sh --stage /opt/cups/driver
```

32 位 ARMv7/glibc 环境如果不便安装编译器，可明确使用实机保存的库：

```bash
sudo bash install.sh --no-deps --prebuilt --stage /opt/cups/driver
```

`--prebuilt` 会检查架构和 glibc，并通过加载/编码测试；ARM64 和 x86_64 分别选择自身的 Actions 构建产物，不会误用 ARMv7 库。优先用上面的 Dockerfile 重新编译。宿主机编译出的库也必须满足容器的 libc 版本，单看 CPU 相同不足以保证。

将下列挂载合并到原 Compose 对应的 service，不要覆盖原账号、配置卷和其他设置：

```yaml
volumes:
  - /opt/cups/driver/rastertolkpl:/usr/lib/cups/filter/rastertolkpl:ro
  - /opt/cups/driver/libjbigwrap.so:/usr/local/lib/libjbigwrap.so:ro
  - /opt/cups/driver/ppd:/usr/share/ppd/lenovo:ro
  - /opt/cups/driver/usb/lenovo-lj2268-unidir:/usr/share/cups/usb/lenovo-lj2268-unidir:ro
```

确认原有 `/etc/cups` 配置卷得到保留，再使用原 Compose 文件重建该 service。驱动文件被替换后需重建/重启容器，以免 bind mount 仍指向旧 inode；不要只改容器可写层。

```bash
docker compose up -d --force-recreate cups
bash configure-printer.sh --container cups --update --share
```

## 备份、恢复和开机启动

备份项目源码、Compose、`.env` 和持久化卷。打印机空闲后停止自己的 CUPS 服务再备份配置，以得到一致快照；不要将管理员密码、证书或 spool 打印文件上传公开仓库。

```bash
sudo systemctl enable docker
docker inspect lj2268-cups --format '{{.HostConfig.RestartPolicy.Name}}'
docker compose ps
```

镜像拉取失败和驱动失败是两类问题。若错误出现 `registry-1.docker.io`，先检查 DNS、加速器是否实际支持该仓库/架构和是否回退到官方仓库，不要删除已工作的镜像或驱动数据。
