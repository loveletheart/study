"""새 체크아웃과 누락된 활성화 스크립트의 실행 준비를 검증한다."""

import json
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(sys.platform == "win32", "Windows startup scripts")
class StartupTests(unittest.TestCase):
    def test_fresh_checkout_reuse_repair_and_dependency_failure(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(prefix="study startup ") as directory:
            checkout = Path(directory)
            shutil.copy2(project_root / "run.ps1", checkout / "run.ps1")
            # Bootstrap itself needs no third-party packages; keep this test offline.
            (checkout / "backend").mkdir()
            requirements = checkout / "backend" / "requirements.txt"
            requirements.write_text("# bootstrap regression test\n", encoding="utf-8")
            env = {**os.environ, "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}

            def setup(python_override: bool = True) -> subprocess.CompletedProcess:
                command = [
                    "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(checkout / "run.ps1"), "-SetupOnly",
                ]
                if python_override:
                    command.extend(["-Python", sys._base_executable])
                result = subprocess.run(
                    command,
                    cwd=project_root, env=env, capture_output=True, timeout=120,
                )
                self.assertEqual(result.returncode, 0, repr(result.stdout + result.stderr))
                self.assertIn(b"[venv] Active:", result.stdout)
                return result

            # No .venv exists at all, and the script is called from another cwd.
            setup(python_override=False)
            venv = checkout / ".venv"
            python = venv / "Scripts" / "python.exe"
            activate = venv / "Scripts" / "Activate.ps1"
            self.assertTrue(activate.is_file())
            result = subprocess.run(
                [str(python), "-c", "import json, sys; print(json.dumps([sys.prefix, sys.base_prefix]))"],
                capture_output=True, check=True, timeout=20,
            )
            prefix, base_prefix = json.loads(result.stdout)
            self.assertEqual(Path(prefix).resolve(), venv.resolve())
            self.assertNotEqual(prefix, base_prefix)

            # An existing environment is reused without deleting its files.
            marker = venv / "reuse-marker.txt"
            marker.write_text("keep", encoding="utf-8")
            reused = setup()
            self.assertNotIn(b"Creating or repairing", reused.stdout)
            self.assertTrue(marker.is_file())

            # Reproduce the original partially created environment.
            activate.unlink()
            setup()
            self.assertTrue(activate.is_file())
            self.assertTrue(marker.is_file())

            # Installation failure must stop before application startup.
            requirements.write_text("study-bootstrap-nonexistent-package==0.0.0\n", encoding="utf-8")
            failed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(checkout / "run.ps1")],
                cwd=project_root, env=env, capture_output=True, timeout=60,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertNotIn(b"[server]", failed.stdout)

    def test_main_delegates_before_importing_application_dependencies(self) -> None:
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        with patch("subprocess.call", return_value=0) as launch:
            with self.assertRaises(SystemExit) as stopped:
                runpy.run_path(str(main_path), run_name="__main__")
        self.assertEqual(stopped.exception.code, 0)
        command = launch.call_args.args[0]
        self.assertEqual(command[0], "powershell.exe")
        self.assertEqual(Path(command[-1]), main_path.parent.parent / "run.ps1")


if __name__ == "__main__":
    unittest.main()
