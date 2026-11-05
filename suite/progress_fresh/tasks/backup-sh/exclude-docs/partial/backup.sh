#!/bin/sh
# usage: backup.sh SRC_DIR DEST_DIR
exclude=""
if [ "$1" = "--exclude" ]; then
  exclude="--exclude=$2"
  shift 2
fi
src=$1
dest=$2
stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p "$dest"
tar -czf "$dest/backup-$stamp.tar.gz" $exclude -C "$src" .
echo "wrote $dest/backup-$stamp.tar.gz"
