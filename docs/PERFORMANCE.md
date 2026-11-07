# 性能优化与实现选择

新版已修正的 C 光栅 filter 与下面的历史 C/PDF 实现不同。新版与 Python 的同输入完整字节比较和测量见 [C 驱动说明](C_DRIVER.md)，原始记录见 `evidence/c-parity-*.json`。

## 实机已经验证的优化

### 灰度处理从 Python 循环改为 Pillow 原生处理

默认 8 位灰度、无抖动的路径使用 Pillow 的 C 实现做查表和位打包，JBIG 压缩也由 C 库执行。只有协议组织和调度主要使用 Python。

同一张曾成功打印的 iPhone A4 页，4760×6818 像素，离线编码从 **37.428 秒降到 3.289 秒**。两次 JBIG 输出同为 26923 字节，SHA-256 完全一致。证据在 `evidence/performance-validation.json`。

这是当时 ARMv7 设备的编码基准，不是从手机点击打印到纸张出来的总耗时。未安装 Pillow 时，filter 有较慢的 Python 回退实现，因此安装脚本会安装 `python3-pil`。

### USB 完成状态等待

`usb/lenovo-lj2268-unidir` 包含仅对 `17ef:5439` 生效的 CUPS 规则：

```
0x17ef 0x5439 unidir
```

它禁用 USB bulk 的双向状态回读。空数据后端测试曾从 8.172 秒降到 0.105 秒；规则持久挂载并重建容器后为 0.177 秒。这个测试没有出纸，也不能据此保证每份作业必然缩短 8 秒。

规则必须安装在 CUPS 实际使用的 `/usr/share/cups/usb/` 中；容器内需要持久挂载或写入自定义镜像。后来提交的实际中英文测试页正常。

## C 与 Python＋JBIG 哪个更好？

- C 更容易实现低内存逐页处理，并减少解释器开销；在协议、渲染输入、输出质量相同的前提下，通常有更好的性能潜力。
- 当前 Python 版的两项主要计算已由 C 执行，不能把它等同于完全使用 Python 逐像素压缩。
- 仓库早期 C 版直接接收 PDF，并调用 `pdftoppm`；当前版接收 CUPS raster。两条路径包括的渲染阶段不同，不能直接拿某个函数的时间作端到端结论。
- 早期 C 源码还保留不同的 JBIG 参数、57 字节零填充页结束载荷和待确认的页头校验；与实机成功的版本并不等价。本次发布不把它当作“更快且可直接替换”的驱动。

新版 C 已完成同一 raster 的字节对比，并通过 ARMv7＋USB LJ2268 的 A4 中英文实机打印。下面保留早期 C/PDF 路径的历史数据；新版结果见 [C 驱动说明](C_DRIVER.md)。源码安装脚本仍默认 Python，成品 `.deb` 和预编译 Docker 使用 C。

### 2026-11-07 离线对比

同一 ARMv7 环境、同一 `hello.pdf`，每项运行三次，中位数如下：

| 路径 | 中位耗时 | 说明 |
| --- | --- | --- |
| CUPS PDF → raster | 2.796 秒 | 当前 Python 路径的上游渲染阶段 |
| Python＋JBIG，raster → LHPL | 4.182 秒 | 不含上游渲染；页结束帧为 64 字节 |
| 原仓库 `c7753a2` 的 C 预编译版，PDF → LHPL | 3.567 秒 | 含其自己的渲染；页结束帧实际为 63 字节 |

C 版在此样本上耗时更短，但渲染方式、压缩参数和帧数据不等价，且未发送到打印机，**不能当作同等质量、同等正确性的性能排名**。原始记录见 `evidence/legacy-c-comparison.json`。这也是保留已实机确认实现作为默认版本的原因。

## 排查慢在哪里

分别记录上传开始/结束、CUPS 开始过滤、filter 完成、USB 后端完成以及实际出纸时间。大 PDF、照片栅格化、网络传输、打印机唤醒和机械走纸都可能成为主要耗时。

连接改为路由器打印服务器后，原 USB quirk 不再作用于 CUPS 主机的 socket 后端，需要重新实测网络后端和打印服务器的状态等待。CUPS AppSocket 的 `waiteof` 行为参见 [OpenPrinting 网络打印文档](https://openprinting.github.io/cups/doc/network.html)。

## C 版最终实机记录

2026-11-07 的中英文校准页，服务器转换和 USB 发送约 **5.47 秒**，用户确认纸面正常、左右留白基本一致。记录见 [physical-c-print-20261107.json](../evidence/physical-c-print-20261107.json)。该页与历史 iPhone 页不同，不能直接用二者计算整次打印的加速倍数。
