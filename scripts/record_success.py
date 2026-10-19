"""Record verified updates at most once every 30 days, without credentials/prices."""
import json
from datetime import datetime, timedelta
from pathlib import Path


def record_success(report_path, record_path):
    report = json.loads(report_path.read_text(encoding="utf-8"))
    completed = datetime.fromisoformat(report["completed_at"])
    if {s["sheet"] for s in report["sheets"]} != {"ETF", "股票", "基金", "买入标的"}:
        raise ValueError("Missing successful sheet updates")
    if any(len(s["latest_dates"]) != s["assets"] for s in report["sheets"]):
        raise ValueError("Missing asset data")
    if record_path.exists():
        previous = json.loads(record_path.read_text(encoding="utf-8"))
        last = datetime.fromisoformat(previous["completed_at"])
        if completed - last < timedelta(days=30):
            print("Success record is less than 30 days old; no commit needed.")
            return False
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Updated monthly success record.")
    return True


if __name__ == "__main__":
    record_success(Path("run-status.json"), Path(".github/last-success.json"))
