# -*- coding: utf-8 -*-
"""Write requirements-lock.txt with the exact versions installed in the current environment
for every package listed in requirements.txt (plus the Python version)."""
import platform
import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
names = []
for line in (repo / "requirements.txt").read_text(encoding="utf-8").splitlines():
    line = line.split("#")[0].strip()
    if line:
        names.append(re.split(r"[=<>!~ ]", line)[0])
out = [f"# python {platform.python_version()} ({platform.system()} {platform.release()})"]
for n in names:
    try:
        out.append(f"{n}=={version(n)}")
    except PackageNotFoundError:
        out.append(f"# {n}: NOT INSTALLED")
(repo / "requirements-lock.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
print("\n".join(out))
