from suite.progress_fresh.dsl import ed

SEED = {
"strbuf.h": '''#ifndef STRBUF_H
#define STRBUF_H
#include <stddef.h>

typedef struct {
    char *data;
    size_t len;
    size_t cap;
} strbuf;

void sb_init(strbuf *sb);
int sb_append(strbuf *sb, const char *s);
void sb_free(strbuf *sb);

#endif
''',
"strbuf.c": '''#include "strbuf.h"
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
''',
"test_strbuf.c": '''#include <assert.h>
#include <string.h>
#include "strbuf.h"

int main(void) {
    strbuf sb;
    sb_init(&sb);
    sb_append(&sb, "ab");
    sb_append(&sb, "cd");
    assert(strcmp(sb.data, "abcd") == 0);
    sb_free(&sb);
    return 0;
}
''',
"Makefile": "test: test_strbuf\n\t./test_strbuf\n\ntest_strbuf: test_strbuf.c strbuf.c strbuf.h\n\tcc -Wall -o test_strbuf test_strbuf.c strbuf.c\n",
}
H = SEED["strbuf.h"]
C = SEED["strbuf.c"]
T = SEED["test_strbuf.c"]
GROW_OLD = '''        sb->cap = sb->len + n + 1;
        sb->data = realloc(sb->data, sb->cap);
    }'''
GROW_NEW = '''        size_t cap = sb->cap ? sb->cap : 16;
        while (cap < sb->len + n + 1) cap *= 2;
        char *p = realloc(sb->data, cap);
        if (!p) return -1;
        sb->data = p;
        sb->cap = cap;
    }'''
TASK = dict(extension=True, name="strbuf-c", language="C", seed=SEED,
unrelated={"Makefile": SEED["Makefile"] + "\nclean:\n\trm -f test_strbuf\n"},
reqs=[
dict(id="grow-check", text="sb_append calls realloc without checking for failure and reallocates on every append. Grow the capacity geometrically (doubling from 16), and on allocation failure return -1 leaving the buffer unchanged.",
 partial={"strbuf.c": ed(C, (GROW_OLD, '''        size_t cap = sb->cap ? sb->cap : 16;
        while (cap < sb->len + n + 1) cap *= 2;
        sb->data = realloc(sb->data, cap);
        sb->cap = cap;
    }'''))},
 done={"strbuf.c": ed(C, (GROW_OLD, GROW_NEW))}),
dict(id="appendf", text="Add sb_appendf(strbuf *sb, const char *fmt, ...) printf-style appending, declared in strbuf.h, returning -1 on failure, with a test that formats an integer and a string.", ns=True,
 partial={"strbuf.h": ed(H, ("void sb_free", "int sb_appendf(strbuf *sb, const char *fmt, ...);\nvoid sb_free")),
          "strbuf.c": ed(C, ("#include <string.h>\n", "#include <string.h>\n#include <stdarg.h>\n#include <stdio.h>\n"), ("void sb_free", '''int sb_appendf(strbuf *sb, const char *fmt, ...) {
    char tmp[256];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(tmp, sizeof tmp, fmt, ap);
    va_end(ap);
    return sb_append(sb, tmp);
}

void sb_free'''))},
 done={"strbuf.h": ed(H, ("void sb_free", "int sb_appendf(strbuf *sb, const char *fmt, ...);\nvoid sb_free")),
       "strbuf.c": ed(C, ("#include <string.h>\n", "#include <string.h>\n#include <stdarg.h>\n#include <stdio.h>\n"), ("void sb_free", '''int sb_appendf(strbuf *sb, const char *fmt, ...) {
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

void sb_free''')),
       "test_strbuf.c": ed(T, ("    sb_free(&sb);\n    return 0;", '''    sb_appendf(&sb, "-%d-%s", 42, "xy");
    assert(strcmp(sb.data, "abcd-42-xy") == 0);
    sb_free(&sb);
    return 0;'''))}),
dict(id="clear-reserve", text="Add sb_clear (empties the buffer but keeps its allocation, data stays a valid empty string) and declare it in strbuf.h; add a test that appends after clearing.",
 partial={"strbuf.h": ed(H, ("void sb_free", "void sb_clear(strbuf *sb);\nvoid sb_free")),
          "strbuf.c": ed(C, ("void sb_free", "void sb_clear(strbuf *sb) {\n    sb->len = 0;\n    if (sb->data) sb->data[0] = '\\0';\n}\n\nvoid sb_free")),
          "test_strbuf.c": ed(T, ("    sb_free(&sb);\n    return 0;", '''    sb_clear(&sb);
    assert(sb.len == 0);
    sb_free(&sb);
    return 0;'''))},
 done={"strbuf.h": ed(H, ("void sb_free", "void sb_clear(strbuf *sb);\nvoid sb_free")),
       "strbuf.c": ed(C, ("void sb_free", "void sb_clear(strbuf *sb) {\n    sb->len = 0;\n    if (sb->data) sb->data[0] = '\\0';\n}\n\nvoid sb_free")),
       "test_strbuf.c": ed(T, ("    sb_free(&sb);\n    return 0;", '''    sb_clear(&sb);
    assert(sb.len == 0 && strcmp(sb.data, "") == 0);
    sb_append(&sb, "z");
    assert(strcmp(sb.data, "z") == 0);
    sb_free(&sb);
    return 0;'''))}),
])
