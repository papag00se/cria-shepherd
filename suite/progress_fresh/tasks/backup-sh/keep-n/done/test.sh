#!/bin/sh
set -e
work=$(mktemp -d)
mkdir "$work/src"
echo hi > "$work/src/a.txt"
sh ./backup.sh "$work/src" "$work/out"
ls "$work/out" | grep -q '^backup-'
for i in 1 2 3; do touch "$work/out/backup-2000010$i-000000.tar.gz"; done
sh ./backup.sh "$work/src" "$work/out" 2 >/dev/null
[ "$(ls "$work/out" | wc -l)" -eq 2 ]
ls "$work/out" | grep -vq 20000101
echo PASS
