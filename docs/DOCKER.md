# Docker：把编译好的驱动放进 CUPS

## 新设备，第一次部署

1. 下载并解压 Release 的**完整 ZIP**，进入项目目录。包内 `packages/` 已有各架构 `.deb`。
2. 运行 `cp .env.example .env`，编辑 `.env`，设置自己的 `CUPS_PASSWORD`。
3. 启动：

```bash
docker compose -f compose.yaml -f compose.prebuilt.yaml up -d --build
```

这里的 `--build` 是把现成驱动包安装进 CUPS 镜像，**不是在你的设备上编译 C 代码**。

4. 打开 `https://设备IP:631/admin/`，用 `.env` 中设置的账号密码登录。
5. 按 [CUPS 网页说明](CUPS.md)添加 USB 打印机，选择 Lenovo LJ2268 或上传 PPD。

## 已有 CUPS 容器：使用编译好的驱动

下面假设原 service/container 叫 `cups`。先保存原 Compose 文件，打印机空闲时操作。

### 1. 构建新镜像

在解压后的完整项目目录运行：

```bash
docker build -f Dockerfile.prebuilt -t lj2268-cups:prebuilt .
```

镜像会按容器架构选择 `packages/` 里对应的成品 `.deb`。

### 2. 修改原 Compose

将原 service 的镜像改成：

```yaml
image: lj2268-cups:prebuilt
```

如果此前挂载了旧 Python 驱动，移除下面四条**旧驱动挂载**，否则旧文件会盖住新镜像中的 C 程序：

```yaml
- /opt/cups/driver/rastertolkpl:/usr/lib/cups/filter/rastertolkpl:ro
- /opt/cups/driver/libjbigwrap.so:/usr/local/lib/libjbigwrap.so:ro
- /opt/cups/driver/ppd:/usr/share/ppd/lenovo:ro
- /opt/cups/driver/usb/lenovo-lj2268-unidir:/usr/share/cups/usb/lenovo-lj2268-unidir:ro
```

保留原来的管理员环境变量、`/etc/cups`、spool、USB 和 D-Bus 挂载。它们分别保存账号设置、队列、打印任务和 iPhone 发现所需连接。

### 3. 用原 Compose 重建这个服务

在原 Compose 文件所在目录执行：

```bash
docker compose up -d --force-recreate cups
```

然后检查 CUPS 网页中的原队列，并由使用者提交一页测试。不要为升级驱动把原来的配置卷清空。

## iPhone 还需要哪些设置？

驱动只负责打印数据转换，iPhone 发现还需要共享和 mDNS。

新部署可先在宿主机启用 Avahi，再使用附加配置：

```bash
sudo apt-get install -y avahi-daemon avahi-utils
sudo systemctl enable --now avahi-daemon
docker compose -f compose.yaml -f compose.prebuilt.yaml -f compose.airprint.yaml up -d --build
bash configure-printer.sh --container lj2268-cups --update --share
```

完整的主机名、广播和排查步骤见 [AirPrint 文档](AIRPRINT.md)。原先已经正常使用 AirPrint 的容器，升级时保留原有相关配置。

## 哪些数据需要保留？

| 内容 | 新部署的默认位置 |
| --- | --- |
| 队列、CUPS 配置 | `data/config` |
| 打印任务目录 | `data/spool` |
| 管理账号设置 | 自己的 `.env` |
| 编译好的驱动 | 新镜像中，可从 `.deb` 重新安装 |

Compose 已设置 `restart: unless-stopped`；宿主机还需启动 Docker 服务，例如 `sudo systemctl enable docker`。

本方案使用 host 网络，不需要再写 `ports: 631:631`。设备的 631 端口需要可用。此前旧内核环境出现过 Docker bridge 发布端口失败，host 模式是该实机采用的方案。

## 回退与源码构建

- 已有容器升级前保存原 Compose。回退时恢复原镜像及对应的旧驱动挂载，再重建原 service。
- 想自行编译或选 Python：使用 `Dockerfile`，在 `.env` 设置 `LJ2268_DRIVER=python` 或 `c`，然后 `docker compose up -d --build`。
- 想使用宿主机文件挂载：安装器支持 `--stage`，但编译/校验环境必须与目标容器的 CPU 和 libc 兼容。见 [开发安装说明](DEVELOPER_INSTALL.md)。
- 镜像拉取时出现 `registry-1.docker.io` 属于镜像源/DNS 问题，不能靠重新导入 PPD 解决。
