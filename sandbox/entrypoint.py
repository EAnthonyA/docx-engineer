import sys
import traceback
import importlib.util
from pathlib import Path

from docx import Document
from docxkit import DocxTools

INPUT_PATH = "/work/in.docx"
OUTPUT_PATH = "/work/out/out.docx"
SCRIPT_PATH = "/work/script.py"
ERROR_PATH = "/work/out/error.txt"


def main():
    try:
        spec = importlib.util.spec_from_file_location("user_script", SCRIPT_PATH)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load script from {SCRIPT_PATH}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, "edit"):
            raise AttributeError(
                "Script must define: def edit(doc, tools) -> None"
            )

        doc = Document(INPUT_PATH)
        module.edit(doc, DocxTools())
        doc.save(OUTPUT_PATH)

        if not Path(OUTPUT_PATH).exists():
            raise FileNotFoundError(
                f"edit() finished but produced no output at {OUTPUT_PATH}"
            )

        sys.exit(0)

    except Exception:
        tb = traceback.format_exc()
        try:
            Path(ERROR_PATH).write_text(tb, encoding="utf-8")
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
