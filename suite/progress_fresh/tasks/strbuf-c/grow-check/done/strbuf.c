#include "strbuf.h"
#include <stdlib.h>
#include <string.h>

void sb_init(strbuf *sb) {
    sb->data = NULL;
    sb->len = 0;
    sb->cap = 0;
}

int sb_append(strbuf *sb, const char *s) {
    size_t n = strlen(s);
    if (sb->len + n + 1 > sb->cap) {
        size_t cap = sb->cap ? sb->cap : 16;
        while (cap < sb->len + n + 1) cap *= 2;
        char *p = realloc(sb->data, cap);
        if (!p) return -1;
        sb->data = p;
        sb->cap = cap;
    }
    memcpy(sb->data + sb->len, s, n + 1);
    sb->len += n;
    return 0;
}

void sb_free(strbuf *sb) {
    free(sb->data);
    sb_init(sb);
}
