import builtins
import sys
import traceback
from pathlib import Path

from docx import Document
from docxkit import DocxTools
from document_io import save_document

INPUT_PATH = "/work/in.docx"
OUTPUT_PATH = "/work/out/out.docx"
SCRIPT_PATH = "/work/script.py"
ERROR_PATH = "/work/out/error.txt"
STAGE_PATH = "/work/out/stage.txt"

_ALLOWED_IMPORTS = {"docx", "re", "html", "math", "datetime", "decimal", "collections"}
_SAFE_BUILTIN_NAMES = {
    "Exception", "IndexError", "KeyError", "RuntimeError", "StopIteration", "TypeError", "ValueError",
    "abs", "all", "any", "bool", "callable", "dict", "enumerate", "filter", "float", "int",
    "isinstance", "iter", "len", "list", "map", "max", "min", "next", "range", "reversed",
    "round", "set", "slice", "sorted", "str", "sum", "tuple", "zip",
}


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    """Import only modules that the generated-script contract permits."""
    if level or name.split(".")[0] not in _ALLOWED_IMPORTS:
        raise ImportError(f"Unsupported import: {name}")
    return builtins.__import__(name, globals, locals, fromlist, level)


_SAFE_BUILTINS = {name: getattr(builtins, name) for name in _SAFE_BUILTIN_NAMES}
_SAFE_BUILTINS["__import__"] = _safe_import


def _load_edit_function(script_path: str):
    """Load a validated user script without exposing Python's full builtins."""
    source = Path(script_path).read_text(encoding="utf-8")
    namespace = {"__builtins__": _SAFE_BUILTINS, "__name__": "user_script"}
    exec(compile(source, script_path, "exec"), namespace)
    edit = namespace.get("edit")
    if not callable(edit):
        raise AttributeError("Script must define: def edit(doc, tools) -> None")
    return edit


def main():
    try:
        Path(STAGE_PATH).write_text("importing_script")
        edit = _load_edit_function(SCRIPT_PATH)

        Path(STAGE_PATH).write_text("loading_document")
        doc = Document(INPUT_PATH)
        Path(STAGE_PATH).write_text("editing_document")
        edit(doc, DocxTools())
        Path(STAGE_PATH).write_text("saving_document")
        save_document(doc, OUTPUT_PATH)

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
