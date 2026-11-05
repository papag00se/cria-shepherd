from suite.progress_fresh.dsl import ed

SEED = {
"lib/LogParse.pm": '''package LogParse;
use strict;
use warnings;
use Exporter 'import';
our @EXPORT_OK = qw(parse_line);

sub parse_line {
    my ($line) = @_;
    if ($line =~ /^(\\S+) (\\w+) (.*)$/) {
        return { time => $1, level => $2, msg => $3 };
    }
    return;
}

1;
''',
"t/parse.t": '''use strict;
use warnings;
use Test::More tests => 1;
use lib 'lib';
use LogParse qw(parse_line);

is_deeply(parse_line("10:00 INFO started"), { time => "10:00", level => "INFO", msg => "started" }, "parses a line");
''',
"bin/summary.pl": '''#!/usr/bin/perl
use strict;
use warnings;
use lib 'lib';
use LogParse qw(parse_line);

my %count;
while (my $line = <STDIN>) {
    chomp $line;
    my $e = parse_line($line) or next;
    $count{ $e->{level} }++;
}
print "$_ $count{$_}\\n" for sort keys %count;
''',
}
L = SEED["lib/LogParse.pm"]
T = SEED["t/parse.t"]
S = SEED["bin/summary.pl"]
TASK = dict(extension=True, name="logparse-pl", language="Perl", seed=SEED,
unrelated={"bin/summary.pl": S.replace("my %count;", "# tally log lines per level\nmy %count;")},
reqs=[
dict(id="level-upper", text="Normalize the level to upper case in parse_line (\"warn\" becomes \"WARN\") and test that a lower-case level is normalized.",
 partial={"lib/LogParse.pm": ed(L, ("level => $2,", "level => uc($2),"))},
 done={"lib/LogParse.pm": ed(L, ("level => $2,", "level => uc($2),")),
       "t/parse.t": ed(T, ("tests => 1", "tests => 2"), ('"parses a line");', '"parses a line");\nis(parse_line("10:01 warn careful")->{level}, "WARN", "level is upper-cased");'))}),
dict(id="levels-filter", text="Add a --min LEVEL option to bin/summary.pl (order DEBUG < INFO < WARN < ERROR) that skips entries below that level, defaulting to counting everything.", ns=True,
 partial={"lib/LogParse.pm": ed(L, ("our @EXPORT_OK = qw(parse_line);", "our @EXPORT_OK = qw(parse_line level_rank);\n\nmy %RANK = (DEBUG => 0, INFO => 1, WARN => 2, ERROR => 3);\nsub level_rank { return $RANK{ uc $_[0] } // -1 }"))},
 done={"lib/LogParse.pm": ed(L, ("our @EXPORT_OK = qw(parse_line);", "our @EXPORT_OK = qw(parse_line level_rank);\n\nmy %RANK = (DEBUG => 0, INFO => 1, WARN => 2, ERROR => 3);\nsub level_rank { return $RANK{ uc $_[0] } // -1 }")),
       "bin/summary.pl": '''#!/usr/bin/perl
use strict;
use warnings;
use Getopt::Long;
use lib 'lib';
use LogParse qw(parse_line level_rank);

my $min = 'DEBUG';
GetOptions('min=s' => \\$min) or die "usage: summary.pl [--min LEVEL]\\n";
my $floor = level_rank($min);
die "unknown level: $min\\n" if $floor < 0;

my %count;
while (my $line = <STDIN>) {
    chomp $line;
    my $e = parse_line($line) or next;
    next if level_rank($e->{level}) < $floor;
    $count{ $e->{level} }++;
}
print "$_ $count{$_}\\n" for sort keys %count;
'''}),
dict(id="malformed-count", text="Lines that fail to parse are silently skipped. Have summary.pl count them and print a final \"malformed N\" line (only when N > 0), and make sure blank lines are not counted as malformed.",
 partial={"bin/summary.pl": ed(S, ("    my $e = parse_line($line) or next;", "    my $e = parse_line($line);\n    if (!$e) { $bad++; next; }"), ("my %count;", "my %count;\nmy $bad = 0;"), ('print "$_ $count{$_}\\n" for sort keys %count;', 'print "$_ $count{$_}\\n" for sort keys %count;\nprint "malformed $bad\\n" if $bad;'))},
 done={"bin/summary.pl": ed(S, ("    my $e = parse_line($line) or next;", "    next if $line =~ /^\\s*$/;\n    my $e = parse_line($line);\n    if (!$e) { $bad++; next; }"), ("my %count;", "my %count;\nmy $bad = 0;"), ('print "$_ $count{$_}\\n" for sort keys %count;', 'print "$_ $count{$_}\\n" for sort keys %count;\nprint "malformed $bad\\n" if $bad;'))}),
])

# supplementary partial-state files (tests/docs the near-miss did write)
_P = {r["id"]: r["partial"] for r in TASK["reqs"]}
_P["levels-filter"]["t/rank.t"] = '''use strict;
use warnings;
use Test::More tests => 2;
use lib 'lib';
use LogParse qw(level_rank);

ok(level_rank("WARN") > level_rank("INFO"), "WARN outranks INFO");
is(level_rank("nope"), -1, "unknown level");
'''
