"""WSL cleanup safety regression tests (no WSL installation required)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import app
from server import wsl_cleanup


class WslCleanupTests(unittest.TestCase):
    def test_rejects_unsafe_roots_without_starting_wsl(self):
        with patch.object(wsl_cleanup.os, "name", "nt"), patch.object(
            wsl_cleanup.subprocess, "run", side_effect=AssertionError("WSL must not run")
        ):
            for root in ("/", "/home", "/tmp", "/mnt", "/home/me/../other", "relative"):
                report = wsl_cleanup.cleanup_wsl_project(root=root)
                self.assertTrue(report["errors"], root)

    def test_wsl_cleanup_uses_argument_vector_without_shell(self):
        from subprocess import CompletedProcess
        fake = CompletedProcess(["wsl.exe"], 0, '{"deleted_files":3,"reclaimed_bytes":4096}')
        with patch.object(wsl_cleanup.os, "name", "nt"), patch.object(
            wsl_cleanup.subprocess, "run", return_value=fake
        ) as run:
            report = wsl_cleanup.cleanup_wsl_project(
                root="/home/me/gameforge-oot", distro="Ubuntu", min_age_hours=48
            )
            self.assertEqual(report["deleted_files"], 3)
            args, kwargs = run.call_args
            self.assertEqual(args[0][:4], ["wsl.exe", "--distribution", "Ubuntu", "--exec"])
            self.assertFalse(kwargs.get("shell", False))

    def test_wrapper_detection_is_project_scoped(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            tools = project / "workspace" / "tools"
            tools.mkdir(parents=True)
            (tools / "build_mod.sh").write_text('mod="/home/me/oot-mod"\nmake all VERSION=gc-us\n')
            (tools / "build_mod.ps1").write_text("wsl -d Ubuntu --exec bash ./build_mod.sh")
            self.assertEqual(app._wsl_cleanup_target(project, {}), ("/home/me/oot-mod", "Ubuntu"))

    def test_linux_host_skips_wsl(self):
        if os.name != "nt":
            report = wsl_cleanup.cleanup_wsl_project(root="/home/me/gameforge")
            self.assertTrue(report["skipped"])


if __name__ == "__main__":
    unittest.main()
