from suite.progress_fresh.dsl import ed

SEED = {
"schema.sql": '''CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    total_cents INTEGER NOT NULL,
    placed_at TEXT NOT NULL
);
''',
"queries/top_customers.sql": '''SELECT c.name, SUM(o.total_cents) AS spent
FROM customers c
JOIN orders o ON o.customer_id = c.id
GROUP BY c.id
ORDER BY spent DESC
LIMIT 10;
''',
"tests/check.sh": '''#!/bin/sh
set -e
db=$(mktemp)
sqlite3 "$db" < schema.sql
sqlite3 "$db" < tests/seed.sql
sqlite3 "$db" < queries/top_customers.sql
''',
"tests/seed.sql": "INSERT INTO customers VALUES (1, 'Ann', 'ann@example.com'), (2, 'Bo', 'bo@example.com'), (3, 'Cy', 'cy@example.com');\nINSERT INTO orders VALUES (1, 1, 500, '2024-01-02'), (2, 1, 700, '2024-02-03'), (3, 2, 100, '2024-02-04');\n",
}
S = SEED["schema.sql"]
Q = SEED["queries/top_customers.sql"]
CK = SEED["tests/check.sh"]
TASK = dict(extension=True, name="orders-sql", language="SQL", seed=SEED,
unrelated={"queries/top_customers.sql": "-- ten biggest spenders\n" + Q},
reqs=[
dict(id="include-zero", text="The top-customers report must also list customers with no orders (spent = 0) instead of dropping them, still ordered by spent descending, then name.",
 partial={"queries/top_customers.sql": ed(Q, ("JOIN orders", "LEFT JOIN orders"))},
 done={"queries/top_customers.sql": '''SELECT c.name, COALESCE(SUM(o.total_cents), 0) AS spent
FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id
GROUP BY c.id
ORDER BY spent DESC, c.name ASC
LIMIT 10;
'''}),
dict(id="email-unique", text="Emails must be unique per customer: add the constraint to schema.sql and a case-insensitive index so 'Ann@Example.com' and 'ann@example.com' collide.",
 partial={"schema.sql": ed(S, ("    email TEXT NOT NULL\n", "    email TEXT NOT NULL UNIQUE\n"))},
 done={"schema.sql": ed(S, ("    email TEXT NOT NULL\n);\n", "    email TEXT NOT NULL\n);\n\nCREATE UNIQUE INDEX customers_email_ci ON customers (lower(email));\n"))}),
dict(id="monthly-view", text="Add queries/monthly_revenue.sql returning one row per month (YYYY-MM) with order count and revenue_cents, newest month first, and call it from tests/check.sh.",
 partial={"queries/monthly_revenue.sql": '''SELECT substr(placed_at, 1, 7) AS month,
       COUNT(*) AS orders,
       SUM(total_cents) AS revenue_cents
FROM orders
GROUP BY month
ORDER BY month DESC;
'''},
 done={"queries/monthly_revenue.sql": '''SELECT substr(placed_at, 1, 7) AS month,
       COUNT(*) AS orders,
       SUM(total_cents) AS revenue_cents
FROM orders
GROUP BY month
ORDER BY month DESC;
''', "tests/check.sh": CK + 'sqlite3 "$db" < queries/monthly_revenue.sql\n'}),
])
