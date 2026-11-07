# 打印内容左右不居中时怎么调

适用于 **v1.1.1 及更新的 C 驱动**。默认偏移为 0；Python 版和旧版成品不识别下面的校准参数。

## 1. 先量纸面

使用 A4 纸，确认纸盒导纸板贴合纸张，再打印一页有对称边框的测试页。

量纸张左边缘到左边框、右边缘到右边框的距离。如果边框明显歪斜或每张偏差不同，先处理纸张定位。如果每次都向同一侧偏移，再校准。

- 左侧空白更宽：内容需要向左移动。
- 右侧空白更宽：内容需要向右移动。
- 移动距离是**左右空白差值的一半**。左右基本一致时即可停止。

已经设置过偏移时，这个移动量要叠加到当前值上。例如当前左移 3 mm，纸面左 8 mm、右 13 mm，需要向右调回约 2.5 mm，最终只保留左移约 0.5 mm。

## 2. 把毫米换成像素

本驱动使用 600 dpi，1 mm 约为 23.62 个像素。负数向左，正数向右，取最接近的整数。

| 目标偏移 | 参数值 |
| --- | --- |
| 不移动 | `0` |
| 向左约 0.5 mm | `-12` |
| 向左约 1 mm | `-24` |
| 向右约 0.5 mm | `12` |

以下用 `-12` 演示。**这是某台设备实测后的值，需要按自己的纸面结果选择。**

## 3. 修改 CUPS 配置

等打印队列空闲后，先备份并编辑 **CUPS 实际使用的 `cups-files.conf`**：

```bash
sudo cp -a /etc/cups/cups-files.conf /etc/cups/cups-files.conf.before-lj2268-alignment
sudo nano /etc/cups/cups-files.conf
```

在文件末尾添加下面一行。如果已经有 `LHPL_X_SHIFT_DOTS`，只修改原来的那一行：

```conf
SetEnv LHPL_X_SHIFT_DOTS -12
```

这行要写在 **`cups-files.conf`**，不能写在 `cupsd.conf`。CUPS 2.4 对错误文件中的 `SetEnv` 可能只提示迁移，语法检查也可能成功，但不会把参数传给驱动。

如果 CUPS 在 Docker 中，修改挂载给容器 `/etc/cups` 的配置目录。例如本项目 Compose 默认是 `data/config/cups-files.conf`；已有容器以自己的挂载为准。文件所在环境仍然必须安装支持此参数的新 C 驱动。

## 4. 检查并重启打印服务

原生 CUPS：

```bash
sudo cupsd -t
sudo systemctl restart cups
```

Docker：以下容器名使用本项目默认的 `lj2268-cups`，已有容器换成自己的名称；确认语法检查成功后再重启这个容器。

```bash
docker exec lj2268-cups /usr/sbin/cupsd -t
docker restart lj2268-cups
```

然后打印一张测试页，重新量左右空白。驱动日志中的 `LHPL horizontal calibration` 应显示设定的像素值。CUPS 任务完成还需要结合实际纸面判断。

## 5. 恢复原位置

将参数改为 `0`，或移除这行，再按上一步检查并重启打印服务。

## 校准会影响什么

校准只平移打印内容，不改变纸张、字号或缩放比例；超出点阵边界的部分会裁掉。示例 `SetEnv` 会作用于该 CUPS 服务中所有使用本项目 C 驱动的队列，电脑和 iPhone 通过这些队列提交的作业都会沿用。

参数允许 -6000 到 6000 的整数像素。默认值为 0，不会由安装包或 Docker 自动套用某台打印机的校准值。

配置文件和重启要求可参考 [CUPS 官方 cups-files.conf 手册](https://openprinting.github.io/cups/doc/man-cups-files.conf.html)。

## 本次实机结果

2026-11-07，ARMv7＋USB Lenovo LJ2268：最终使用 `-12`，实际左移约 0.508 mm。用户确认中英文、细线、网点正常，左右留白基本一致。该页 CUPS 转换和 USB 发送约 5.47 秒，不包含使用者观察到的全部机械出纸时间。记录见[实机验证](../evidence/physical-c-print-20261107.json)。
