"""cria refused 492 commands for tokens that were never a path it would open.

`command_refusal` scans for rooted tokens and refuses the command that contains one. It did that
without first establishing that the token is a filesystem path the command opens, which #5b forbids
in as many words: a refusal must name something the coder can actually change, and a command must be
validated as well-formed before it is judged.

REPLAYED over every captured refusal, with each command's real workspace root taken from its own
leading `cd`:

    refused, before        51 distinct / 1,225 occurrences
    refused, after         31 distinct /   733 occurrences
    no longer refused      20 distinct /   492 occurrences   (40%)

Two shapes, both of them cria answering a question it could not observe.

A PARAMETER VALUE IS NOT AN ACCESS. A weak model wrote a tool SIGNATURE as a shell command —

    exec_command cmd="go mod tidy", justification="…", max_output_tokens=10000, shell="/bin/bash"

— and cria refused it for the interpreter named in the last parameter, answering "Writing/reading
outside the working directory is not permitted". There is nothing there for the coder to change: the
string was never a shell command. The difference from `cat "/etc/x"`, which IS a path and is still
refused, is the `=` in front of the quote, and that is the whole difference. 9 distinct commands,
229 occurrences.

A SUFFIX ON AN UNRESOLVED EXPANSION IS NOT A PATH. `ls $(go env GOPATH)/pkg/github.com/…` contains
no path the coder wrote: the leading component comes from a command cria never ran, so whether the
result lands inside the workspace is unknowable from the string. #11b — a mechanism that cannot
observe the thing it is judging must abstain. It did not; it read `/pkg/github.com/…` as an absolute
path and refused. 11 distinct commands, 263 occurrences.

Everything the guard is FOR still holds: a heredoc writing to /tmp, a `find /`, a redirect to an
external file, a bare external write target, and a quoted path that opens its quote.
"""

import unittest

from cria import dirguard

WS = "/tmp/ws"


def refused(cmd, level="none", workspace=WS):
    return dirguard.command_refusal(cmd, level, workspace)


class AParameterValueIsNotAnAccessTests(unittest.TestCase):
    def test_the_measured_tool_signature(self):
        cmd = ('exec_command cmd="go mod tidy", justification="Download dependencies", '
               'max_output_tokens=10000, yield_time_ms=30000, tty=true, shell="/bin/bash"')
        self.assertIsNone(refused(cmd))

    def test_a_spaced_assignment_too(self):
        self.assertIsNone(refused('run shell = "/bin/bash"'))

    def test_an_env_prefix_assignment(self):
        self.assertIsNone(refused('OUT="/etc/passwd" cat local.txt'))

    def test_a_quoted_path_that_opens_its_quote_is_still_a_path(self):
        """The distinction is the `=`. Without one, a quote that OPENS with the path is a real file
        argument and stays refused — that is what the quote rule was written for."""
        self.assertIsNotNone(refused('cat "/etc/passwd"'))

    def test_a_mid_quote_term_is_still_a_search_pattern(self):
        self.assertIsNone(refused('grep -n "GET /handles" file.go'))


class ASuffixOnAnUnresolvedExpansionIsNotAPathTests(unittest.TestCase):
    def test_a_command_substitution_tail(self):
        self.assertIsNone(refused("ls -la $(go env GOPATH)/pkg/github.com/shopspring/decimal"))

    def test_a_brace_expansion_tail(self):
        self.assertIsNone(refused("ls ${GOROOT}/pkg/"))

    def test_a_nested_substitution_tail(self):
        self.assertIsNone(refused("ls $(dirname $(which go))/../pkg/x"))

    def test_a_plain_paren_is_not_an_expansion(self):
        """Only `$(`/`${` make the leading component unknowable. A bare `)` before a rooted token is
        an ordinary subshell boundary and the path after it is the coder's own."""
        self.assertIsNotNone(refused("(cd x) && cat /etc/passwd"))

    def test_an_unmatched_paren_does_not_exempt(self):
        self.assertIsNotNone(refused("echo ) /etc/passwd"))


class EverythingTheGuardIsForStillHoldsTests(unittest.TestCase):
    def test_an_external_heredoc_write(self):
        self.assertIsNotNone(refused("cat > /tmp/test.rs << 'EOF'\nfn main(){}\nEOF"))

    def test_reading_the_whole_filesystem(self):
        self.assertIsNotNone(refused("find / -name bundle 2>/dev/null"))

    def test_an_external_redirect_target(self):
        self.assertIsNotNone(refused("java -cp x pipeline.Importer > /tmp/run1.txt 2>&1"))

    def test_a_bare_external_write_target(self):
        self.assertIsNotNone(refused("cp local.txt /etc/hosts"))

    def test_the_workspace_itself_is_never_refused(self):
        self.assertIsNone(refused(f"cat {WS}/main.go"))

    def test_a_command_with_no_rooted_token(self):
        self.assertIsNone(refused("go build ./..."))

    def test_read_level_still_allows_an_external_read(self):
        self.assertIsNone(refused("cat /etc/hosts", level="read"))

    def test_read_level_still_refuses_an_external_write(self):
        self.assertIsNotNone(refused("cp x /etc/hosts", level="read"))

    def test_write_level_is_off_entirely(self):
        self.assertIsNone(refused("rm -rf /etc", level="write"))


class TheHelpersAnswerTheirOwnQuestionTests(unittest.TestCase):
    def test_param_quote_detection(self):
        for cmd, start, want in ((' shell="/bin/bash"', 8, True),
                                 ('cat "/etc/x"', 5, False),
                                 ('k = "/etc/x"', 5, True)):
            with self.subTest(cmd=cmd):
                self.assertEqual(dirguard._is_param_value_quote(cmd, start), want)

    def test_expansion_tail_detection(self):
        for cmd, want in (("$(go env GOPATH)/pkg", True),
                          ("${GOROOT}/pkg", True),
                          ("(subshell)/pkg", False),
                          ("/pkg", False)):
            start = cmd.rindex("/pkg")
            with self.subTest(cmd=cmd):
                self.assertEqual(dirguard._after_unresolved_expansion(cmd, start), want)


if __name__ == "__main__":
    unittest.main()
