<?php
require __DIR__ . '/../vendor/autoload.php';

$book = new Guestbook\Guestbook(__DIR__ . '/../data/entries.jsonl');
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $book->add($_POST['name'] ?? '', $_POST['message'] ?? '');
}
foreach ($book->all() as $e) {
    echo "<p><b>{$e['name']}</b>: {$e['message']}</p>";
}
