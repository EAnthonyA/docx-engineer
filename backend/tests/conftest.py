import sys
from pathlib import Path

# docxkit.py ships in the sandbox container as a top-level module. Put the
# sandbox dir on sys.path so the backend test suite can import and exercise it
# directly (it only depends on python-docx, which is in the backend env).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox"))
