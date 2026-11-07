# 与 Python 基准一致的原生 C 光栅驱动

本版本的 `source/rastertolkpl.c` 是 **CUPS raster → LHPL** filter。它与当前 Python filter 使用相同输入，不是仓库早期调用 `pdftoppm` 的 PDF filter。旧版历史代码和当时的对比数据不代表新版的行为。

## 一致性依据

基准文件仍为原来的 `rastertolkpl`，SHA-256：

```
5b7d3c2c60a08bc1362b4777f5bb250163ff47407380fedaaf257a433f30ea03
```

没有为了让测试通过而修改 Python 协议输出。`tools/generate_c_tables.py` 从它读取页头/页结束参考值并生成 `source/protocol_tables.h`，`--check` 防止表格漂移。

修正内容包括 58 字节载荷、完整 64 字节帧、异或校验、两处 LE32 压缩长度、JBIG 的 l0/options/mx/my、正确纸型标识与图像尺寸、PJL 份数及同一灰度阈值/位打包方式。C 版不调用 shell 或外部 PDF 渲染命令。

比较使用相同 job 参数和主机名，并固定测试时钟，**对完整 stdout 逐字节比较**，包括 PJL、所有帧和全部 JBIG 字节。正式使用时照常写入实际作业时间；仅测试工具使用 `LHPL_JOB_EPOCH` 固定时间，Python 由独立测试包装器冻结时钟。

v1.1.1 增加可选水平校准 `LHPL_X_SHIFT_DOTS`。默认 0 时仍与 Python 完整字节一致；明确设置非零时会按要求平移单色点阵，因此输出会相应改变。校准不改变纸张或字号，空出的区域填白，超出原点阵边界的内容裁掉。设置步骤见[位置校准](ALIGNMENT.md)。

用例覆盖灰度阈值、非字节/512 点对齐宽度、行填充、1/24/32bpp、Bayer 抖动、七种正常长度的纸型模板及横向、两种多页头排列、stdin、份数、UTF-8 标题、页结束覆盖和超过 65535 字节的压缩长度。另对真实 CUPS 生成的 A4 光栅比较并测时。

### 明确的范围限制

- 现有 Python 的 **16K 模板是 59 字节**，不是规定的 58 字节。C 版明确拒绝 16K（以及回退到此模板的自定义纸型），不会复制这条异常输出；该纸型不在一致性通过范围内。
- C 版针对与 Python 相同的、以 `3SaR` 开始的小端未压缩 raster 及其两种多页排列；不声称支持所有压缩 CUPS/PWG Raster 格式。
- 非法格式、截断页、异常阈值会报错，并在开始输出作业前检查。Python 原型的部分容错行为会忽略不完整尾部，C 版对此更严格。
- 1bpp 和 RGB＋抖动选项保留基准的既有解释；这不代表所有其他色彩空间都经过实机验证。默认 PPD 的 600dpi/8 位灰度路径是当前主要目标。
- `@ep` 中未恢复语义的不透明字段仍与正常工作的参考值一致，未声称支持全部厂商扩展功能。

## 安装与回退

默认依然安装 Python 版。明确选择 C：

```bash
sudo bash install.sh --driver c
# 依赖已满足，且预编译产物与当前 glibc 兼容时：
sudo bash install.sh --driver c --no-deps --prebuilt
```

安装器先运行 Python 基准自检，再进行 C/Python 的完整一致性检查，最后才写入系统。PPD 引用名仍是 `rastertolkpl`，已有队列无需更换 URI；原有文件会备份。

回退 Python：

```bash
sudo bash install.sh --driver python
```

C 程序运行时不需要 Python/Pillow/`libjbigwrap.so`，JBIG 编译在可执行文件内；安装、生成表格和验证阶段仍使用 Python。发行包包含完整 JBIG 源码和 GPL 许可证。

预编译二进制的运行环境见各架构 `C_BUILD.json`。glibc 版本不兼容时，应在目标系统/容器内编译，不能仅凭 CPU 型号保证兼容。

## Docker 与现有持久挂载

在 `.env` 中选择：

```dotenv
LJ2268_DRIVER=c
```

然后用原来的 Compose 文件重建自己的服务：

```bash
docker compose up -d --build
# 原先用了 AirPrint override 时继续保留它：
docker compose -f compose.yaml -f compose.airprint.yaml up -d --build
```

容器网络、配置卷、USB、AirPrint、D-Bus 设置不因选择 C 版而改变。切回 `LJ2268_DRIVER=python` 并重建即可回退。

采用现有 `--stage` 绑定挂载方案时：

```bash
sudo bash install.sh --driver c --stage /opt/cups/driver
# 必须使用自己的原 Compose 文件，保留全部挂载和队列数据。
docker compose up -d --force-recreate cups
```

替换宿主机文件后，容器的文件 bind mount 可能仍指向旧 inode，所以应重新创建相应容器。此项目发布过程不会替换线上设备的驱动，也不会自动打印。

## 性能与复现

以下是 v1.1.0 的 ARMv7 编码基准，保留在 [c-benchmark-armv7-v1.1.0.json](../evidence/c-benchmark-armv7-v1.1.0.json)。同一设备、同一份 32455480 字节 A4 raster，每版预热一次后运行五次：

| 指标 | Python＋原生 JBIG | 修正后 C |
| --- | --- | --- |
| 编码中位时间 | 4.155 秒 | 2.265 秒 |
| 峰值 RSS 中位数 | 147288 KiB，约 143.8 MiB | 32980 KiB，约 32.2 MiB |
| 输出 | 完整字节一致 | 完整字节一致 |

该样本中编码加速约 **1.83 倍**，峰值 RSS 下降约 **77.6%**。不包括 PDF 上游渲染、网络上传、USB 等待、打印机唤醒和走纸，不能据此承诺实际出纸时间同比缩短。C 按页生成位图与压缩，但仍保留整个作业输入；内存用量随作业大小增长。

```bash
bash build-native.sh
bash build-c.sh
python3 tests/compare_drivers.py --native build/rastertolkpl-c \
  --library build/libjbigwrap.so --raster 自己的同一份.raster \
  --benchmark --report build/c-parity.json
```

测量使用 Linux `/usr/bin/time` 采集每个进程的 RSS，每次输出均核对 SHA-256。ARM64、x86_64 的结果由 GitHub Actions 原生 runner 生成，分别与同一 runner 上的 Python 基准比较，不用不同机器的绝对耗时作排名。证据文件在 `evidence/c-parity-*.json`。

## 实机打印与校准验证

2026-11-07 已把当前 ARMv7 设备的实际 CUPS 驱动切换到 C，并通过 USB LJ2268 打印中英文、标点、细线和黑白网点。未校准页的服务器转换及 USB 发送约 5.53 秒，用户确认约 10 秒内正常出纸。

随后增加可选水平校准，实测左右距离后最终使用 -12 点（约左移 0.508 mm）。最终页服务器处理约 5.47 秒，用户确认左右留白基本一致、效果正常。记录见 [physical-c-print-20261107.json](../evidence/physical-c-print-20261107.json)。

校准测试用独立的逐像素平移结果作为期望值，再编码并比较完整打印流。覆盖 1/8/24/32 位输入、抖动、非字节边界、左右移动、超出页宽和非法参数。另将实际 CUPS 作业发送到本机 TCP 接收器，核对参数确实传入驱动，且打印数据与独立验证结果一致；这一步不使用 USB、不消耗纸张。

纸面验收范围仍是 ARMv7、USB LJ2268、A4/600dpi。ARM64、x86_64 由 Actions 验证编译、安装、输出和内存安全，不等同于各架构都接过实机。当前 CUPS/AirPrint 共享配置保留，iPhone 在 C 版下的完整实机任务尚未另测。
