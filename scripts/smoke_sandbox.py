"""Exercise the actual sandbox image; only Docker and host Python are required."""

import os
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree


def main():
    image = os.environ.get("SANDBOX_IMAGE", "docx-sandbox")
    common = ["docker", "run", "--rm", "--network", "none", "--read-only",
              "--tmpfs", "/tmp:size=64m", "--cap-drop", "ALL",
              "--security-opt", "no-new-privileges", "--memory", "1500m",
              "--cpus", "1", "--pids-limit", "64"]
    # Keep bind mounts under the checkout: macOS Docker runtimes may not share
    # the system's /var/folders temporary directory with the Linux VM.
    checkout = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix=".docx-smoke-", dir=checkout) as temporary:
        root = Path(temporary)
        fixtures, output = root / "fixtures", root / "out"
        fixtures.mkdir(mode=0o777)
        output.mkdir(mode=0o777)
        fixtures.chmod(0o777)
        output.chmod(0o777)
        script = root / "script.py"
        script.write_text(
            'def edit(doc, tools):\n'
            '    import re\n'
            '    tools.replace_text(doc, re.sub("test", "test", "test"), "smoke passed")\n'
        )
        script.chmod(0o644)
        subprocess.run(common + ["-v", f"{fixtures}:/fixtures:rw", image, "python", "-c",
            "from docx import Document; d=Document(); d.add_paragraph('test'); d.save('/fixtures/in.docx')"],
            check=True, timeout=60)
        result = subprocess.run(common + ["-v", f"{fixtures / 'in.docx'}:/work/in.docx:ro",
            "-v", f"{script}:/work/script.py:ro", "-v", f"{output}:/work/out:rw", image], timeout=60)
        if result.returncode:
            error = output / "error.txt"
            raise RuntimeError(error.read_text() if error.exists() else f"Sandbox exited {result.returncode}")
        with zipfile.ZipFile(output / "out.docx") as archive:
            xml = ElementTree.fromstring(archive.read("word/document.xml"))
            text = "".join(xml.itertext())
            assert "smoke passed" in text, "Sandbox produced an unchanged document"

        blocked = root / "blocked.py"
        blocked.write_text(
            'def edit(doc, tools):\n'
            '    return __builtins__["__import__"]("os")\n'
        )
        blocked_result = subprocess.run(common + ["-v", f"{fixtures / 'in.docx'}:/work/in.docx:ro",
            "-v", f"{blocked}:/work/script.py:ro", "-v", f"{output}:/work/out:rw", image], timeout=60)
        assert blocked_result.returncode != 0, "Sandbox allowed an unsupported import"
        assert "Unsupported import: os" in (output / "error.txt").read_text()
    print("Sandbox smoke test passed")


if __name__ == "__main__":
    main()
