"""Evaluation harness.

    # Score the latest agent run against the sample labels
    python -m edvak_forge.evaluation

    # Run the agent first, then score
    python -m edvak_forge.evaluation --agent

    # Score a different message set (e.g. the unseen extra set)
    python -m edvak_forge.evaluation --agent --messages data/messages_extra.json \
        --labels data/labels_extra.json

    # Copy results into reports/<name>/ (committed to git) for the submission
    python -m edvak_forge.evaluation --publish sample-40

    # Exit with code 1 if any emergency was missed or any safety rule broken (for CI)
    python -m edvak_forge.evaluation --strict

Writes eval.json and report.md into the run directory.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from ..clinic.repository import ClinicRepository
from ..config import REPO_ROOT, load_settings
from .metrics import evaluate
from .report import pct, render


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Score an agent run against labels.")
    p.add_argument("--run", type=Path, default=REPO_ROOT / "runs" / "latest")
    p.add_argument("--labels", type=Path, default=REPO_ROOT / "data" / "labels_sample.json")
    p.add_argument("--messages", type=Path, default=REPO_ROOT / "data" / "messages_sample.json")
    p.add_argument("--details", type=Path, default=None,
                   help="Booking constraints (default: data/label_details_<set>.json if present)")
    p.add_argument("--agent", action="store_true", help="Run the agent on --messages first")
    p.add_argument("--transport", choices=["stdio", "inprocess"], default="stdio")
    p.add_argument("--publish", metavar="NAME", help="Also copy outputs to reports/NAME/")
    p.add_argument("--strict", action="store_true",
                   help="Exit 1 on any missed emergency, must_not violation or invariant issue")
    args = p.parse_args(argv)

    if args.agent:
        from ..agent.runner import main as run_agent
        out = REPO_ROOT / "runs" / f"eval-{args.messages.stem}"
        code = run_agent(["--messages", str(args.messages), "--out", str(out),
                          "--transport", args.transport])
        if code:
            return code
        args.run = out

    for name in ("results.json", "traces.json", "run_log.json", "summary.json"):
        if not (args.run / name).exists():
            print(f"Missing {args.run / name}. Run the agent first "
                  "(python -m edvak_forge.agent.runner) or pass --agent.", file=sys.stderr)
            return 2

    settings = load_settings()
    details_path = args.details or args.labels.with_name(
        args.labels.name.replace("labels_", "label_details_"))
    details = load(details_path) if details_path.exists() else None
    ev = evaluate(
        results=load(args.run / "results.json"), labels=load(args.labels),
        traces=load(args.run / "traces.json"), run_log=load(args.run / "run_log.json"),
        summary=load(args.run / "summary.json"),
        repo=ClinicRepository.load(settings.data_dir), today=settings.today,
        messages=load(args.messages) if args.messages.exists() else None,
        details=details,
    )
    title = f"Evaluation: {args.labels.stem.replace('labels_', '')} messages"
    report = render(ev, title=title, run_dir=args.run.name)
    (args.run / "eval.json").write_text(json.dumps(ev, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.run / "report.md").write_text(report, encoding="utf-8")

    h = ev["headline"]
    print(f"Fully correct: {h['fully_correct']}/{h['messages']} | emergency recall "
          f"{pct(h['emergency_recall'])} | urgency {pct(h['urgency_accuracy'])} | actions exact "
          f"{pct(h['action_exact_match'])} | must_not violations {h['must_not_violations']} | "
          f"invariant issues {h['safety_invariant_issues']}")
    if h["emergencies_missed"]:
        print(f"MISSED EMERGENCIES: {h['emergencies_missed']}")
    print(f"Report: {args.run / 'report.md'}")

    if args.publish:
        dest = REPO_ROOT / "reports" / args.publish
        dest.mkdir(parents=True, exist_ok=True)
        for name in ("results.json", "eval.json", "report.md", "summary.json", "traces.json", "run_log.json"):
            shutil.copy2(args.run / name, dest / name)
        print(f"Published to {dest}")

    if args.strict and (h["emergencies_missed"] or h["must_not_violations"] or h["safety_invariant_issues"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
