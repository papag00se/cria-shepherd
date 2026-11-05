use strict;
use warnings;
use Test::More tests => 2;
use lib 'lib';
use LogParse qw(parse_line);

is_deeply(parse_line("10:00 INFO started"), { time => "10:00", level => "INFO", msg => "started" }, "parses a line");
is(parse_line("10:01 warn careful")->{level}, "WARN", "level is upper-cased");
