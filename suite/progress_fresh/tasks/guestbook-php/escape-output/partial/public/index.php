<?php
require __DIR__ . '/../vendor/autoload.php';

$book = new Guestbook\Guestbook(__DIR__ . '/../data/entries.jsonl');
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $book->add($_POST['name'] ?? '', $_POST['message'] ?? '');
}
foreach ($book->all() as $e) {
    $name = htmlspecialchars($e['name']);
    echo "<p><b>{$name}</b>: {$e['message']}</p>";
}
