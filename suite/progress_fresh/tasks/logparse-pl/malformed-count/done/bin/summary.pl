#!/usr/bin/perl
use strict;
use warnings;
use lib 'lib';
use LogParse qw(parse_line);

my %count;
my $bad = 0;
while (my $line = <STDIN>) {
    chomp $line;
    next if $line =~ /^\s*$/;
    my $e = parse_line($line);
    if (!$e) { $bad++; next; }
    $count{ $e->{level} }++;
}
print "$_ $count{$_}\n" for sort keys %count;
print "malformed $bad\n" if $bad;
