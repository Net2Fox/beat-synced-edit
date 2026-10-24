#!/usr/bin/env python3
"""Create or reuse the skill's .venv, install its requirements and check readiness.

Run with any Python 3.10+ interpreter; only the standard library is used:

    python3 <skill>/scripts/bootstrap.py              # macOS / Linux
    python  <skill>\\scripts\\bootstrap.py              # Windows

An existing healthy environment is reused without reinstalling. The report names
the `edit` launcher (scripts/edit or scripts\\edit.cmd) that runs the CLI with this
environment; call it by absolute path because agent shells keep no state.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

SCRIPTS = Path(__file__).resolve().parent
# Installed skills keep runtime modules in scripts/; the repository keeps them at its root.
ROOT = SCRIPTS.parent if SCRIPTS.name == "scripts" else SCRIPTS


def venv_python(venv):
    windows = venv / "Scripts" / "python.exe"
    return windows if os.name == "nt" else venv / "bin" / "python"


def run(args, **kwargs):
    print("+ " + " ".join(str(a) for a in args), file=sys.stderr, flush=True)
    return subprocess.run([str(a) for a in args], **kwargs)


def doctor(python):
    result = run([python, "-X", "utf8", SCRIPTS / "env_doctor.py"], capture_output=True, text=True,
                 encoding="utf-8", errors="replace")
    try:
        return json.loads(result.stdout)
    except ValueError:
        return {"ready": False, "required_ready": False,
                "problems": [f"doctor could not run: {result.stderr.strip()[-2000:]}"]}


def packages_ready(report):
    return all(item["status"] == "pass" for item in report.get("checks", [])
               if item.get("required") and str(item.get("name", "")).startswith("package:"))


def helpers(python):
    """How to call the CLI. Agents should use the launcher path in every command."""
    launcher = SCRIPTS / ("edit.cmd" if os.name == "nt" else "edit")
    script = SCRIPTS / "edit_project.py"
    return {
        "launcher": str(launcher),
        "direct": f'"{python}" -X utf8 "{script}"',
        "bash": f"alias edit='{launcher.as_posix()}'",
        "powershell": f"Set-Alias edit '{SCRIPTS / 'edit.cmd'}'",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--venv", type=Path, default=ROOT / ".venv", help="Environment directory (default: <skill>/.venv)")
    parser.add_argument("--transcription", action="store_true", help="Also install optional local speech recognition")
    parser.add_argument("--lock", action="store_true", help="Install the tested pinned versions from requirements.lock.txt")
    parser.add_argument("--reinstall", action="store_true", help="Run pip even when the packages already import")
    parser.add_argument("--check", action="store_true", help="Only report; never create or install anything")
    parser.add_argument("--json", action="store_true", help="Print the final report as JSON")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 10):
        parser.exit(2, f"Python 3.10+ is required (found {sys.version.split()[0]}); 3.12 is recommended.\n")

    venv = args.venv.expanduser().resolve()
    python = venv_python(venv)
    actions = []
    if not python.is_file():
        if args.check:
            report = {"ready": False, "problems": [f"No environment at {venv}; run bootstrap without --check"]}
            print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else report["problems"][0])
            return 4
        created = run([sys.executable, "-m", "venv", venv])
        if created.returncode or not python.is_file():
            parser.exit(3, "Could not create the virtual environment. On Debian/Ubuntu install python3-venv; "
                           "otherwise check that this Python includes the venv module.\n")
        actions.append(f"created {venv}")

    report = doctor(python)
    requirements = [ROOT / ("requirements.lock.txt" if args.lock else "requirements.txt")]
    optional_missing = any(item.get("name") == "optional:faster-whisper" and item.get("status") != "pass"
                           for item in report.get("checks", []))
    if args.transcription and (optional_missing or args.reinstall):
        requirements.append(ROOT / "requirements-transcription.txt")
    needs_base = args.reinstall or not packages_ready(report)
    if not args.check and (needs_base or len(requirements) > 1):
        command = [python, "-m", "pip", "install", "--disable-pip-version-check"]
        for path in requirements if needs_base else requirements[1:]:
            command += ["-r", path]
        if run(command).returncode:
            parser.exit(3, "pip install failed; read the error above (network, proxy or a missing compiler).\n")
        actions.append("installed " + ", ".join(p.name for p in (requirements if needs_base else requirements[1:])))
        report = doctor(python)

    report["actions"] = actions or ["reused the existing environment"]
    report["helpers"] = helpers(python)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        state = "READY" if report.get("ready") else "NOT READY"
        print(f"{state}: {python}")
        for action in report["actions"]:
            print(f"- {action}")
        for problem in report.get("problems", []):
            print(f"! {problem}")
        for item in report.get("checks", []):
            if not item.get("required") and item.get("status") != "pass":
                print(f"  optional {item['name']}: {item['detail']}")
        print(f"\nLauncher (use its absolute path in every agent command): {report['helpers']['launcher']}")
        print(f"Interactive shells: bash/zsh  {report['helpers']['bash']}")
        print(f"                    PowerShell {report['helpers']['powershell']}")
    return 0 if report.get("ready") else 4


if __name__ == "__main__":
    raise SystemExit(main())
