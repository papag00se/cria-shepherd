<?php
require __DIR__ . '/../vendor/autoload.php';

function e(string $s): string
{
    return htmlspecialchars($s, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

$book = new Guestbook\Guestbook(__DIR__ . '/../data/entries.jsonl');
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $book->add($_POST['name'] ?? '', $_POST['message'] ?? '');
}
foreach ($book->all() as $entry) {
    echo '<p><b>' . e($entry['name']) . '</b>: ' . e($entry['message']) . '</p>';
}
