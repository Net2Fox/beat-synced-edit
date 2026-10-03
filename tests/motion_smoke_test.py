"""Actual local motion export, optional Remotion render, reimport and cached batch.

First run without --remotion to export the editable React project. Install its
package.json dependencies in the reported directory, then rerun with --remotion.
No dependencies are installed automatically by this test.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", default=str(ROOT / "work" / "motion-smoke"))
    parser.add_argument("--scripts-dir", default=str(ROOT))
    parser.add_argument("--remotion", action="store_true")
    parser.add_argument("--remotion-work")
    args = parser.parse_args()
    work, scripts = Path(args.work_dir).resolve(), Path(args.scripts_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)

    def save(path, data):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def cli(*values):
        command = [sys.executable, "-X", "utf8", str(scripts / "edit_project.py"), *map(str, values), "--json-brief"]
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        if completed.returncode:
            raise RuntimeError(completed.stdout + completed.stderr)
        result = json.loads(completed.stdout)
        if not result["ok"]:
            raise RuntimeError(str(result))
        return result["result"]

    spec = {"duration": 2, "fps": 24, "width": 180, "height": 320, "background": "#12385B",
            "graphics": [{"id": "hook", "kind": "card", "text": "Привет, мир!", "start_frame": 0, "end_frame": 48,
                          "rect": [.08, .2, .78, .22], "animation": "slide"},
                         {"id": "progress", "kind": "bar", "start_frame": 0, "end_frame": 48,
                          "rect": [.06, .75, .78, .025], "animation": "none"}]}
    save(work / "spec.json", spec)
    cli("motion-project", work / "spec.json", "-o", work / "project.json")
    native = cli("render", work / "project.json", "-o", work / "native.mp4")
    if native["frames"] != 48 or not native["qa"]["technical_pass"]:
        raise RuntimeError("Native motion export failed actual QA")
    react = Path(args.remotion_work).resolve() if args.remotion_work else work / "react"
    options = ["--render", work / "remotion.mp4"] if args.remotion else []
    remotion = cli("remotion-export", work / "spec.json", "--work", react, *options)
    report = {"native": native, "remotion": remotion, "remotion_status": "rendered" if args.remotion else "not_run", "visual_review": "not_reviewed"}
    if args.remotion:
        capture = cv2.VideoCapture(str(work / "remotion.mp4"))
        capture.set(cv2.CAP_PROP_POS_FRAMES, 24)
        success, frame = capture.read()
        capture.release()
        if not success:
            raise RuntimeError("Cannot inspect actual Remotion output")
        y, x = np.where(frame.min(axis=2) > 200)
        if len(x) < 30 or x.min() < 18 or x.max() > 151 or y.min() < 68 or y.max() > 130:
            raise RuntimeError("Cyrillic text is absent or clipped at the authored card boundary")
        report["text_pixel_bounds"] = [int(x.min()), int(y.min()), int(x.max()), int(y.max())]
        spec["graphics"] = [{"id": "import", "kind": "video", "source": str(work / "remotion.mp4"),
                             "start_frame": 0, "end_frame": 48, "rect": [0, 0, 1, 1], "animation": "none"}]
        save(work / "import-spec.json", spec)
        cli("motion-project", work / "import-spec.json", "-o", work / "import-project.json")
        save(work / "jobs.json", {"jobs": [{"project": "import-project.json", "output": "import.mp4"},
                                         {"project": "import-project.json", "output": "import-again.mp4"}]})
        batch = cli("batch-render", work / "jobs.json", "--work", work / "batch")
        if not batch["all_succeeded"] or batch["jobs"][1]["result"]["cache_hits"] != 1:
            raise RuntimeError("Remotion import/batch/cache workflow failed")
        report["batch"] = batch
    save(work / "evidence.json", report)
    print(json.dumps({"status": "PASS", "native_frames": 48, "remotion": report["remotion_status"],
                      "report": str(work / "evidence.json"), "remotion_directory": str(react)}, indent=2))


if __name__ == "__main__":
    main()
