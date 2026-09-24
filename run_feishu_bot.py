"""Run the Feishu bot while rotating captured stdout and stderr logs."""

from __future__ import annotations

import argparse
import runpy
import sys
import traceback
from pathlib import Path

from log_rotation import RotatingTextStream


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdout-log", required=True)
    parser.add_argument("--stderr-log", required=True)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    stdout_path = Path(args.stdout_log)
    stderr_path = Path(args.stderr_log)
    if not stdout_path.is_absolute():
        stdout_path = root / stdout_path
    if not stderr_path.is_absolute():
        stderr_path = root / stderr_path

    original_stdout = sys.stdout
    original_stderr = sys.stderr
    stdout_stream = RotatingTextStream(stdout_path)
    same_log = stdout_path.resolve() == stderr_path.resolve()
    stderr_stream = stdout_stream if same_log else RotatingTextStream(stderr_path)
    sys.stdout = stdout_stream
    sys.stderr = stderr_stream

    exit_code = 0
    try:
        runpy.run_path(str(root / "feishu_bot.py"), run_name="__main__")
    except SystemExit as error:
        if error.code not in (None, 0):
            print(error.code, file=stderr_stream)
            exit_code = error.code if isinstance(error.code, int) else 1
    except BaseException:
        traceback.print_exc(file=stderr_stream)
        exit_code = 1
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        stdout_stream.close()
        if not same_log:
            stderr_stream.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
