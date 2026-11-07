# 换设备时如何恢复

## 保留哪些东西

保留整个项目或 Git commit、自己的 Compose、`.env`、CUPS 配置卷、AirPrint 主机名发布 service。打印任务文件可能含私人文档，按需单独保存，不放到公开仓库。

## 原生 Linux

1. 新设备安装 CUPS 2.x，运行 `sudo bash install.sh`，让库在新架构上重新编译。
2. 打印机接到新设备，运行 `lpinfo -v` 核对 USB URI。
3. 运行 `sudo bash configure-printer.sh`；原有队列已存在时用 `--update`。
4. 原来需要共享、默认打印机时明确添加 `--share --set-default`。
5. 按 `AIRPRINT.md` 配置新设备 LAN 地址、唯一主机名、共享和发现，然后手机实际测试。

## Docker

推荐在新设备重新构建 Dockerfile，并还原自己的配置卷。若从旧设备恢复完整 `/etc/cups`，先检查其中的 Listen 地址、ServerAlias、DNSSDHostName、证书和队列 URI，避免沿用旧机器 IP 或不存在的 USB 设备。

使用 `--stage` 挂载方案时，新架构重新生成 `libjbigwrap.so`；ARMv7、ARM64、x86_64 的库不能互换。动态库还受 libc ABI 约束；优先在目标容器镜像内编译。

旧设备应停止打印服务或移除冲突的广播后，再让新设备使用相同 IP/`.local` 名称，避免网络上同时出现两个同名服务器。此步骤由迁移使用者按自己的环境安排，安装器不会远程关闭其他设备。

## ARMv7 离线恢复

包内的 `prebuilt/linux-armv7-glibc/libjbigwrap.so` 是当前实机所用库。已有 Python 和 CUPS 时，可以：

```bash
sudo bash install.sh --no-deps --prebuilt
sudo bash configure-printer.sh
```

没有 Python/CUPS 等系统依赖时仍需从可信的软件源安装；这个包不是完整 Linux 离线系统镜像。

## 最后验收

- 离线 selftest 通过，PPD 检查通过。
- USB 被识别，CUPS 队列正确，没有误用其他设备。
- 明确提交测试页，纸面中英文、图形和边距正常。
- 如需 AirPrint，手机能发现、能打印。
- 重启自己的新设备后再次确认服务自启和手机发现。
