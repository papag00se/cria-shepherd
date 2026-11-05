#include <assert.h>
#include <string.h>
#include "strbuf.h"

int main(void) {
    strbuf sb;
    sb_init(&sb);
    sb_append(&sb, "ab");
    sb_append(&sb, "cd");
    assert(strcmp(sb.data, "abcd") == 0);
    sb_clear(&sb);
    assert(sb.len == 0);
    sb_free(&sb);
    return 0;
}
