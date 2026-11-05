#include "strbuf.h"
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <stdio.h>

void sb_init(strbuf *sb) {
    sb->data = NULL;
    sb->len = 0;
    sb->cap = 0;
}

int sb_append(strbuf *sb, const char *s) {
    size_t n = strlen(s);
    if (sb->len + n + 1 > sb->cap) {
        sb->cap = sb->len + n + 1;
        sb->data = realloc(sb->data, sb->cap);
    }
    memcpy(sb->data + sb->len, s, n + 1);
    sb->len += n;
    return 0;
}

int sb_appendf(strbuf *sb, const char *fmt, ...) {
    va_list ap, ap2;
    va_start(ap, fmt);
    va_copy(ap2, ap);
    int n = vsnprintf(NULL, 0, fmt, ap);
    va_end(ap);
    if (n < 0) { va_end(ap2); return -1; }
    char *tmp = malloc((size_t)n + 1);
    if (!tmp) { va_end(ap2); return -1; }
    vsnprintf(tmp, (size_t)n + 1, fmt, ap2);
    va_end(ap2);
    int rc = sb_append(sb, tmp);
    free(tmp);
    return rc;
}

void sb_free(strbuf *sb) {
    free(sb->data);
    sb_init(sb);
}
