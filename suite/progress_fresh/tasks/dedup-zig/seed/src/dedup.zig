const std = @import("std");

/// Removes consecutive duplicates in place and returns the new length.
pub fn dedupSorted(xs: []i32) usize {
    if (xs.len == 0) return 0;
    var w: usize = 1;
    for (xs[1..]) |x| {
        if (x != xs[w - 1]) {
            xs[w] = x;
            w += 1;
        }
    }
    return w;
}

test "dedupSorted removes neighbours" {
    var a = [_]i32{ 1, 1, 2, 3, 3 };
    const n = dedupSorted(&a);
    try std.testing.expectEqual(@as(usize, 3), n);
}
