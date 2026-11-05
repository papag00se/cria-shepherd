package LogParse;
use strict;
use warnings;
use Exporter 'import';
our @EXPORT_OK = qw(parse_line);

sub parse_line {
    my ($line) = @_;
    if ($line =~ /^(\S+) (\w+) (.*)$/) {
        return { time => $1, level => $2, msg => $3 };
    }
    return;
}

1;
