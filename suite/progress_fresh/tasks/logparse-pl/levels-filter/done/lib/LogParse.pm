package LogParse;
use strict;
use warnings;
use Exporter 'import';
our @EXPORT_OK = qw(parse_line level_rank);

my %RANK = (DEBUG => 0, INFO => 1, WARN => 2, ERROR => 3);
sub level_rank { return $RANK{ uc $_[0] } // -1 }

sub parse_line {
    my ($line) = @_;
    if ($line =~ /^(\S+) (\w+) (.*)$/) {
        return { time => $1, level => $2, msg => $3 };
    }
    return;
}

1;
