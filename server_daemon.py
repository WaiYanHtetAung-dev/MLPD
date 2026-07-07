import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path


def redirect_streams(stdout_log: Path, stderr_log: Path) -> None:
    stdout_log.parent.mkdir(parents=True, exist_ok=True)
    stderr_log.parent.mkdir(parents=True, exist_ok=True)
    stdout = open(stdout_log, "a", encoding="utf-8", buffering=1)
    stderr = open(stderr_log, "a", encoding="utf-8", buffering=1)
    sys.stdout = stdout
    sys.stderr = stderr
    if hasattr(os, "dup2"):
        os.dup2(stdout.fileno(), 1)
        os.dup2(stderr.fileno(), 2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MLPD as a detached background server.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--stdout-log", required=True)
    parser.add_argument("--stderr-log", required=True)
    parser.add_argument("--pid-file", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    os.chdir(root)

    runtime_temp = root / ".runtime-temp"
    runtime_temp.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(runtime_temp)
    os.environ["TMP"] = str(runtime_temp)

    redirect_streams(Path(args.stdout_log), Path(args.stderr_log))
    Path(args.pid_file).write_text(str(os.getpid()), encoding="utf-8")

    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    print(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] Starting MLPD server on port {args.port}", flush=True)

    import uvicorn

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=args.port,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()
