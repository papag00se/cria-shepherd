"""What one ``read`` frame of a file says about it, decided here (docs/harness-programs.md section 7, Phase 6b): whether it is empty or whitespace-only text, has
something in it, or is not text at all, and the sha-256 the harness computed over the whole file. This is what the unread-write rule stands on (a blank file may
be overwritten unread, a file that is not may not). The harness returns bytes and a hash; the decision is cria's."""
import codecs
import os

FACT_LEN = 512            # bytes of a file that decide whether it is text with something in it
FACT_FULL = 1 << 20       # a file whose first bytes are only whitespace is read this far (whitespace compresses to nothing)
FACT_FLOOR = 64           # a read the harness cut is asked again at half the length, down to this


def error(code) -> str:
    return f'[Errno {code}] {os.strerror(code)}' if isinstance(code, int) and code else 'unreadable'


def decide(header: dict, data: bytes, whole_asked: bool = False) -> tuple:
    """``(blank, digest, error, whole file needed)`` from an ok frame of a ``read`` and the bytes it returned: ``blank`` is True or False for text and None
    for anything else (not UTF-8, binary), ``digest`` the harness's sha-256 of the whole file (None where nothing is claimed), ``error`` set when the file
    changed while it was read, and the last item says that the first bytes were only whitespace so the rest decides (once)."""
    if header['fsize'] != header['size']:
        return None, None, 'file changed during the read', False
    complete = len(data) >= header['fsize']
    if b'\0' in data:
        return None, None, None, False                                          # binary
    try:
        text = codecs.getincrementaldecoder('utf-8')('strict').decode(data, final=complete)
    except UnicodeError:
        return None, None, None, False                                          # not UTF-8
    blank = not text or text.isspace()
    if blank and not complete:
        return None, None, None, not whole_asked                                # only whitespace so far: the rest decides (once)
    return blank, header['fsha'], None, False
