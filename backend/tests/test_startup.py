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
        """가상환경 생성·재사용·복구와 설치 실패 시 중단을 확인한다."""
        project_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(prefix="study startup ") as directory:
            checkout = Path(directory)
            shutil.copy2(project_root / "run.ps1", checkout / "run.ps1")
            # 환경 준비 과정 자체에는 외부 패키지가 필요 없으므로 네트워크 없이 검증합니다.
            (checkout / "backend").mkdir()
            requirements = checkout / "backend" / "requirements.txt"
            requirements.write_text("# 환경 준비 과정의 회귀 테스트\n", encoding="utf-8-sig")
            env = {**os.environ, "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}

            def setup(python_override: bool = True) -> subprocess.CompletedProcess:
                """임시 프로젝트의 환경 준비 스크립트를 실행한다."""
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

            # 가상환경이 없는 상태에서 다른 작업 디렉터리를 기준으로 스크립트를 실행합니다.
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

            # 기존 가상환경의 파일을 삭제하지 않고 재사용하는지 확인합니다.
            marker = venv / "reuse-marker.txt"
            marker.write_text("keep", encoding="utf-8")
            reused = setup()
            self.assertNotIn(b"Creating or repairing", reused.stdout)
            self.assertTrue(marker.is_file())

            # 활성화 스크립트가 누락된 불완전한 가상환경을 재현합니다.
            activate.unlink()
            setup()
            self.assertTrue(activate.is_file())
            self.assertTrue(marker.is_file())

            # 패키지 설치에 실패하면 애플리케이션을 시작하기 전에 중단해야 합니다.
            requirements.write_text("study-bootstrap-nonexistent-package==0.0.0\n", encoding="utf-8")
            failed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(checkout / "run.ps1")],
                cwd=project_root, env=env, capture_output=True, timeout=60,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertNotIn(b"[server]", failed.stdout)

    def test_main_delegates_before_importing_application_dependencies(self) -> None:
        """의존성 로드 전에 실행 스크립트로 위임하는지 확인한다."""
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
