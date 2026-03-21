import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.config import get_settings
from services.preflight import preflight_report


def main() -> int:
    settings = get_settings()
    report = preflight_report(settings)
    print(json.dumps(report, indent=2))
    return 0 if report.get("healthy", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
