"""Regression test for issue #68 T15: install.bat / uninstall.bat treat an
empty ``set /p`` reply (Enter) as "yes" on (y/N) prompts, because the
variable is pre-set to "y" and ``set /p`` leaves it unchanged on empty
input. Enter must mean No: nothing installed, overwritten or removed.

SAFETY: every scenario runs the real .bat files, but only against a
throwaway project directory and a temp ``USERPROFILE``, with recorder
stubs for ``python``/``pip``/``npm`` placed first on ``PATH`` so no real
Python package is installed and no real skill directory is touched.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALL_BAT = ROOT / "install.bat"
UNINSTALL_BAT = ROOT / "uninstall.bat"

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="install.bat/uninstall.bat are Windows-only"
)

# Extra blank-line buffer appended to every scripted stdin so any prompt
# that isn't the one under test (e.g. install.bat's gh-CLI prompt, which
# already defaults its REPLY to "n" and is out of scope for T15) doesn't
# leave `set /p` waiting on a closed pipe.
_BUFFER = "\n" * 6

# A recorder stub must be a real .exe, not a .bat/.cmd: install.bat invokes
# `!PYTHON_CMD! ...` directly (no `call`), which is fine for a real
# python.exe but would hand control to a .bat stub permanently (the
# classic "batch calling batch without call never returns" behaviour) and
# abort the rest of install.bat before it reaches the prompts under test.
_STUB_SOURCE = """
using System;
using System.IO;

class Stub
{
    static int Main(string[] args)
    {
        string exeName = Path.GetFileNameWithoutExtension(Environment.GetCommandLineArgs()[0]);
        string logDir = Environment.GetEnvironmentVariable("LOG_DIR");
        if (!string.IsNullOrEmpty(logDir))
        {
            string logFile = Path.Combine(logDir, exeName + ".log");
            File.AppendAllText(logFile, string.Join(" ", args) + Environment.NewLine);
        }
        if (exeName.Equals("python", StringComparison.OrdinalIgnoreCase)
            && args.Length > 0 && args[0] == "-c")
        {
            int code;
            if (!int.TryParse(Environment.GetEnvironmentVariable("STUB_PROBE_EXIT"), out code))
            {
                code = 0;
            }
            return code;
        }
        return 0;
    }
}
"""

_CSC_CANDIDATES = [
    shutil.which("csc.exe") or shutil.which("csc"),
    r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
    r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe",
]


@pytest.fixture(scope="session")
def stub_exe(tmp_path_factory) -> Path:
    """Compile the recorder-stub source into a single reusable .exe."""
    csc = next((c for c in _CSC_CANDIDATES if c and Path(c).exists()), None)
    if csc is None:
        pytest.skip("csc.exe not found; cannot build the install.bat stub executables")
    build_dir = tmp_path_factory.mktemp("stub_build")
    src = build_dir / "stub.cs"
    src.write_text(_STUB_SOURCE, encoding="ascii")
    out = build_dir / "stub.exe"
    result = subprocess.run(
        [csc, "/nologo", f"/out:{out}", str(src)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0 or not out.exists():
        pytest.skip("csc.exe failed to build the install.bat stub executable: " + result.stdout)
    # Pay any first-execution cost (e.g. Windows Defender scanning a fresh,
    # unsigned binary) here, once, instead of racing it inside a
    # timing-sensitive `set /p` stdin pipe in every test below.
    subprocess.run([str(out)], capture_output=True, timeout=30)
    return out


def _make_stub_bin(tmp_path: Path, stub_exe: Path, *, deps_missing: bool) -> tuple[Path, Path]:
    """Recorder stubs for python/pip/npm, placed first on PATH.

    Returns (bin_dir, log_dir). Each invocation is appended to
    ``<log_dir>/<name>.log``. The stub exits 1 for python's ``-c`` probes
    when ``deps_missing`` is true (simulating missing pipdeptree/requests),
    and exits 0 for everything else (e.g. ``-m pip install ...``).
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    for name in ("python.exe", "pip.exe", "npm.exe"):
        shutil.copy(stub_exe, bin_dir / name)

    return bin_dir, log_dir


def _minimal_env(
    tmp_path: Path, bin_dir: Path, log_dir: Path, userprofile: Path, *, deps_missing: bool = False
) -> dict:
    windir = Path(r"C:\Windows")
    path = ";".join(
        str(p)
        for p in (
            bin_dir,
            windir / "System32",
            windir,
            windir / "System32" / "Wbem",
            windir / "System32" / "WindowsPowerShell" / "v1.0",
        )
    )
    return {
        "PATH": path,
        "SystemRoot": str(windir),
        "USERPROFILE": str(userprofile),
        "LOG_DIR": str(log_dir),
        "STUB_PROBE_EXIT": "1" if deps_missing else "0",
        "TEMP": str(tmp_path),
        "TMP": str(tmp_path),
    }


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "package-upgrade").mkdir(parents=True)
    (project / "package-upgrade" / "dummy.txt").write_text("x", encoding="ascii")
    (project / "package-upgrade-feedback").mkdir(parents=True)
    (project / "package-upgrade-feedback" / "dummy.txt").write_text("x", encoding="ascii")
    return project


def _run(
    script: Path, args: list[str], cwd: Path, env: dict, stdin: str
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["cmd", "/c", str(script), *args],
        cwd=cwd,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=60,
    )


def _read_log(log_dir: Path, name: str) -> str:
    log_file = log_dir / f"{name}.log"
    return log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else ""


# --------------------------------------------------------------------------- #
# install.bat: "Continue installing?" prompt (install.bat:98-99)
# --------------------------------------------------------------------------- #


def test_enter_cancels_install(tmp_path, stub_exe):
    bin_dir, log_dir = _make_stub_bin(tmp_path, stub_exe, deps_missing=False)
    userprofile = tmp_path / "home"
    userprofile.mkdir()
    project = _make_project(tmp_path)
    env = _minimal_env(tmp_path, bin_dir, log_dir, userprofile)

    result = _run(INSTALL_BAT, [], project, env, "\n" + _BUFFER)

    target_dir = userprofile / ".claude" / "skills" / "package-upgrade"
    assert result.returncode == 0, result.stdout + result.stderr
    assert not target_dir.exists(), "Enter at the install prompt must not install anything"


def test_y_proceeds_with_install(tmp_path, stub_exe):
    bin_dir, log_dir = _make_stub_bin(tmp_path, stub_exe, deps_missing=False)
    userprofile = tmp_path / "home"
    userprofile.mkdir()
    project = _make_project(tmp_path)
    env = _minimal_env(tmp_path, bin_dir, log_dir, userprofile)

    result = _run(INSTALL_BAT, [], project, env, "y\n" + _BUFFER)

    target_dir = userprofile / ".claude" / "skills" / "package-upgrade"
    assert result.returncode == 0, result.stdout + result.stderr
    assert (target_dir / "dummy.txt").exists(), "y must still proceed with install"


def test_yes_flag_proceeds_without_prompting(tmp_path, stub_exe):
    bin_dir, log_dir = _make_stub_bin(tmp_path, stub_exe, deps_missing=False)
    userprofile = tmp_path / "home"
    userprofile.mkdir()
    project = _make_project(tmp_path)
    env = _minimal_env(tmp_path, bin_dir, log_dir, userprofile)

    result = _run(INSTALL_BAT, ["--yes"], project, env, "")

    target_dir = userprofile / ".claude" / "skills" / "package-upgrade"
    assert result.returncode == 0, result.stdout + result.stderr
    assert (target_dir / "dummy.txt").exists(), "--yes must install without any prompt"


# --------------------------------------------------------------------------- #
# install.bat: "overwrite existing install?" prompt (install.bat:118-119)
# --------------------------------------------------------------------------- #


def test_enter_declines_overwrite(tmp_path, stub_exe):
    bin_dir, log_dir = _make_stub_bin(tmp_path, stub_exe, deps_missing=False)
    userprofile = tmp_path / "home"
    userprofile.mkdir()
    project = _make_project(tmp_path)
    env = _minimal_env(tmp_path, bin_dir, log_dir, userprofile)

    target_dir = userprofile / ".claude" / "skills" / "package-upgrade"
    target_dir.mkdir(parents=True)
    marker = target_dir / "MARKER.txt"
    marker.write_text("keep me", encoding="ascii")

    # "y" answers the first (continue) prompt, then Enter at the overwrite
    # prompt must decline rather than delete the existing install.
    result = _run(INSTALL_BAT, [], project, env, "y\n\n" + _BUFFER)

    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.exists(), "Enter at the overwrite prompt must not delete the existing install"


# --------------------------------------------------------------------------- #
# install.bat: "install missing Python deps?" prompt (install.bat:178-179)
# --------------------------------------------------------------------------- #


def test_enter_declines_dependency_install(tmp_path, stub_exe):
    bin_dir, log_dir = _make_stub_bin(tmp_path, stub_exe, deps_missing=True)
    userprofile = tmp_path / "home"
    userprofile.mkdir()
    project = _make_project(tmp_path)
    env = _minimal_env(tmp_path, bin_dir, log_dir, userprofile, deps_missing=True)

    # "y" answers the continue prompt; no overwrite prompt (fresh install);
    # Enter at the dependency prompt must not run pip install.
    result = _run(INSTALL_BAT, [], project, env, "y\n\n" + _BUFFER)

    assert result.returncode == 0, result.stdout + result.stderr
    python_log = _read_log(log_dir, "python")
    assert "pip install" not in python_log, (
        "Enter at the dependency prompt must not run pip install: " + python_log
    )


def test_yes_flag_installs_dependencies(tmp_path, stub_exe):
    bin_dir, log_dir = _make_stub_bin(tmp_path, stub_exe, deps_missing=True)
    userprofile = tmp_path / "home"
    userprofile.mkdir()
    project = _make_project(tmp_path)
    env = _minimal_env(tmp_path, bin_dir, log_dir, userprofile, deps_missing=True)

    result = _run(INSTALL_BAT, ["--yes"], project, env, "")

    assert result.returncode == 0, result.stdout + result.stderr
    python_log = _read_log(log_dir, "python")
    assert "pip install" in python_log, "--yes must still install missing deps: " + python_log


# --------------------------------------------------------------------------- #
# uninstall.bat: "remove skill?" prompt (uninstall.bat:96-97)
# --------------------------------------------------------------------------- #


def _make_fingerprinted_skill(skills_root: Path) -> Path:
    skill_dir = skills_root / "package-upgrade"
    (skill_dir / "scripts" / "common").mkdir(parents=True)
    (skill_dir / "scripts" / "go").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: package-upgrade\n---\n", encoding="ascii")
    (skill_dir / "scripts" / "common" / "save_token.sh").write_text("", encoding="ascii")
    (skill_dir / "scripts" / "common" / "provenance_stop_hook.py").write_text("", encoding="ascii")
    (skill_dir / "scripts" / "go" / "dep_tree.py").write_text("", encoding="ascii")
    return skill_dir


def test_enter_declines_uninstall(tmp_path, stub_exe):
    bin_dir, log_dir = _make_stub_bin(tmp_path, stub_exe, deps_missing=False)
    userprofile = tmp_path / "home"
    userprofile.mkdir()
    project = _make_project(tmp_path)
    env = _minimal_env(tmp_path, bin_dir, log_dir, userprofile)

    skills_root = userprofile / ".claude" / "skills"
    skill_dir = _make_fingerprinted_skill(skills_root)

    result = _run(UNINSTALL_BAT, [], project, env, "\n" + _BUFFER)

    assert result.returncode == 0, result.stdout + result.stderr
    assert skill_dir.exists(), "Enter at the uninstall prompt must not remove the skill"


def test_yes_flag_uninstalls(tmp_path, stub_exe):
    bin_dir, log_dir = _make_stub_bin(tmp_path, stub_exe, deps_missing=False)
    userprofile = tmp_path / "home"
    userprofile.mkdir()
    project = _make_project(tmp_path)
    env = _minimal_env(tmp_path, bin_dir, log_dir, userprofile)

    skills_root = userprofile / ".claude" / "skills"
    skill_dir = _make_fingerprinted_skill(skills_root)

    result = _run(UNINSTALL_BAT, ["--yes"], project, env, "")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not skill_dir.exists(), "--yes must still remove the fingerprinted skill"
