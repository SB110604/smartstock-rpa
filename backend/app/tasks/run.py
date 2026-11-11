"""Run a scheduled job immediately without Celery: `python -m app.tasks.run <job>` (e.g. backup, pipeline)."""

import json
import sys

from app.tasks import jobs

JOBS = {"pipeline": jobs.pipeline, "quick_check": jobs.quick_check, "tracking": jobs.tracking,
        "supplier_scores": jobs.supplier_scores, "weekly_models": jobs.weekly_models, "learning_daily": jobs.learning_daily,
        "approval_sla": jobs.approval_sla, "daily_summary": jobs.daily_summary, "weekly_report": jobs.weekly_report,
        "report_schedules": jobs.report_schedules, "backup": jobs.backup, "email_quotes": jobs.email_quotes}


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in JOBS:
        print(f"usage: python -m app.tasks.run [{' | '.join(JOBS)}]")
        return 2
    print(json.dumps(JOBS[name](), default=str, indent=2)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
