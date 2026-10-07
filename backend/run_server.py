import platform
import uvicorn


def main() -> None:
    is_windows = platform.system().lower().startswith("win")
    # On Windows the spawned reloader can trigger intermittent subprocess
    # fdopen/KeyboardInterrupt issues. Disable the auto-reloader on Windows
    # and use it elsewhere for developer convenience.
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=(not is_windows),
    )


if __name__ == "__main__":
    main()
