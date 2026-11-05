#!/bin/sh
set -e
work=$(mktemp -d)
mkdir "$work/src"
echo hi > "$work/src/a.txt"
sh ./backup.sh "$work/src" "$work/out"
ls "$work/out" | grep -q '^backup-'
echo PASS
