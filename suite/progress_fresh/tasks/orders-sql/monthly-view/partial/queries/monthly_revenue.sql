SELECT substr(placed_at, 1, 7) AS month,
       COUNT(*) AS orders,
       SUM(total_cents) AS revenue_cents
FROM orders
GROUP BY month
ORDER BY month DESC;
