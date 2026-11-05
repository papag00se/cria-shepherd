TASK = dict(name="guestbook-php", language="PHP", seed={
"composer.json": '{\n    "name": "example/guestbook",\n    "require": {"php": ">=8.1"},\n    "require-dev": {"phpunit/phpunit": "^10.5"},\n    "autoload": {"psr-4": {"Guestbook\\\\": "src/"}}\n}\n',
"src/Guestbook.php": '''<?php
namespace Guestbook;

class Guestbook
{
    public function __construct(private string $file) {}

    public function add(string $name, string $message): void
    {
        $line = json_encode(['name' => $name, 'message' => $message, 'at' => time()]);
        file_put_contents($this->file, $line . "\\n", FILE_APPEND);
    }

    public function all(): array
    {
        if (!file_exists($this->file)) {
            return [];
        }
        return array_map(fn($l) => json_decode($l, true), file($this->file, FILE_IGNORE_NEW_LINES));
    }
}
''',
"public/index.php": '''<?php
require __DIR__ . '/../vendor/autoload.php';

$book = new Guestbook\\Guestbook(__DIR__ . '/../data/entries.jsonl');
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $book->add($_POST['name'] ?? '', $_POST['message'] ?? '');
}
foreach ($book->all() as $e) {
    echo "<p><b>{$e['name']}</b>: {$e['message']}</p>";
}
''',
"tests/GuestbookTest.php": '''<?php
use Guestbook\\Guestbook;
use PHPUnit\\Framework\\TestCase;

final class GuestbookTest extends TestCase
{
    public function testAddedEntryIsListed(): void
    {
        $f = tempnam(sys_get_temp_dir(), 'gb');
        $g = new Guestbook($f);
        $g->add('ann', 'hi');
        $this->assertSame('hi', $g->all()[0]['message']);
    }
}
''',
}, unrelated={"composer.json": '{\n    "name": "example/guestbook",\n    "description": "A tiny guestbook",\n    "require": {"php": ">=8.1"},\n    "require-dev": {"phpunit/phpunit": "^10.5"},\n    "autoload": {"psr-4": {"Guestbook\\\\": "src/"}}\n}\n'},
reqs=[
dict(id="escape-output", text="Fix the stored-XSS hole: index.php must HTML-escape the name and message of every entry when rendering them.",
 partial={"public/index.php": '''<?php
require __DIR__ . '/../vendor/autoload.php';

$book = new Guestbook\\Guestbook(__DIR__ . '/../data/entries.jsonl');
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $book->add($_POST['name'] ?? '', $_POST['message'] ?? '');
}
foreach ($book->all() as $e) {
    $name = htmlspecialchars($e['name']);
    echo "<p><b>{$name}</b>: {$e['message']}</p>";
}
'''},
 done={"public/index.php": '''<?php
require __DIR__ . '/../vendor/autoload.php';

function e(string $s): string
{
    return htmlspecialchars($s, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

$book = new Guestbook\\Guestbook(__DIR__ . '/../data/entries.jsonl');
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $book->add($_POST['name'] ?? '', $_POST['message'] ?? '');
}
foreach ($book->all() as $entry) {
    echo '<p><b>' . e($entry['name']) . '</b>: ' . e($entry['message']) . '</p>';
}
'''}),
dict(id="reject-blank", text="Guestbook::add must throw InvalidArgumentException for a blank name or message (whitespace only counts as blank) and must limit messages to 500 characters, rejecting longer ones, without writing to the file.",
 partial={"src/Guestbook.php": '''<?php
namespace Guestbook;

class Guestbook
{
    public function __construct(private string $file) {}

    public function add(string $name, string $message): void
    {
        if ($name === '' || $message === '') {
            throw new \\InvalidArgumentException('name and message are required');
        }
        $line = json_encode(['name' => $name, 'message' => $message, 'at' => time()]);
        file_put_contents($this->file, $line . "\\n", FILE_APPEND);
    }

    public function all(): array
    {
        if (!file_exists($this->file)) {
            return [];
        }
        return array_map(fn($l) => json_decode($l, true), file($this->file, FILE_IGNORE_NEW_LINES));
    }
}
'''},
 done={"src/Guestbook.php": '''<?php
namespace Guestbook;

class Guestbook
{
    public const MAX_MESSAGE = 500;

    public function __construct(private string $file) {}

    public function add(string $name, string $message): void
    {
        if (trim($name) === '' || trim($message) === '') {
            throw new \\InvalidArgumentException('name and message are required');
        }
        if (mb_strlen($message) > self::MAX_MESSAGE) {
            throw new \\InvalidArgumentException('message too long');
        }
        $line = json_encode(['name' => $name, 'message' => $message, 'at' => time()]);
        file_put_contents($this->file, $line . "\\n", FILE_APPEND);
    }

    public function all(): array
    {
        if (!file_exists($this->file)) {
            return [];
        }
        return array_map(fn($l) => json_decode($l, true), file($this->file, FILE_IGNORE_NEW_LINES));
    }
}
'''}),
dict(id="phpunit-config", text="Make the tests runnable with `vendor/bin/phpunit`: add a phpunit.xml.dist that points at the tests/ directory and the composer autoloader, and add a `test` script to composer.json.",
 partial={"phpunit.xml.dist": '''<?xml version="1.0" encoding="UTF-8"?>
<phpunit bootstrap="vendor/autoload.php" colors="true">
</phpunit>
'''},
 done={"phpunit.xml.dist": '''<?xml version="1.0" encoding="UTF-8"?>
<phpunit bootstrap="vendor/autoload.php" colors="true">
    <testsuites>
        <testsuite name="guestbook">
            <directory>tests</directory>
        </testsuite>
    </testsuites>
</phpunit>
''', "composer.json": '{\n    "name": "example/guestbook",\n    "require": {"php": ">=8.1"},\n    "require-dev": {"phpunit/phpunit": "^10.5"},\n    "autoload": {"psr-4": {"Guestbook\\\\": "src/"}},\n    "scripts": {"test": "phpunit"}\n}\n'}),
])
