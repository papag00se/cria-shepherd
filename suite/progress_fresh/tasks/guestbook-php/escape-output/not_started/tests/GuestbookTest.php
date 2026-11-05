<?php
use Guestbook\Guestbook;
use PHPUnit\Framework\TestCase;

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
