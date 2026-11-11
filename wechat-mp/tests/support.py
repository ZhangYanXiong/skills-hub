"""回归测试共用的真实 CLI 与模块加载工具。"""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="wechat-mp-test-")
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_script(self, script, *args):
        return subprocess.run(
            [sys.executable, "-I", "-B", str(SCRIPTS / script), *map(str, args)],
            cwd=SKILL_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
