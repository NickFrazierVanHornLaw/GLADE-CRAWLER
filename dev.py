# dev.py
import os
import uvicorn
from pathlib import Path

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "1") == "1"  # turn off in prod
    # Keep the watcher focused so it starts immediately
    project_dir = str(Path(__file__).parent.resolve())
    glade_dir = str(Path(project_dir, "glade").resolve())

    uvicorn.run(
        "server:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=[project_dir, glade_dir],
        reload_includes=["*.py"],
        reload_excludes=[".venv/*", "**/__pycache__/*", "**/*.log", "**/*.png", "**/*.pdf"],
        workers=1,
        log_level=os.getenv("LOG_LEVEL", "info"),
    )
