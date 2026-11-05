const std = @import("std");
const dedup = @import("dedup.zig");

pub fn main() void {
    var a = [_]i32{ 3, 3, 1 };
    const n = dedup.dedupSorted(&a);
    std.debug.print("{d}\n", .{n});
}
