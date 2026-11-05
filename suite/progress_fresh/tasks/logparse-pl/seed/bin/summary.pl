#!/usr/bin/perl
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
print "$_ $count{$_}\n" for sort keys %count;
