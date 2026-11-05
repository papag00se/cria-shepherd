SELECT c.name, SUM(o.total_cents) AS spent
FROM customers c
JOIN orders o ON o.customer_id = c.id
GROUP BY c.id
ORDER BY spent DESC
LIMIT 10;
