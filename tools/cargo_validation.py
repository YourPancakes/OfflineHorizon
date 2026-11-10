#!/usr/bin/env python3
"""Run Cargo with a task-local cache when Cargo's Windows TLS transport fails.

Uses verified HTTPS downloads through the system curl, checks Cargo.lock SHA-256,
and writes only under target/validation-cargo-home. User Cargo config/credentials
are neither copied nor changed. Example:
    python tools/cargo_validation.py test --locked -p horizon-client --lib
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib

try:
    from . import lab
except ImportError:
    import lab

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"


def main():
    source_home = Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo"))
    cache_home = ROOT / "target" / "validation-cargo-home"
    cargo = shutil.which("cargo") or str(source_home / "bin" / ("cargo.exe" if os.name == "nt" else "cargo"))
    curl = shutil.which("curl.exe" if os.name == "nt" else "curl")
    if not curl or not Path(cargo).is_file():
        sys.exit("Cargo and system curl are required")
    indexes = sorted((source_home / "registry" / "index").glob("index.crates.io-*"))
    if not indexes:
        sys.exit("No existing public crates.io index; use normal Cargo first")
    index = indexes[0]
    target_index = cache_home / "registry" / "index" / index.name
    if not target_index.exists():
        target_index.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(index, target_index)
    archive_dir = cache_home / "registry" / "cache" / index.name
    archive_dir.mkdir(parents=True, exist_ok=True)
    packages = {
        (p["name"], p["version"]): p["checksum"]
        for p in tomllib.loads((ROOT / "Cargo.lock").read_text(encoding="utf-8"))["package"]
        if p.get("source") == REGISTRY
    }
    for (name, version) in packages:
        filename = f"{name}-{version}.crate"
        cached = source_home / "registry" / "cache" / index.name / filename
        destination = archive_dir / filename
        if cached.is_file() and not destination.exists():
            shutil.copy2(cached, destination)
    env = dict(os.environ)
    env["CARGO_HOME"] = str(cache_home)
    env["CARGO_NET_OFFLINE"] = "true"
    env["CARGO_HTTP_TIMEOUT"] = "10"
    env["CARGO_NET_RETRY"] = "0"
    env["PATH"] = str(source_home / "bin") + os.pathsep + env.get("PATH", "")
    data_root = ROOT / "target" / "validation-data"
    data_root.mkdir(parents=True, exist_ok=True)
    data = Path(tempfile.mkdtemp(prefix="run-", dir=data_root))
    for variable, folder in {
        "HORIZON_HOME": "game", "HORIZON_LAUNCHER_HOME": "launcher",
        "XDG_DATA_HOME": "xdg-data", "XDG_CONFIG_HOME": "xdg-config",
        "HORIZON_LAUNCHER_TRASH": "trash", "HORIZON_LAUNCHER_CLIPBOARD": "clipboard",
        "HORIZON_LAUNCHER_DESKTOP": "desktop",
    }.items():
        destination = data / folder
        destination.mkdir()
        env[variable] = str(destination)
    env = lab.game_env(env)
    env["HORIZON_TELEMETRY_URL"] = "off"
    env.setdefault("CARGO_BUILD_JOBS", "1")
    env["PYTHONUTF8"] = "1"
    env["CARGO_TERM_COLOR"] = "never"
    env.setdefault("RUST_TEST_THREADS", "1")
    arguments = sys.argv[1:]
    if not arguments:
        sys.exit("Supply a Cargo command")
    while True:
        command = ([sys.executable, *arguments[1:]] if arguments[0] == "--python"
                   else [cargo, "--offline", *arguments])
        lines = []
        with subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                              errors="replace") as process:
            for line in process.stdout:
                lines.append(line)
                print(line, end="", flush=True)
            result = subprocess.CompletedProcess(command, process.wait(), stdout="".join(lines), stderr="")
        output = result.stdout
        missing = (re.search(r"failed to download `([^ ]+) v([^`]+)`", output)
                   if result.returncode and arguments[0] != "--python" else None)
        if not missing:
            return result.returncode
        name, version = missing.groups()
        expected = packages.get((name, version))
        if expected is None:
            print(output, end="")
            sys.exit("Refusing a download absent from Cargo.lock")
        archive = archive_dir / f"{name}-{version}.crate"
        if archive.exists():
            print(output, end="")
            sys.exit("Cargo rejected an existing cached archive")
        temporary = archive.with_suffix(".part")
        url = f"https://static.crates.io/crates/{name}/{name}-{version}.crate"
        print(f"Fetching locked dependency {name} {version}", flush=True)
        download = subprocess.run(
            [curl, "--fail", "--location", "--silent", "--show-error",
             "--connect-timeout", "10", "--max-time", "60",
             "--output", str(temporary), url],
        )
        if download.returncode:
            temporary.unlink(missing_ok=True)
            return download.returncode
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        if digest != expected:
            temporary.unlink(missing_ok=True)
            sys.exit(f"Cargo.lock checksum mismatch for {name} {version}")
        temporary.replace(archive)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--background":
        label = sys.argv[2]
        if re.fullmatch(r"[A-Za-z0-9_-]+", label) is None:
            sys.exit("Invalid validation label")
        directory = ROOT / "target" / "validation-results"
        directory.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, HORIZON_VALIDATION_LABEL=label)
        with (directory / f"{label}.log").open("w", encoding="utf-8") as log:
            child = subprocess.Popen(
                [sys.executable, "-u", str(Path(__file__).resolve()), *sys.argv[3:]],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
        print(f"Started {label}: PID {child.pid}")
    else:
        label = os.environ.get("HORIZON_VALIDATION_LABEL")
        status = ROOT / "target" / "validation-results" / f"{label}.json"
        if label:
            status.write_text(json.dumps({"running": True, "pid": os.getpid()}), encoding="utf-8")
        try:
            code = main()
        except SystemExit as error:
            code = error.code if isinstance(error.code, int) else 1
            if error.code and not isinstance(error.code, int):
                print(error.code, file=sys.stderr)
        except Exception:
            if label:
                status.write_text(json.dumps({"running": False, "exit_code": 1}), encoding="utf-8")
            raise
        if label:
            status.write_text(json.dumps({"running": False, "exit_code": code}), encoding="utf-8")
        raise SystemExit(code)

