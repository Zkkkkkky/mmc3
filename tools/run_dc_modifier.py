from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def main() -> int:
    self_test = "--self-test" in sys.argv
    try:
        from dc_modifier.app import run

        return run()
    except Exception as error:
        if self_test:
            return 90
        raise SystemExit(
            "修改器启动失败。若使用源码版，请先安装 requirements-modifier.txt；"
            f"错误：{error}"
        ) from error


if __name__ == "__main__":
    raise SystemExit(main())
