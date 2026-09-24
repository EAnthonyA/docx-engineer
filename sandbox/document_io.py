"""Write DOCX XML directly into its ZIP member without a full XML byte copy.

This follows python-docx 1.1.2's package writer, including before_marshal,
content types, binary parts and relationships. Keep the equivalence test when
upgrading python-docx, since its content-types builder is a private API.
"""

from zipfile import ZIP_DEFLATED, ZipFile

from docx.opc.part import XmlPart
from docx.opc.pkgwriter import _ContentTypesItem
from lxml import etree


def save_document(doc, path):
    package = doc.part.package
    for part in package.parts:
        part.before_marshal()
    parts = package.parts
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _ContentTypesItem.from_parts(parts).blob)
        archive.writestr("_rels/.rels", package.rels.xml)
        for part in parts:
            name = part.partname.membername
            if isinstance(part, XmlPart):
                with archive.open(name, "w") as member:
                    etree.ElementTree(part.element).write(
                        member, encoding="UTF-8", xml_declaration=True, standalone=True,
                    )
            else:
                archive.writestr(name, part.blob)
            if part.rels:
                archive.writestr(part.partname.rels_uri.membername, part.rels.xml)
