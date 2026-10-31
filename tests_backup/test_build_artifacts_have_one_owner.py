"""Two skip-sets for the same job, and the one feeding the "complete" listing was the shorter one.

`groundtruth._INVENTORY_EXCLUDE` and `execcheck._SKIP_DIRS` both answer "which directories did the
toolchain generate". They disagreed: execcheck knew about `target`, `dist` and `build`; the inventory
did not — and the inventory is what carries the footer "This list is complete — a file not listed
here does not exist in the workspace".

Measured on rust: ~450 lines of `target/` artifacts (.d, .rmeta, .rlib, extensionless fingerprint
files) presented to a judge as the workspace's own files, under a completeness claim.

The kernel is identical in every ecosystem — the toolchain wrote it, the coder did not — so it is one
constant with one owner.
"""
import unittest

from cria import execcheck, groundtruth


class OneSetSharedByEveryWalkerTests(unittest.TestCase):
    def test_the_two_consumers_use_the_same_object(self):
        self.assertIs(execcheck._SKIP_DIRS, groundtruth.BUILD_ARTIFACT_DIRS)
        self.assertIs(groundtruth._INVENTORY_EXCLUDE, groundtruth.BUILD_ARTIFACT_DIRS)

    def test_every_ecosystems_build_output_is_covered(self):
        for d in ("target", "dist", "build", "node_modules", "__pycache__", ".venv",
                  "site-packages", ".gradle", ".next"):
            with self.subTest(dir=d):
                self.assertIn(d, groundtruth.BUILD_ARTIFACT_DIRS)

    def test_directories_that_can_hold_real_source_are_left_in(self):
        """`bin`, `obj` and `vendor` are generated in some ecosystems and hand-written in others.
        The cost of being wrong here is hiding a deliverable from the judge, so they stay."""
        for d in ("bin", "obj", "vendor", "src", "lib", "test"):
            with self.subTest(dir=d):
                self.assertNotIn(d, groundtruth.BUILD_ARTIFACT_DIRS)


if __name__ == "__main__":
    unittest.main()
