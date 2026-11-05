use strict;
use warnings;
use Test::More tests => 2;
use lib 'lib';
use LogParse qw(level_rank);

ok(level_rank("WARN") > level_rank("INFO"), "WARN outranks INFO");
is(level_rank("nope"), -1, "unknown level");
