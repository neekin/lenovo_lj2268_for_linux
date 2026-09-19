# LHPL 协议规格（逆向成果）

对象：Lenovo LJ2268 / LJ2268W（IEEE 1284 Device ID:
`MFG:Lenovo;CMD:GDI;MDL:LJ2268;CLS:PRINTER;CID:Lenovo_Printer_GDI;`）

逆向方法：在 macOS 上跑官方 filter `LNTHR6Z`（x86_64 Mach-O），
喂标准 CUPS 栅格，捕获其输出的 LHPL 真值；再用**差分实验**（换纸张 / 换分辨率）
逐字段反推含义。全程黑盒取样，未做指令级反汇编。

---

## 1. 整体结构

```
ESC%-12345X                        ← UEL（Universal Exit Language）
@PJL JOB NAME="..."                ← 作业信息（含 JOBATTR=DATE/TIME 等）
@PJL SET RESOLUTION=600
@PJL SET BITSPERPIXEL=1
@PJL ENTER LANGUAGE=LHPL
    ESC L H @ s j   + 58B 参数      ← 作业开始（每作业一次）
    ┌ 每页:
    │ ESC L H @ s p + 58B 页头 + JBIG 数据
    │ ESC L H @ e p + 57B 参数
    └
ESC%-12345X
@PJL EOJ
ESC%-12345X
```

命令块统一为：`0x1B 0x4C 0x48 0x40` + 两字符命令（`sj` / `sp` / `ep`）。

---

## 2. 页头（58 字节，紧跟 `sp` 之后）

| 偏移 | 类型 | 含义 | A4@600 实测 |
|---|---|---|---|
| [0] | u8 | 纸张 ID | `02` |
| [1] | u8 | 固定 `01` | `01` |
| [2:6] | u32 LE | 位图宽（bit） | 5120 |
| [6:10] | u32 LE | 行数 | 6818 |
| [10:14] | u32 LE | 未压缩字节数 | 4363520 |
| [14:18] | u32 LE | JBIG 压缩长度 | 1951 |
| [18:22] | u32 LE | 同上（官方重复写一次） | 1951 |
| [36:38] | u16 LE | **X 分辨率 dpi** | 600 |
| [38:40] | u16 LE | 纸宽（0.1mm） | 2099 |
| [40:42] | u16 LE | 纸高（0.1mm） | 2970 |
| [57] | u8 | 疑似校验和 | `d4`（**打印机不校验**） |

> ⚠️ 踩过的坑：分辨率/尺寸字段在 **[36:44]**，不是 [38:46]。
> 写错会让 X 分辨率读到 0，打印机回退 1200dpi 渲染，
> 表现为**内容只占纸宽一半**。

### 纸张 ID（官方驱动实测）

A4=2, Letter=1, Legal=3, Executive=5, A5=6, B5=7, A6=8

### 尺寸换算

厂商不取整毫米，而是由 PPD 的 `PaperDimension`(pt) 换算：

```
mm = pt * 25.4 / 72
595pt → 209.9mm → 2099      (A4)
612pt → 215.9mm → 2159      (Letter)
```

### 几何公式

```
row_bytes  = ceil( ceil(纸宽mm / 25.4 * xdpi) / 8 / 64 ) * 64     # 64字节对齐
width_bits = row_bytes * 8
rows       = round( (纸高mm - 2 * 4.1998) / 25.4 * ydpi )          # round 不是 ceil
```

校验：A4@600 → rows=6818（6818.09），Letter@600 → rows=6402（6401.57），两者都自洽。

> `DrvResolution=1200dpi` 在官方 PPD 里实际是 `[1200 600]`，
> **只有 X 轴提升，行数不变**。别按 1200 算 Y。

---

## 3. 位图压缩：标准 JBIG1

filter 符号表里躺着 `jbg_enc_init / jbg_enc_options / jbg_enc_out / jbg_enc_free /
jbg_buf_write / arith_encode / encode_sde` —— 是**开源 jbigkit 被静态链接**进来的。
所以压缩算法本身无需逆向，Linux 上直接链 `libjbig`。

实测：官方样本的 JBIG 段能被 `jbgtopbm` 直接解出，得到 `P4 5120 6818`。

### 编码参数

```c
jbg_enc_init(s, width_bits, rows, 1, rows_pointers, out_cb, &ctx);
jbg_enc_layers(s, 0);
jbg_enc_options(s, 0, 0, 32, 0, 2048);   /* order, options, l0=32, mx=0, my=2048 */
jbg_enc_out(s);
jbg_enc_free(s);
```

BIH 关键字段：`L0=32`、`MX=0`、`MY=2048`、`ORDER` 无 TPBON 位。
（`MY=2048 + 无 TPBON` 比 jbigkit 默认参数压缩率更好：1951 B vs 2628 B）

---

## 4. 内容落位（关键结论）

官方位图**只覆盖可打印区**（rows=6818 = 288.6mm），
且内容在 bitmap 中的起点与原 PDF 页坐标**逐像素一致**。
因此驱动里需把渲染图按 `margin_mm` 裁掉后再编码，才能做到页精确对位。

实测比对（墨量阈值 >25px/行）：

| | 官方 macOS 驱动 | 本驱动 |
|---|---|---|
| 首个实质内容行 | y=936 | y=936 |
| 行内首墨列 | x=102 | x=102 |
| 偏差 | — | **dx=0, dy=0** |

结论：本驱动在纸上的落位与官方驱动完全相同。
打印出来的四边留白若有不对称，属打印机硬件特性（约 4mm 物理不可打印区），
与驱动无关。

---

## 5. 未解出的部分

- **页头 [57] 校验字节**：A4=`d4`、Letter=`35`、A4@1200=`7e`。
  试过求和、异或、9 种 CRC8 多项式、含/不含压缩数据的各种范围组合，均未命中。
  **实测打印机不校验该字节**，可填任意值。
- 多页作业时 `sj` 每作业一次、`sp`/`ep` 每页一对（已由 2 页样本确认）。
- 彩色路径未逆向（本驱动走 1bit 灰度/黑白，官方 filter 会 dlopen
  `LNTHR6Zcl.dylib` 做色彩/加网）。
