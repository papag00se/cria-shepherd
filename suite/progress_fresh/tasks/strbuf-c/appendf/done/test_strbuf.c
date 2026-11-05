#include <assert.h>
#include <string.h>
#include "strbuf.h"

int main(void) {
    strbuf sb;
    sb_init(&sb);
    sb_append(&sb, "ab");
    sb_append(&sb, "cd");
    assert(strcmp(sb.data, "abcd") == 0);
    sb_appendf(&sb, "-%d-%s", 42, "xy");
    assert(strcmp(sb.data, "abcd-42-xy") == 0);
    sb_free(&sb);
    return 0;
}
