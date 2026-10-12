"""Exercise the Rust-only sandbox image against a minimal DOCX fixture."""

import os
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree


def _write_fixture(path: Path) -> None:
    """Create the smallest Word package needed by the worker without Python in it."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>""",
        )
        archive.writestr(
            "word/document.xml",
            """<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>test</w:t></w:r></w:p><w:sectPr/></w:body></w:document>""",
        )


def main():
    image = os.environ.get("RUST_SANDBOX_IMAGE", "docx-sandbox-rust")
    common = ["docker", "run", "--rm", "--network", "none", "--read-only",
              "--tmpfs", "/tmp:size=64m", "--cap-drop", "ALL",
              "--security-opt", "no-new-privileges", "--memory", "1500m",
              "--cpus", "1", "--pids-limit", "64"]
    checkout = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix=".docx-smoke-", dir=checkout) as temporary:
        root = Path(temporary)
        output = root / "out"
        output.mkdir(mode=0o777)
        output.chmod(0o777)
        source = root / "in.docx"
        plan = root / "plan.json"
        script = root / "script.rhai"
        _write_fixture(source)
        plan.write_text(
            '{"schema_version":1,"operations":[{"id":"replace","type":"replace_text","locations":["body"],"search":"test","replacement":"smoke passed","match_case":true}]}'
        )
        result = subprocess.run(
            common + ["-v", f"{source}:/work/in.docx:ro", "-v", f"{plan}:/work/plan.json:ro",
                      "-v", f"{output}:/work/out:rw", image,
                      "/usr/local/bin/docx-engineer-rust", "--input", "/work/in.docx",
                      "--plan", "/work/plan.json", "--output", "/work/out/out.docx"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode:
            raise RuntimeError(result.stderr or f"Rust sandbox exited {result.returncode}")
        with zipfile.ZipFile(output / "out.docx") as archive:
            xml = ElementTree.fromstring(archive.read("word/document.xml"))
            text = "".join(xml.itertext())
            assert "smoke passed" in text, "Sandbox produced an unchanged document"

        script.write_text('for location in ["body"] { replace_text("test", "rhai passed", location); }')
        scripted = subprocess.run(
            common + ["-v", f"{source}:/work/in.docx:ro", "-v", f"{script}:/work/script.rhai:ro",
                      "-v", f"{output}:/work/out:rw", image,
                      "/usr/local/bin/docx-engineer-rust", "--input", "/work/in.docx",
                      "--script", "/work/script.rhai", "--output", "/work/out/scripted.docx"],
            capture_output=True, text=True, timeout=60,
        )
        if scripted.returncode:
            raise RuntimeError(scripted.stderr or f"Rhai sandbox exited {scripted.returncode}")
        with zipfile.ZipFile(output / "scripted.docx") as archive:
            xml = ElementTree.fromstring(archive.read("word/document.xml"))
            assert "rhai passed" in "".join(xml.itertext()), "Rhai script produced an unchanged document"

        script.write_text('import "os" as os;')
        blocked = subprocess.run(
            common + ["-v", f"{source}:/work/in.docx:ro", "-v", f"{script}:/work/script.rhai:ro",
                      "-v", f"{output}:/work/out:rw", image,
                      "/usr/local/bin/docx-engineer-rust", "--input", "/work/in.docx",
                      "--script", "/work/script.rhai", "--output", "/work/out/blocked.docx"],
            capture_output=True, text=True, timeout=60,
        )
        assert blocked.returncode != 0, "Sandbox accepted an unregistered Rhai import"
    print("Sandbox smoke test passed")


if __name__ == "__main__":
    main()
