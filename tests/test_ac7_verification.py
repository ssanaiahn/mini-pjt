import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_ac7_tests_only_import_stdlib_or_requirements():
    reqs = {re.split(r"[<>=\[ ]", l.strip())[0].lower().replace("-", "_")
            for l in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")}
    allowed = reqs | {"voc", "app", "tests", "conftest", "evaluation"} | set(sys.stdlib_module_names)
    files = [*(ROOT / "tests").glob("*.py"), *(ROOT / "voc").glob("*.py"),
             *(ROOT / "evaluation").glob("*.py"), ROOT / "app.py"]
    for f in files:
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = [a.name for a in n.names] if isinstance(n, ast.Import) else \
                [n.module] if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module else []
            for m in mods:
                assert m.split(".")[0] in allowed, f"{f.name}: {m}"


def test_ac7_pytest_config_collects_tests_dir():
    assert "testpaths = tests" in (ROOT / "pytest.ini").read_text(encoding="utf-8")
