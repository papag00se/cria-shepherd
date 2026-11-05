<?php
namespace Guestbook;

class Guestbook
{
    public const MAX_MESSAGE = 500;

    public function __construct(private string $file) {}

    public function add(string $name, string $message): void
    {
        if (trim($name) === '' || trim($message) === '') {
            throw new \InvalidArgumentException('name and message are required');
        }
        if (mb_strlen($message) > self::MAX_MESSAGE) {
            throw new \InvalidArgumentException('message too long');
        }
        $line = json_encode(['name' => $name, 'message' => $message, 'at' => time()]);
        file_put_contents($this->file, $line . "\n", FILE_APPEND);
    }

    public function all(): array
    {
        if (!file_exists($this->file)) {
            return [];
        }
        return array_map(fn($l) => json_decode($l, true), file($this->file, FILE_IGNORE_NEW_LINES));
    }
}
