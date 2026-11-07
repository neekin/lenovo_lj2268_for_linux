/* SPDX-License-Identifier: MIT
 * Native equivalent of rastertolkpl (Python reference).
 * Input is the SAME uncompressed CUPS raster, not a separate PDF render path.
 * JBIG-KIT sources linked into this executable retain GPL-2.0-or-later.
 */
#define _POSIX_C_SOURCE 200809L
#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/utsname.h>
#include <time.h>
#include "jbig.h"
#include "protocol_tables.h"

typedef struct {
    uint32_t w, h, bpp, bpl, pw, ph;
    const unsigned char *data;
} page;
typedef struct { unsigned char *data; size_t len, cap; int failed; } buffer;

static void die(const char *message) {
    fprintf(stderr, "rastertolkpl-c: %s\n", message);
    exit(1);
}
static uint32_t get32(const unsigned char *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static void put16(unsigned char *p, uint32_t n) {
    p[0] = (unsigned char)n; p[1] = (unsigned char)(n >> 8);
}
static void put32(unsigned char *p, uint32_t n) {
    put16(p, n); put16(p + 2, n >> 16);
}
static int equals(const char *a, const char *b) { return a && !strcmp(a, b); }
static void write_all(const void *data, size_t size) {
    if (fwrite(data, 1, size, stdout) != size) die("cannot write output");
}
static void write_frame(const char *command, const unsigned char *payload) {
    unsigned char out[64];
    memcpy(out, command, 6); memcpy(out + 6, payload, 58);
    out[63] = 0;
    for (size_t i = 0; i < 63; ++i) out[63] ^= out[i];
    write_all(out, sizeof out);
}
static unsigned char *read_input(FILE *file, size_t *length) {
    buffer b = {NULL, 0, 0, 0};
    for (;;) {
        if (b.cap - b.len < 65536) {
            if (b.cap > SIZE_MAX / 2) die("input is too large");
            size_t cap = b.cap ? b.cap * 2 : 65536;
            void *next = realloc(b.data, cap);
            if (!next) { free(b.data); die("cannot allocate input buffer"); }
            b.data = next; b.cap = cap;
        }
        size_t n = fread(b.data + b.len, 1, b.cap - b.len, file);
        b.len += n;
        if (!n) {
            if (ferror(file)) { free(b.data); die("cannot read raster input"); }
            break;
        }
    }
    *length = b.len;
    return b.data;
}
static int header(const unsigned char *input, size_t length, size_t pos,
                  size_t size, unsigned shift, page *p) {
    if (pos > length || size > length - pos) return 0;
    const unsigned char *h = input + pos;
    p->w = get32(h + 0x178 - shift); p->h = get32(h + 0x17c - shift);
    p->bpp = get32(h + 0x188 - shift); p->bpl = get32(h + 0x18c - shift);
    p->pw = get32(h + 0x164 - shift); p->ph = get32(h + 0x168 - shift);
    if (!p->w || !p->h || !p->bpl || p->h > (length - pos - size) / p->bpl) return 0;
    p->data = h + size;
    return 1;
}
static page *parse_pages(const unsigned char *input, size_t length, size_t *count) {
    static const size_t sizes[] = {1800, 1796, 1792, 1804, 1816, 1784, 1768, 1832};
    size_t pos = 0, used = 0, capacity = 0;
    page *pages = NULL, p;
    while (pos <= length && length - pos >= 0x190) {
        size_t hsize = 0;
        if (!used) {
            if (memcmp(input + pos, "3SaR", 4)) { ++pos; continue; }
            if (!header(input, length, pos, 1800, 0, &p)) break;
            size_t pixels = (size_t)p.bpl * p.h;
            hsize = 1800;
            for (size_t i = 0; i < sizeof sizes / sizeof sizes[0]; ++i) {
                size_t s = sizes[i];
                if (s > length - pos || pixels > length - pos - s) continue;
                size_t end = pos + s + pixels;
                if (end == length || (length - end >= 4 && !memcmp(input + end, "3SaR", 4))) {
                    hsize = s; break;
                }
            }
            p.data = input + pos + hsize;
        } else if (header(input, length, pos, 1796, 4, &p)) {
            hsize = 1796;
        } else if (!memcmp(input + pos, "3SaR", 4) && header(input, length, pos, 1800, 0, &p)) {
            hsize = 1800;
        } else {
            /* Unlike the legacy parser, do not silently print an incomplete job. */
            free(pages); die("incomplete or invalid subsequent raster page");
        }
        if (p.w > 65024 || p.h > 65535 ||
            !(p.bpp == 1 || p.bpp == 8 || p.bpp == 24 || p.bpp == 32) ||
            (uint64_t)p.w * p.bpp > (uint64_t)p.bpl * 8) {
            free(pages); die("unsupported raster geometry, pixel format or row length");
        }
        if (used == capacity) {
            if (capacity > SIZE_MAX / 2 / sizeof(page)) { free(pages); die("too many pages"); }
            capacity = capacity ? capacity * 2 : 8;
            void *next = realloc(pages, capacity * sizeof(page));
            if (!next) { free(pages); die("cannot allocate page metadata"); }
            pages = next;
        }
        pages[used++] = p;
        pos += hsize + (size_t)p.bpl * p.h;
    }
    if (!used) { free(pages); die("no complete raster pages found"); }
    /* A complete input ends immediately after its last page. */
    if (pos != length) { free(pages); die("unparsed trailing or truncated raster data"); }
    *count = used;
    return pages;
}
static int64_t integer(const char *text, const char *error) {
    char *end;
    errno = 0;
    intmax_t value = strtoimax(text, &end, 10);
    if (end == text || errno) die(error);
    while (isspace((unsigned char)*end)) ++end;
    if (*end || value < INT64_MIN || value > INT64_MAX) die(error);
    return (int64_t)value;
}
static unsigned char *bitmap(const page *p, int threshold, int dither, size_t *length) {
    static const int bayer[4][4] = {{0,8,2,10},{12,4,14,6},{3,11,1,9},{15,7,13,5}};
    size_t srcrow = (p->w + 7) / 8;
    size_t outrow = ((p->w + 511) / 512) * 64;
    if (p->h > SIZE_MAX / outrow) die("bitmap size overflow");
    *length = outrow * p->h;
    unsigned char *bits = calloc(*length, 1);
    if (!bits) die("cannot allocate bitmap");
    for (uint32_t y = 0; y < p->h; ++y) {
        unsigned char *out = bits + outrow * y;
        if (p->bpp == 1) {
            /* Preserve the Python reference's packed 1bpp semantics exactly. */
            memcpy(out, p->data + srcrow * y, srcrow);
            continue;
        }
        const unsigned char *in = p->data + (size_t)p->bpl * y;
        if (p->bpp == 8 && !dither) {
            for (uint32_t x = 0; x < p->w; ++x)
                if (in[x] < threshold) out[x >> 3] |= (unsigned char)(0x80 >> (x & 7));
        } else if (p->bpp >= 24) {
            unsigned channels = p->bpp / 8;
            for (uint32_t x = 0; x < p->w; ++x) {
                size_t i = (size_t)x * channels;
                int gray = (in[i] * 299 + in[i + 1] * 587 + in[i + 2] * 114) / 1000;
                if (gray < threshold) out[x >> 3] |= (unsigned char)(0x80 >> (x & 7));
            }
        } else {
            for (uint32_t x = 0; x < p->w; ++x)
                if (in[x] < threshold + bayer[y & 3][x & 3] - 8)
                    out[x >> 3] |= (unsigned char)(0x80 >> (x & 7));
        }
    }
    return bits;
}
/* Signed physical horizontal calibration: negative moves ink left.
 * Shift the packed monochrome pixels, preserving geometry and blank padding.
 * With no calibration requested the reference path remains byte-identical.
 */
static void shift_bitmap(unsigned char *bits, const page *p, int dots) {
    if (!dots) return;
    uint32_t count = (uint32_t)(dots < 0 ? -dots : dots);
    size_t stride = ((p->w + 511) / 512) * 64;
    if (count >= p->w) {
        memset(bits, 0, stride * p->h);
        return;
    }
    size_t bytes = (p->w + 7) / 8, whole = count / 8;
    unsigned fraction = count & 7;
    unsigned char tailmask = p->w & 7 ? (unsigned char)(0xff << (8 - (p->w & 7))) : 0xff;
    for (uint32_t y = 0; y < p->h; ++y) {
        unsigned char *row = bits + stride * y;
        row[bytes - 1] &= tailmask;
        if (dots < 0) {
            for (size_t x = 0; x < bytes; ++x) {
                size_t from = x + whole;
                unsigned value = from < bytes ? (unsigned)row[from] << fraction : 0;
                if (fraction && from + 1 < bytes) value |= row[from + 1] >> (8 - fraction);
                row[x] = (unsigned char)value;
            }
        } else {
            for (size_t x = bytes; x-- > 0;) {
                unsigned value = 0;
                if (x >= whole) {
                    size_t from = x - whole;
                    value = row[from] >> fraction;
                    if (fraction && from) value |= (unsigned)row[from - 1] << (8 - fraction);
                }
                row[x] = (unsigned char)value;
            }
        }
        row[bytes - 1] &= tailmask;
        memset(row + bytes, 0, stride - bytes);
    }
}
static void collect(unsigned char *data, size_t length, void *opaque) {
    buffer *b = opaque;
    if (b->failed) return;
    if (length > SIZE_MAX - b->len) { b->failed = 1; return; }
    size_t need = b->len + length;
    if (need > b->cap) {
        size_t cap = b->cap ? b->cap : 8192;
        while (cap < need) {
            if (cap > SIZE_MAX / 2) { cap = need; break; }
            cap *= 2;
        }
        void *next = realloc(b->data, cap);
        if (!next) { b->failed = 1; return; }
        b->data = next; b->cap = cap;
    }
    memcpy(b->data + b->len, data, length); b->len += length;
}
static uint64_t distance(uint32_t a, uint32_t b) { return a > b ? (uint64_t)a - b : (uint64_t)b - a; }
static const unsigned char *paper_for(const page *p) {
    size_t best = 0;
    uint64_t score = UINT64_MAX;
    for (size_t i = 0; i < sizeof PAPERS / sizeof PAPERS[0]; ++i) {
        uint64_t dx = distance(PAPERS[i].pw, p->pw), dy = distance(PAPERS[i].ph, p->ph);
        uint64_t rx = distance(PAPERS[i].pw, p->ph), ry = distance(PAPERS[i].ph, p->pw);
        if ((dx <= 2 && dy <= 2) || (rx <= 2 && ry <= 2)) { best = i; break; }
        uint64_t d = dx + dy < rx + ry ? dx + dy : rx + ry;
        if (d < score) { best = i; score = d; }
    }
    if (PAPERS[best].length != 58) die("16K reference template has an invalid length; choose a verified paper size such as A4");
    return PAPERS[best].data;
}
static void page_end(unsigned char *out) {
    memcpy(out, EP_PAYLOAD, 58);
    const char *hex = getenv("LHPL_EP_HEX");
    if (!hex || !*hex) return;
    unsigned used = 0;
    while (*hex) {
        while (isspace((unsigned char)*hex)) ++hex;
        if (!*hex) break;
        int value = 0;
        for (unsigned i = 0; i < 2; ++i) {
            unsigned char c = (unsigned char)*hex++;
            if (c >= '0' && c <= '9') value = value * 16 + c - '0';
            else if (c >= 'a' && c <= 'f') value = value * 16 + c - 'a' + 10;
            else if (c >= 'A' && c <= 'F') value = value * 16 + c - 'A' + 10;
            else die("LHPL_EP_HEX must contain exactly 58 hexadecimal bytes");
        }
        if (used >= 58) die("LHPL_EP_HEX is too long");
        out[used++] = (unsigned char)value;
    }
    if (used != 58) die("LHPL_EP_HEX must contain exactly 58 bytes");
}
static uint64_t copies(const char *text) {
    if (!*text || strspn(text, "0123456789") != strlen(text)) return 1;
    char *end; errno = 0;
    unsigned long long n = strtoull(text, &end, 10);
    if (errno || *end) die("copies value is too large");
    return n ? (uint64_t)n : 1;
}
int main(int argc, char **argv) {
    if (argc < 6) die("usage: rastertolkpl-c job-id user title copies options [file]");
    int threshold = 128;
    const char *setting = getenv("LHPL_THRESHOLD");
    if (setting) {
        int64_t n = integer(setting, "invalid LHPL_THRESHOLD");
        if (n < 0 || n > 255) die("LHPL_THRESHOLD must be between 0 and 255");
        threshold = (int)n;
    }
    int dither = equals(getenv("LHPL_DITHER"), "1");
    int x_shift = 0;
    setting = getenv("LHPL_X_SHIFT_DOTS");
    if (setting) {
        int64_t n = integer(setting, "invalid LHPL_X_SHIFT_DOTS");
        if (n < -6000 || n > 6000) die("LHPL_X_SHIFT_DOTS must be between -6000 and 6000");
        x_shift = (int)n;
    }
    uint64_t ncopies = copies(argv[4]);
    unsigned char ep[58]; page_end(ep);
    FILE *file = stdin;
    if (argc >= 7 && strcmp(argv[6], "-")) {
        file = fopen(argv[6], "rb");
        if (!file) die("cannot open raster file");
    }
    size_t input_length, count;
    unsigned char *input = read_input(file, &input_length);
    if (file != stdin) fclose(file);
    page *pages = parse_pages(input, input_length, &count);
    for (size_t i = 0; i < count; ++i) (void)paper_for(&pages[i]);
    if (x_shift) fprintf(stderr, "INFO: LHPL horizontal calibration: %d dots at 600 dpi (%.3f mm)\n",
                         x_shift, x_shift * 25.4 / 600.0);
    struct utsname host;
    if (uname(&host)) die("cannot determine hostname");
    time_t timestamp = time(NULL);
    const char *epoch = getenv("LHPL_JOB_EPOCH");
    if (epoch) {
        int64_t n = integer(epoch, "invalid LHPL_JOB_EPOCH");
        timestamp = (time_t)n;
        if ((int64_t)timestamp != n) die("LHPL_JOB_EPOCH is out of range");
    }
    struct tm tm;
    if (!localtime_r(&timestamp, &tm)) die("cannot determine job time");
    printf("\033%%-12345X@PJL JOB NAME=PRINTER\r\n"
           "@PJL SET JOBATTR=HST:%s\r\n@PJL SET JOBATTR=USR:%s\r\n"
           "@PJL SET JOBATTR=DOC:%s\r\n@PJL SET JOBATTR=DATE:%02d/%02d/%04d\r\n"
           "@PJL SET JOBATTR=TIME:%02d:%02d:%02d\r\n"
           "@PJL SET DUPLEX=OFF\r\n@PJL SET MEDIASOURCE=0\r\n"
           "@PJL SET RENDERMODE=GRAYSCALE\r\n@PJL SET RESOLUTION=600\r\n"
           "@PJL SET BITSPERPIXEL=1\r\n@PJL SET COPIES=%" PRIu64 "\r\n"
           "@PJL ENTER LANGUAGE=LHPL\r\n",
           host.nodename, argv[2], argv[3], tm.tm_mon + 1, tm.tm_mday, tm.tm_year + 1900,
           tm.tm_hour, tm.tm_min, tm.tm_sec, ncopies);
    write_frame("\033LH@sj", SJ_PAYLOAD);
    for (size_t i = 0; i < count; ++i) {
        const page *p = &pages[i];
        size_t bitmap_length;
        unsigned char *bits = bitmap(p, threshold, dither, &bitmap_length);
        (void)bitmap_length;
        shift_bitmap(bits, p, x_shift);
        unsigned char *planes[1] = {bits};
        struct jbg_enc_state encoder;
        buffer compressed = {NULL, 0, 0, 0};
        uint32_t width = ((p->w + 511) / 512) * 512;
        jbg_enc_init(&encoder, width, p->h, 1, planes, collect, &compressed);
        jbg_enc_options(&encoder, 0, JBG_LRLTWO | JBG_SDRST, 128, 0, 0);
        jbg_enc_out(&encoder);
        jbg_enc_free(&encoder);
        free(bits);
        if (compressed.failed || compressed.len > UINT32_MAX) {
            free(compressed.data); die("cannot encode JBIG image");
        }
        unsigned char sp[58]; memcpy(sp, paper_for(p), 58);
        put16(sp + 2, width); put16(sp + 6, p->h);
        put32(sp + 0x0a, (width / 8) * p->h);
        put32(sp + 0x0e, (uint32_t)compressed.len);
        put32(sp + 0x12, (uint32_t)compressed.len);
        write_frame("\033LH@sp", sp);
        write_all(compressed.data, compressed.len);
        free(compressed.data);
        write_frame("\033LH@ep", ep);
    }
    write_all("\033%-12345X@PJL EOJ\r\n", 19);
    free(pages); free(input);
    if (fflush(stdout) || ferror(stdout)) die("cannot finish output");
    return 0;
}
