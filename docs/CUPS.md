# 在 CUPS 网页中安装 LJ2268

## 一、先安装完整驱动

CUPS 网页中的“上传 PPD”只安装打印机描述，**不会替你安装实际转换程序**。

- CUPS 直接运行在 Debian/Ubuntu：先安装 Release 中对应架构的 `.deb`。
- CUPS 运行在 Docker：使用配套的预编译 Docker 方案，或按 [Docker 文档](DOCKER.md)升级已有容器。

完成这一步，再打开 CUPS 网页。

## 二、打开管理页面

地址是 `https://运行CUPS的设备IP:631/admin/`。

例如打印服务器地址为 `192.168.1.50`，就打开 `https://192.168.1.50:631/admin/`。请用自己实际的地址，不要用容器内部的 `172.x.x.x` 地址。

登录账号与密码由自己的系统或 Docker `.env` 设置。

原生 CUPS 如果只允许本机访问，可先在服务器本机打开 `http://localhost:631/admin/`。局域网管理权限由 CUPS 配置决定，驱动包不会自动开放远程管理。

如果提示“需要升级，必须通过 HTTPS 访问”，把网址开头的 `http://` 改成 `https://`。自己的服务器使用自签名证书时，浏览器可能需要确认后继续。

## 三、添加 USB 打印机

1. 把打印机 USB 接到运行 CUPS 的设备上，并开机。
2. 在网页点击 **Administration（管理）→ Add Printer（添加打印机）**。
3. 在 Local Printers / USB 列表里选择 **Lenovo LJ2268**，继续。
4. 填写名称，例如 `Lenovo_LJ2268`。需要局域网共享时，勾选 **Share This Printer**。
5. 到选择驱动的页面，先看列表里是否有 **Lenovo LJ2268**。
6. 没有列出时，在 **Provide a PPD File** 处上传下载包内的 `ppd/Lenovo-LJ2268.ppd`，再继续。
7. 默认选 **A4、600dpi、灰度**，保存。

**不要把 `.deb` 或 C 可执行文件上传到 PPD 选择框。** 那里只接受 PPD；`.deb` 是系统安装包。

## 四、确认可以打印

在 Printers 页面打开新建的打印机，选择 **Maintenance → Print Test Page**。确认实际出纸、文字和图形正常。

看到任务“Completed”只表示 CUPS 已处理完成，仍需确认纸面。C 版已在 ARMv7＋USB LJ2268 上通过中英文实机测试，自动化测试仍不等于每台设备都经过纸面确认。

如果内容完整但左右留白不一致，按[位置校准](ALIGNMENT.md)量距离再调整；新驱动默认不移动页面。

## 五、已有队列怎么办？

安装驱动包不会删除已有队列。如果队列本来就使用本项目的 `rastertolkpl`，驱动文件替换后仍可沿用。

若队列原来选的是通用驱动或其他 filter，进入打印机的 **Administration → Modify Printer**，重新选择本包的 Lenovo LJ2268 / PPD。保留原来的 USB 设备地址。

## 常见问题

| 现象 | 先检查什么 |
| --- | --- |
| USB 列表没有 LJ2268 | 打印机开机、USB 接线；Docker 是否映射 USB |
| 能上传 PPD，但显示 Filter failed | 真正的 C 程序是否安装在 CUPS 所在环境，架构/glibc 是否兼容 |
| 网页能打开，iPhone 却搜不到 | [AirPrint 发现配置](AIRPRINT.md)，不是重复上传 PPD |
| 想自己编译或用命令创建队列 | [开发与命令行安装](DEVELOPER_INSTALL.md) |
| 16K 打印报错 | 当前 C 版明确不支持这个异常模板；请改为 A4 等受支持纸型 |
