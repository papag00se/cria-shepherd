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

pub fn dedupAny(xs: []i32) usize {
    var w: usize = 0;
    for (xs) |x| {
        var seen = false;
        for (xs[0..w]) |y| {
            if (y == x) seen = true;
        }
        if (!seen) {
            xs[w] = x;
            w += 1;
        }
    }
    return w;
}

test "dedupAny keeps first occurrences in order" {
    var a = [_]i32{ 3, 1, 3, 2, 1 };
    const n = dedupAny(&a);
    try std.testing.expectEqualSlices(i32, &[_]i32{ 3, 1, 2 }, a[0..n]);
}
