SELECT c.name, COALESCE(SUM(o.total_cents), 0) AS spent
FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id
GROUP BY c.id
ORDER BY spent DESC, c.name ASC
LIMIT 10;
