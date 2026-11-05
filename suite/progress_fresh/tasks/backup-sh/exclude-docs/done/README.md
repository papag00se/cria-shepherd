# backup

Tar-gzips a directory into a timestamped archive.

## Options

`--exclude PATTERN` skips matching files (tar `--exclude` syntax); it must come first:

    sh backup.sh --exclude '*.log' ./site /var/backups
