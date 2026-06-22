import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.migrations import run_migrations


if __name__ == "__main__":
    applied = run_migrations()
    if applied:
        print("Applied migrations:")
        for version in applied:
            print(f"- {version}")
    else:
        print("No pending migrations.")
