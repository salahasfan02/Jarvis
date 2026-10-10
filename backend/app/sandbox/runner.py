"""Sandbox v2 — reliable, multi-language, multi-file code execution.

Guarantees:
- NEVER fails silently: every problem (missing runtime, compile error, spawn
  failure, timeout) comes back as a readable message with logs.
- Execution runs under macOS sandbox-exec: no network, writes confined to the
  working directory. Package installation (pip/npm) runs BEFORE the sandbox
  with network, then execution is offline.
- Multi-file projects; optional persistent project folders under
  ~/.jarvis/projects/<name> (also served at /projects/<name>/ for live HTML
  preview).

Languages: python, javascript, typescript (node --experimental-strip-types),
bash, c, c++, go, rust, java — compiled ones require their toolchain and the
error says exactly what to install when missing.
"""
from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
import time
from pathlib import Path

from ..config import JARVIS_HOME

PROJECTS_DIR = JARVIS_HOME / "projects"
PROJECTS_DIR.mkdir(exist_ok=True)

# Later rules win in SBPL. Reads stay open in general (runtimes need the
# system), but secrets and personal data are closed, and Apple Events are
# denied — `osascript` could otherwise tell Terminal to run anything outside
# the sandbox.
PRIVATE_DIRS = [".ssh", ".aws", ".gnupg", ".jarvis", ".docker", ".kube", ".netrc",
                "Library/Messages", "Library/Mail", "Library/Keychains", "Library/Cookies",
                "Library/Safari", "Library/Application Support/Google/Chrome",
                "Library/Containers/com.apple.mail", "Library/Group Containers"]

PROFILE = """(version 1)
(allow default)
(deny network*)
(deny appleevent-send)
(deny file-read* {private})
(deny file-write*)
(allow file-read* file-write* (subpath "{workdir}"))
(allow file-write* (subpath "/private/var/folders") (subpath "/dev"))
"""


def _profile(workdir: Path) -> str:
    home = Path.home()
    private = " ".join(f'(subpath "{home / d}")' for d in PRIVATE_DIRS)
    return PROFILE.format(workdir=str(workdir.resolve()), private=private)

LANGS: dict[str, dict] = {
    "python":     {"ext": "py",   "bin": "python3"},
    "javascript": {"ext": "js",   "bin": "node"},
    "typescript": {"ext": "ts",   "bin": "node"},
    "bash":       {"ext": "sh",   "bin": "bash"},
    "c":          {"ext": "c",    "bin": "clang",  "compiled": True,
                   "install": "xcode-select --install"},
    "c++":        {"ext": "cpp",  "bin": "clang++", "compiled": True,
                   "install": "xcode-select --install"},
    "go":         {"ext": "go",   "bin": "go",     "install": "brew install go"},
    "rust":       {"ext": "rs",   "bin": "rustc",  "compiled": True,
                   "install": "brew install rust"},
    "java":       {"ext": "java", "bin": "java",   "install": "brew install openjdk"},
    "html":       {"ext": "html", "bin": None},
}
ALIASES = {"js": "javascript", "node": "javascript", "ts": "typescript",
           "sh": "bash", "shell": "bash", "zsh": "bash", "cpp": "c++",
           "c#": None, "py": "python", "golang": "go"}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or "project"


async def _shell(cmd: list[str], cwd: Path, timeout: float,
                 env: dict | None = None) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(cwd), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def run(code: str = "", language: str = "python", timeout: int = 30,
              files: list[dict] | None = None, packages: list[str] | None = None,
              project: str = "", entry: str = "") -> dict:
    """Execute code. `files` = [{"name","content"}]; `code` becomes the entry
    file when files don't already include one. Returns a rich result dict."""
    started = time.time()
    logs: list[str] = []
    language = ALIASES.get((language or "python").lower(),
                           (language or "python").lower())
    if language not in LANGS:
        return {"error": f"unsupported language '{language}'. Supported: "
                         + ", ".join(LANGS)}
    spec = LANGS[language]

    if spec["bin"] and shutil.which(spec["bin"]) is None:
        hint = spec.get("install", f"install {spec['bin']}")
        return {"error": f"{spec['bin']} is not installed on this Mac. "
                         f"Install it with: {hint}"}

    # ---- workspace -----------------------------------------------------
    persistent = bool(project)
    if persistent:
        workdir = PROJECTS_DIR / _slug(project)
        workdir.mkdir(parents=True, exist_ok=True)
    else:
        workdir = Path(tempfile.mkdtemp(prefix="jarvis-run-"))

    try:
        for f in files or []:
            target = (workdir / f["name"]).resolve()
            if not str(target).startswith(str(workdir.resolve())):
                return {"error": f"illegal file path: {f['name']}"}
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f.get("content", ""))
            logs.append(f"wrote {f['name']} ({len(f.get('content',''))} chars)")

        entry_name = entry or f"main.{spec['ext']}"
        if code and not (workdir / entry_name).exists():
            (workdir / entry_name).write_text(code)
            logs.append(f"wrote {entry_name}")
        if not (workdir / entry_name).exists():
            return {"error": f"no entry file: provide `code` or a file named {entry_name}"}

        # ---- html: no execution, serve it -------------------------------
        if language == "html":
            if not persistent:
                project = f"preview-{int(started)}"
                target_dir = PROJECTS_DIR / _slug(project)
                shutil.copytree(workdir, target_dir, dirs_exist_ok=True)
                workdir_final = target_dir
            else:
                workdir_final = workdir
            url = f"http://127.0.0.1:8765/projects/{_slug(project)}/{entry_name}"
            return {"exit_code": 0, "stdout": "", "stderr": "",
                    "preview_url": url, "project": _slug(project),
                    "logs": logs, "seconds": round(time.time() - started, 2)}

        # ---- dependency install (network ON, before sandboxing) ----------
        if packages:
            if language == "python":
                logs.append(f"pip installing: {', '.join(packages)}")
                rc, out, err = await _shell(
                    ["python3", "-m", "pip", "install", "--quiet",
                     "--target", str(workdir / "_deps"), *packages],
                    workdir, timeout=240)
                if rc != 0:
                    return {"error": f"pip install failed:\n{(err or out)[-1500:]}",
                            "logs": logs}
            elif language in ("javascript", "typescript"):
                logs.append(f"npm installing: {', '.join(packages)}")
                rc, out, err = await _shell(
                    ["npm", "install", "--no-audit", "--no-fund", *packages],
                    workdir, timeout=240)
                if rc != 0:
                    return {"error": f"npm install failed:\n{(err or out)[-1500:]}",
                            "logs": logs}

        # ---- build (compiled languages) ----------------------------------
        binary = workdir / "_app"
        if spec.get("compiled"):
            compile_cmd = {"c": ["clang", entry_name, "-o", str(binary)],
                           "c++": ["clang++", "-std=c++17", entry_name, "-o", str(binary)],
                           "rust": ["rustc", entry_name, "-o", str(binary)]}[language]
            logs.append("compiling: " + " ".join(compile_cmd))
            rc, out, err = await _shell(compile_cmd, workdir, timeout=120)
            if rc != 0:
                return {"error": "compilation failed", "exit_code": rc,
                        "stdout": out[-4000:], "stderr": err[-6000:], "logs": logs}

        # ---- run under the sandbox ---------------------------------------
        run_cmd: list[str]
        if spec.get("compiled"):
            run_cmd = [str(binary)]
        elif language == "python":
            run_cmd = ["python3", entry_name]
        elif language == "javascript":
            run_cmd = ["node", entry_name]
        elif language == "typescript":
            run_cmd = ["node", "--experimental-strip-types", entry_name]
        elif language == "go":
            run_cmd = ["go", "run", entry_name]
        elif language == "java":
            run_cmd = ["java", entry_name]
        else:
            run_cmd = ["bash", entry_name]

        env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
               "HOME": str(workdir),
               "PYTHONPATH": str(workdir / "_deps"),
               "GOCACHE": str(workdir / "_gocache"),
               "TMPDIR": str(workdir)}
        profile = _profile(workdir)  # projects live in ~/.jarvis: re-allowed by workdir
        sandboxed = ["sandbox-exec", "-p", profile] + run_cmd
        logs.append("executing (sandboxed): " + " ".join(run_cmd))

        try:
            rc, out, err = await _shell(sandboxed, workdir, timeout=timeout, env=env)
        except asyncio.TimeoutError:
            return {"error": f"timed out after {timeout}s (infinite loop?)",
                    "timeout": True, "logs": logs}
        except FileNotFoundError as e:
            return {"error": f"could not launch runtime: {e}", "logs": logs}

        return {"exit_code": rc, "stdout": out[-10000:], "stderr": err[-10000:],
                "logs": logs, "seconds": round(time.time() - started, 2),
                "project": _slug(project) if persistent else None,
                "sandbox": "no network, no Apple Events, writes confined to the project "
                           "folder, private folders unreadable"}
    finally:
        if not persistent and language != "html":
            shutil.rmtree(workdir, ignore_errors=True)


def available_languages() -> list[dict]:
    return [{"language": lang,
             "available": spec["bin"] is None or shutil.which(spec["bin"]) is not None,
             "install": spec.get("install", "")}
            for lang, spec in LANGS.items()]
