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
        sb->cap = sb->len + n + 1;
        sb->data = realloc(sb->data, sb->cap);
    }
    memcpy(sb->data + sb->len, s, n + 1);
    sb->len += n;
    return 0;
}

void sb_free(strbuf *sb) {
    free(sb->data);
    sb_init(sb);
}
