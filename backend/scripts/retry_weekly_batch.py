"""현재 설정의 당일 주간 배치에서 실패한 항목을 재실행한다."""

import argparse
import json
import logging

from app.outfits.bootstrap import get_weekly_outfit_batch


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    result = get_weekly_outfit_batch().retry_failed()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] in {"completed", "already_run", "no_failed_targets"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
