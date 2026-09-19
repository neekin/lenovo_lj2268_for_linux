/*
 * rastertolhpl - Lenovo LJ2268 / LJ2268W LHPL 打印驱动（Linux 移植）
 *
 * 通过逆向官方 macOS 驱动 (LNTHR6Z) 得到 LHPL 协议。
 * 协议要点：
 *   1. PJL 作业头 -> @PJL ENTER LANGUAGE=LHPL
 *   2. ESC L H @ s j + 58字节参数  每作业一次
 *   3. ESC L H @ s p + 58字节页头 + JBIG数据   每页
 *   4. ESC L H @ e p + 57字节参数             每页
 *   5. ESC %-12345X @PJL EOJ
 *   压缩使用标准 JBIG1 (jbigkit)
 *
 * 编译: gcc -O2 -o rastertolhpl rastertolhpl.c /usr/lib/arm-linux-gnueabihf/libjbig.so.0
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <math.h>
#include <unistd.h>
#include <time.h>
#include <sys/stat.h>
#include <limits.h>
#include <stdint.h>
#include "jbig.h"

#define ROW_ALIGN 64

/* ---------- 纸张表 ----------
 * 官方驱动页头的纸张宽高字段由 PPD 的 PaperDimension(pt) 换算而来:
 *   595pt * 25.4/72 = 209.90mm -> 2099   (A4, 与实测一致)
 *   612pt * 25.4/72 = 215.90mm -> 2159   (Letter, 与实测一致)
 * 故此处以 pt 为准。id 由官方驱动逐型号实测得出(A4=2, Letter=1)。
 */
typedef struct { const char *name; int id; double w_pt, h_pt; } paper_t;
static paper_t papers[] = {
    {"A4",       2, 595.0, 842.0},
    {"Letter",   1, 612.0, 792.0},
    {"Legal",    3, 612.0, 1008.0},
    {"Executive",5, 522.0, 756.0},
    {"A5",       6, 420.0, 595.0},
    {"A6",       8, 297.0, 420.0},
    {"B5",       7, 499.0, 709.0},
    {NULL,0,0,0}
};
#define PT2MM(pt) ((pt) * 25.4 / 72.0)

/* ---------- 工具 ---------- */
/* 页头必须按**小端**落到字节流: LHPL 源自 x86 macOS 驱动, 打印机按小端解析。
   这里显式逐字节写入, 不依赖本机字节序和 ABI —— 在 ILP32 / LP64 / 大端机上结果一致。 */
static void put_u16_le(unsigned char *p, uint16_t v) {
    p[0] = (unsigned char)(v & 0xff);
    p[1] = (unsigned char)((v >> 8) & 0xff);
}
static void put_u32_le(unsigned char *p, uint32_t v) {
    p[0] = (unsigned char)(v & 0xff);
    p[1] = (unsigned char)((v >> 8) & 0xff);
    p[2] = (unsigned char)((v >> 16) & 0xff);
    p[3] = (unsigned char)((v >> 24) & 0xff);
}

static double envd(const char *k, double dflt) {
    const char *v = getenv(k); return v ? atof(v) : dflt;
}

/* 从 options 字符串里取 key=value */
static const char *optval(const char *opts, const char *key, char *buf, size_t n) {
    size_t klen = strlen(key);
    const char *p = opts;
    while ((p = strstr(p, key))) {
        if ((p == opts || p[-1] == ' ' || p[-1] == '\t') && p[klen] == '=') {
            const char *s = p + klen + 1;
            size_t i = 0;
            while (s[i] && s[i] != ' ' && s[i] != '\t' && i + 1 < n) i++;
            memcpy(buf, s, i); buf[i] = 0;
            return buf;
        }
        p += klen;
    }
    buf[0] = 0; return buf;
}

/* ---------- PBM 读取 ---------- */
typedef struct { int w, h, rb; unsigned char *data; } pbm_t;

static int pbm_read(const char *path, pbm_t *o) {
    FILE *f = fopen(path, "rb");
    if (!f) return -1;
    char magic[4]; int w, h;
    if (fscanf(f, "%2s %d %d", magic, &w, &h) != 3) { fclose(f); return -1; }
    if (magic[0] != 'P' || magic[1] != '4') { fclose(f); return -1; }
    int c = fgetc(f);                     /* 数字后的单个空白 */
    (void)c;
    int rb = (w + 7) / 8;
    size_t sz = (size_t)rb * h;
    unsigned char *d = malloc(sz);
    if (!d) { fclose(f); return -1; }
    if (fread(d, 1, sz, f) != sz) { free(d); fclose(f); return -1; }
    fclose(f);
    o->w = w; o->h = h; o->rb = rb; o->data = d;
    return 0;
}

/* ---------- JBIG 输出回调 ---------- */
typedef struct { unsigned char *buf; size_t len, cap; } accum_t;
static void accum_out(unsigned char *start, size_t len, void *file) {
    accum_t *a = (accum_t *)file;
    if (a->len + len > a->cap) {
        while (a->len + len > a->cap) a->cap = a->cap ? a->cap * 2 : 8192;
        a->buf = realloc(a->buf, a->cap);
    }
    memcpy(a->buf + a->len, start, len);
    a->len += len;
}

/* ---------- 主流程 ---------- */
int main(int argc, char **argv) {
    if (argc < 6) { fprintf(stderr, "用法: %s job user title copies options [file]\n", argv[0]); return 1; }
    const char *user   = argv[2];
    const char *title  = argv[3];
    const char *opts   = argv[5];
    const char *infile = (argc > 6) ? argv[6] : NULL;

    char psbuf[64], resbuf[64], mtbuf[64], mpbuf[64], dupbuf[64];
    optval(opts, "PageSize",      psbuf, sizeof psbuf);   if (!psbuf[0])  strcpy(psbuf, "A4");
    optval(opts, "DrvResolution", resbuf,sizeof resbuf);  if (!resbuf[0]) strcpy(resbuf, "600dpi");
    optval(opts, "MediaType",     mtbuf, sizeof mtbuf);
    optval(opts, "MS_MediaType",  mpbuf, sizeof mpbuf);
    optval(opts, "DrvDuplex",     dupbuf,sizeof dupbuf);

    /* 解析分辨率: 1200dpi 在官方PPD里实际是 X=1200 Y=600 */
    int xdpi = 600, ydpi = 600;
    if (strncmp(resbuf, "1200", 4) == 0) { xdpi = 1200; ydpi = 600; }
    else if (strncmp(resbuf, "300", 3) == 0) { xdpi = 300; ydpi = 300; }

    /* 查纸张 */
    paper_t P = {"A4", 2, 595.0, 842.0};
    for (int i = 0; papers[i].name; i++)
        if (strcasecmp(papers[i].name, psbuf) == 0) { P = papers[i]; break; }

    /* 几何（与官方驱动实测值完全吻合）
     * 对位模型：官方位图 row0/col0 = 可打印区起点，打印机把它放在硬件边距处。
     * 因此渲染图要先裁掉 PPD 边距(4.2mm)再送入，内容即页精确对位。
     * offx/offy 用于按实测微调（如硬件边距不对称时）。 */
    double margin_mm = envd("LHPL_MARGIN_MM", 4.1998);      /* 不可打印边距, 单侧 */
    double offx_mm   = envd("LHPL_OFFSET_X_MM", 0.0);       /* 标定用横向微调 */
    double offy_mm   = envd("LHPL_OFFSET_Y_MM", 0.0);       /* 标定用纵向微调 */

    double pw_mm = PT2MM(P.w_pt), ph_mm = PT2MM(P.h_pt);
    double im_h_mm = ph_mm - 2.0 * margin_mm;
    int rows      = (int)lround(im_h_mm / 25.4 * ydpi);   /* A4->6818, Letter->6402, 与官方一致 */
    long full_w_px = (long)ceil(pw_mm / 25.4 * xdpi);
    int  row_bytes = (int)(((full_w_px + 7) / 8 + ROW_ALIGN - 1) / ROW_ALIGN) * ROW_ALIGN;
    int  width_bits = row_bytes * 8;

    int crop_x = (int)lround((margin_mm + offx_mm) / 25.4 * xdpi);
    int crop_y = (int)lround((margin_mm + offy_mm) / 25.4 * ydpi);

    fprintf(stderr, "DEBUG: paper=%s id=%d %.1fx%.1fmm  dpi=%dx%d  rows=%d row_bytes=%d width_bits=%d crop=(%d,%d)\n",
            P.name, P.id, pw_mm, ph_mm, xdpi, ydpi, rows, row_bytes, width_bits, crop_x, crop_y);

    /* 渲染 PDF -> PBM (mono) */
    char tmpdir[] = "/tmp/lhplXXXXXX";
    if (!mkdtemp(tmpdir)) { perror("mkdtemp"); return 1; }

    const char *src = infile ? infile : "/dev/stdin";
    char real_src[PATH_MAX];
    if (!infile) {                       /* 标准输入先落盘, 因为 pdftoppm 需要文件名 */
        snprintf(real_src, sizeof real_src, "%s/in.pdf", tmpdir);
        FILE *inf = fopen(real_src, "wb"); FILE *sin = stdin;
        if (!inf) return 1;
        char b[65536]; size_t n;
        while ((n = fread(b, 1, sizeof b, sin)) > 0) fwrite(b, 1, n, inf);
        fclose(inf);
    } else snprintf(real_src, sizeof real_src, "%s", infile);

    char cmd[1024];
    snprintf(cmd, sizeof cmd, "pdftoppm -rx %d -ry %d -mono '%s' %s/pg 2>/dev/null",
             xdpi, ydpi, real_src, tmpdir);
    if (system(cmd) != 0) fprintf(stderr, "WARN: pdftoppm 执行异常\n");

    /* PJL 作业头 */
    char host[256] = "unknown"; if (gethostname(host, sizeof host)) strcpy(host, "unknown");
    time_t t0 = time(NULL); struct tm tm0; localtime_r(&t0, &tm0);
    char date[16], tim[16];
    strftime(date, sizeof date, "%m/%d/%Y", &tm0);
    strftime(tim,  sizeof tim,  "%H:%M:%S", &tm0);

    printf("\033%%-12345X@PJL JOB NAME=PRINTER\r\n");
    printf("@PJL SET JOBATTR=HST:%s\r\n", host);
    printf("@PJL SET JOBATTR=USR:%s\r\n", user);
    printf("@PJL SET JOBATTR=DOC:%s\r\n", title);
    printf("@PJL SET JOBATTR=DATE:%s\r\n", date);
    printf("@PJL SET JOBATTR=TIME:%s\r\n", tim);
    printf("@PJL SET DUPLEX=OFF\r\n");
    printf("@PJL SET MEDIASOURCE=0\r\n");
    printf("@PJL SET RENDERMODE=GRAYSCALE\r\n");
    printf("@PJL SET RESOLUTION=%d\r\n", xdpi);
    printf("@PJL SET BITSPERPIXEL=1\r\n");
    printf("@PJL SET COPIES=1\r\n");
    printf("@PJL ENTER LANGUAGE=LHPL\r\n");

    /* sj 块: 58 字节参数 (官方样本: 01 00 01 00 ... 00 46) */
    {
        unsigned char sj[58]; memset(sj, 0, sizeof sj);
        sj[0] = 0x01; sj[2] = 0x01; sj[57] = 0x46;
        fwrite("\033LH@sj", 1, 6, stdout); fwrite(sj, 1, sizeof sj, stdout);
    }

    /* 逐页处理 */
    char **rowp = calloc(rows > 0 ? rows : 1, sizeof(char *));
    unsigned char *pagebuf = calloc((size_t)row_bytes * (rows > 0 ? rows : 1), 1);

    int npages = 0;
    for (int pi = 1; ; pi++) {
        char path[PATH_MAX];
        snprintf(path, sizeof path, "%s/pg-%d.pbm", tmpdir, pi);
        struct stat st;
        if (stat(path, &st) != 0) {           /* 兼容 pg-01.pbm 命名 */
            snprintf(path, sizeof path, "%s/pg-%02d.pbm", tmpdir, pi);
            if (stat(path, &st) != 0) break;
        }

        pbm_t pm;
        if (pbm_read(path, &pm) != 0) { fprintf(stderr, "SKIP unreadable %s\n", path); break; }

        /* 组装可打印位图 */
        memset(pagebuf, 0, (size_t)row_bytes * rows);
        int copy_bytes = row_bytes * 8 < (crop_x > 0 ? pm.w - crop_x : pm.w) ? row_bytes : pm.rb;
        if (copy_bytes > pm.rb) copy_bytes = pm.rb;
        if (copy_bytes > row_bytes) copy_bytes = row_bytes;
        int avail_rows = pm.h - crop_y;
        int n = rows < avail_rows ? rows : avail_rows;
        for (int r = 0; r < n; r++) {
            unsigned char *dst = pagebuf + (size_t)r * row_bytes;
            unsigned char *src = pm.data + (size_t)(r + crop_y) * pm.rb;
            if (crop_x > 0) {
                long srcbit = crop_x, dstbit = 0;   /* 位级拷贝 */
                long cnt = (pm.w - crop_x) < width_bits ? (pm.w - crop_x) : width_bits;
                for (long i = 0; i < cnt; i++, srcbit++, dstbit++) {
                    int bit = (src[srcbit >> 3] >> (7 - (srcbit & 7))) & 1;
                    dst[dstbit >> 3] |= bit << (7 - (dstbit & 7));
                }
            } else {
                memcpy(dst, src, copy_bytes);
            }
        }
        free(pm.data);

        for (int r = 0; r < rows; r++) rowp[r] = (char *)(pagebuf + (size_t)r * row_bytes);

        /* JBIG 压缩 */
        accum_t acc = {NULL, 0, 0};
        struct jbg_enc_state *s = malloc(sizeof(struct jbg_enc_state));
        jbg_enc_init(s, width_bits, rows, 1, (unsigned char **)rowp, accum_out, &acc);
        jbg_enc_layers(s, 0);
        jbg_enc_options(s, 0, 0, 32, 0, 2048);     /* order, options, l0, mx, my */
        jbg_enc_out(s);
        jbg_enc_free(s);
        free(s);

        /* sp 块 */
        unsigned char hdr[58]; memset(hdr, 0, sizeof hdr);
        hdr[0] = (unsigned char)(P.id & 0xff);
        hdr[1] = 0x01;
        put_u32_le(hdr + 2,  (uint32_t)width_bits);
        put_u32_le(hdr + 6,  (uint32_t)rows);
        put_u32_le(hdr + 10, (uint32_t)((size_t)row_bytes * rows));
        put_u32_le(hdr + 14, (uint32_t)acc.len);
        put_u32_le(hdr + 18, (uint32_t)acc.len);   /* 官方页头里重复一次长度 */
        put_u16_le(hdr + 36, (uint16_t)xdpi);                /* [36:38] X 分辨率 */
        put_u16_le(hdr + 38, (uint16_t)lround(pw_mm * 10));  /* [38:40] 纸宽 0.1mm */
        put_u16_le(hdr + 40, (uint16_t)lround(ph_mm * 10));  /* [40:42] 纸高 0.1mm */
        unsigned char sum = 0;
        for (int i = 0; i < 57; i++) sum += hdr[i];
        hdr[57] = sum;                            /* 校验和(待实测确认) */

        fwrite("\033LH@sp", 1, 6, stdout);
        fwrite(hdr, 1, sizeof hdr, stdout);
        if (acc.len) fwrite(acc.buf, 1, acc.len, stdout);
        free(acc.buf);

        /* ep 块: 官方样本为统计摘要, 先用零填充 + 尾标记 */
        {
            unsigned char ep[57]; memset(ep, 0, sizeof ep);
            fwrite("\033LH@ep", 1, 6, stdout);
            fwrite(ep, 1, sizeof ep, stdout);
        }
        npages++;
        if (pi > 999) break;
    }

    if (npages == 0) fprintf(stderr, "ERROR: 没有产生任何页面\n");

    printf("\033%%-12345X@PJL EOJ\r\n");
    fflush(stdout);

    snprintf(cmd, sizeof cmd, "rm -rf %s", tmpdir);
    system(cmd);
    return 0;
}
