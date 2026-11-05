#!/bin/sh
set -e
db=$(mktemp)
sqlite3 "$db" < schema.sql
sqlite3 "$db" < tests/seed.sql
sqlite3 "$db" < queries/top_customers.sql
sqlite3 "$db" < queries/monthly_revenue.sql
