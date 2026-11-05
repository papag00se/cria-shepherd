const std = @import("std");
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
    std.debug.print("\n", .{});
}
