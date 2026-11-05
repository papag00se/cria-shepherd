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

pub fn contains(xs: []const i32, needle: i32) bool {
    var lo: usize = 0;
    var hi: usize = xs.len;
    while (lo < hi) {
        const mid = lo + (hi - lo) / 2;
        if (xs[mid] == needle) return true;
        if (xs[mid] < needle) lo = mid + 1 else hi = mid;
    }
    return false;
}

test "contains finds present values" {
    const a = [_]i32{ 1, 3, 5, 7 };
    try std.testing.expect(contains(&a, 5));
    try std.testing.expect(contains(&a, 1));
    try std.testing.expect(contains(&a, 7));
    try std.testing.expect(!contains(&a, 4));
}

test "contains on an empty slice" {
    const a = [_]i32{};
    try std.testing.expect(!contains(&a, 1));
}
