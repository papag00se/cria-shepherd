from suite.progress_fresh.dsl import ed

SEED = {
"src/dedup.zig": '''const std = @import("std");

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
''',
"src/main.zig": '''const std = @import("std");
const dedup = @import("dedup.zig");

pub fn main() void {
    var a = [_]i32{ 3, 3, 1 };
    const n = dedup.dedupSorted(&a);
    std.debug.print("{d}\\n", .{n});
}
''',
"build.zig": 'const std = @import("std");\n\npub fn build(b: *std.Build) void {\n    _ = b;\n}\n',
}
D = SEED["src/dedup.zig"]
M = SEED["src/main.zig"]
CTN = '''
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
'''
TASK = dict(extension=True, name="dedup-zig", language="Zig", seed=SEED,
unrelated={"src/main.zig": M.replace("pub fn main", "// demo entry point\npub fn main")},
reqs=[
dict(id="non-adjacent", text="dedupSorted only removes neighbours, so unsorted input keeps duplicates. Add dedupAny(xs) that removes all duplicates (keeping first occurrences, in order) in place and returns the new length, with a test using unsorted input.",
 partial={"src/dedup.zig": D + '''
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
'''},
 done={"src/dedup.zig": D + '''
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
'''}),
dict(id="binary-search", text="Add contains(xs, needle) doing a binary search over a sorted slice (it must work for empty slices) and test hits, misses and the empty case.",
 partial={"src/dedup.zig": D + CTN + '''
test "contains finds present values" {
    const a = [_]i32{ 1, 3, 5, 7 };
    try std.testing.expect(contains(&a, 5));
    try std.testing.expect(!contains(&a, 4));
}
'''},
 done={"src/dedup.zig": D + CTN + '''
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
'''}),
dict(id="cli-use", text="Make main read integers from the command line arguments, dedupe them with dedupSorted and print the surviving values space-separated instead of the hardcoded demo array.",
 partial={"src/main.zig": '''const std = @import("std");
const dedup = @import("dedup.zig");

pub fn main() !void {
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa.deinit();
    const alloc = gpa.allocator();
    const args = try std.process.argsAlloc(alloc);
    defer std.process.argsFree(alloc, args);
    var nums = try alloc.alloc(i32, args.len - 1);
    defer alloc.free(nums);
    for (args[1..], 0..) |a, i| nums[i] = try std.fmt.parseInt(i32, a, 10);
    _ = dedup.dedupSorted(nums);
    for (nums) |x| std.debug.print("{d} ", .{x});
    std.debug.print("\\n", .{});
}
'''},
 done={"src/main.zig": '''const std = @import("std");
const dedup = @import("dedup.zig");

pub fn main() !void {
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa.deinit();
    const alloc = gpa.allocator();
    const args = try std.process.argsAlloc(alloc);
    defer std.process.argsFree(alloc, args);
    var nums = try alloc.alloc(i32, args.len - 1);
    defer alloc.free(nums);
    for (args[1..], 0..) |a, i| nums[i] = try std.fmt.parseInt(i32, a, 10);
    const n = dedup.dedupSorted(nums);
    for (nums[0..n]) |x| std.debug.print("{d} ", .{x});
    std.debug.print("\\n", .{});
}
'''}),
])
