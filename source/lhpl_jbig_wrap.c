/* 简化的 jbigkit 编码器包装：供 Python ctypes 进程内调用 */
#include <stddef.h>
#include "jbig.h"

size_t lhpl_jbig_sizeof(void)
{
    return sizeof(struct jbg_enc_state);
}

int lhpl_jbig_encode(void *state, unsigned long x, unsigned long y,
                     unsigned char *bitmap, long l0, int options,
                     int order, int mx, int my,
                     void (*cb)(unsigned char *, size_t, void *),
                     void *user)
{
    struct jbg_enc_state *s = (struct jbg_enc_state *)state;
    unsigned char *planes[1];
    planes[0] = bitmap;
    jbg_enc_init(s, x, y, 1, planes, cb, user);
    jbg_enc_options(s, order, options, l0, mx, my);
    jbg_enc_out(s);
    return (int)s->stripes;
}
