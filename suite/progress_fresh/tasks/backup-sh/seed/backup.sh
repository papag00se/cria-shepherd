#!/bin/sh
# usage: backup.sh SRC_DIR DEST_DIR
src=$1
dest=$2
stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p "$dest"
tar -czf "$dest/backup-$stamp.tar.gz" -C "$src" .
echo "wrote $dest/backup-$stamp.tar.gz"
