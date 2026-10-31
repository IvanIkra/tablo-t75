# PlatformIO pre-script: the git commit goes into the firmware version (FW_VERSION in
# src/state.h), "-dirty" if the firmware has changes not committed yet. Without git: "nogit".
import subprocess

Import("env")  # noqa: F821 - provided by PlatformIO


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=env.subst("$PROJECT_DIR"), capture_output=True,
                          text=True, check=True).stdout.strip()


try:
    commit = git("rev-parse", "--short=7", "HEAD")
    if git("status", "--porcelain", "--", "."):
        commit += "-dirty"
except (OSError, subprocess.CalledProcessError):
    commit = "nogit"

env.Append(CPPDEFINES=[("FW_COMMIT", env.StringifyMacro(commit))])
