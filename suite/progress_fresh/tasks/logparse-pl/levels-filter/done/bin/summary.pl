#!/usr/bin/perl
use strict;
use warnings;
use Getopt::Long;
use lib 'lib';
use LogParse qw(parse_line level_rank);

my $min = 'DEBUG';
GetOptions('min=s' => \$min) or die "usage: summary.pl [--min LEVEL]\n";
my $floor = level_rank($min);
die "unknown level: $min\n" if $floor < 0;

my %count;
while (my $line = <STDIN>) {
    chomp $line;
    my $e = parse_line($line) or next;
    next if level_rank($e->{level}) < $floor;
    $count{ $e->{level} }++;
}
print "$_ $count{$_}\n" for sort keys %count;
