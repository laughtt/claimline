"""Build the agent code bundle for AgentCore Runtime without Docker.

AgentCore runs the code on Linux arm64, so dependencies are installed as
manylinux aarch64 wheels into ``build/agent``. They are reinstalled only when
``agent/requirements.txt`` changes; the agent code is copied on every synth.
This uses uv, not pip: pip evaluates dependency markers for the host, so on
Windows it tries to pull in pywin32.
"""

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "agent"
BUNDLE = ROOT / "build" / "agent"
REQUIREMENTS = SOURCE / "requirements.txt"
STAMP = BUNDLE / ".requirements.sha256"

# Started by AgentCore as `python main.py`
ENTRYPOINT = '''from agent.main import app

app.run()
'''


def build() -> Path:
    wanted = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    if not STAMP.exists() or STAMP.read_text() != wanted:
        if BUNDLE.exists():
            shutil.rmtree(BUNDLE)
        BUNDLE.mkdir(parents=True)
        subprocess.run([
            sys.executable, "-m", "uv", "pip", "install", "--quiet",
            "--requirement", str(REQUIREMENTS),
            "--target", str(BUNDLE),
            "--python-platform", "aarch64-manylinux2014",
            "--python-version", "3.12",
            "--only-binary", ":all:",
        ], check=True)
        STAMP.write_text(wanted)

    package = BUNDLE / "agent"
    if package.exists():
        shutil.rmtree(package)
    package.mkdir()
    for f in SOURCE.glob("*.py"):
        shutil.copy2(f, package / f.name)
    (BUNDLE / "main.py").write_text(ENTRYPOINT)
    return BUNDLE
