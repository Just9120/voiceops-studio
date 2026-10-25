"""Deterministic, self-contained DOCX using the canonical transcript layout.

Stable bytes permit verifying an uncertain create-only upload without treating
an edited document as the original. The opaque receipt is a hidden property,
never part of the visible transcript or a remote relationship.
"""
import io
import re
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .transcript_document import (
    TRANSCRIPT_BODY_LABEL, TRANSCRIPT_METADATA_LABEL,
    TRANSCRIPT_BODY_FONT_SIZE_PT, TRANSCRIPT_SPEAKER_FONT_SIZE_PT,
    build_transcript_document_style_requests,
)

DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOCX_OUTPUT_KIND = "yandex_disk_docx_transcript"
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_SPEAKER = re.compile(r"^(Спикер\s+\d+:)(.*)$")
_RECEIPT = re.compile(r"or_[A-Za-z0-9_-]{20,100}\Z")


def _xml(value):
    if not isinstance(value, str) or any(not (
        c in "\t\n\r" or 0x20 <= ord(c) <= 0xD7FF
        or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF
    ) for c in value):
        raise ValueError("Invalid document text")
    return escape(value)


def _run(text, *, speaker=False):
    properties = (f'<w:rPr><w:b/><w:sz w:val="{TRANSCRIPT_SPEAKER_FONT_SIZE_PT * 2}"/></w:rPr>'
                  if speaker else "")
    # Tabs are actual Word tabs; XML whitespace preservation keeps indentation.
    segments = text.split("\t")
    content = "<w:tab/>".join(f'<w:t xml:space="preserve">{_xml(part)}</w:t>' for part in segments)
    return "<w:r>" + properties + content + "</w:r>"


def render_transcript_docx(document_text: str, *, reconciliation_token: str) -> bytes:
    if not isinstance(reconciliation_token, str) or not _RECEIPT.fullmatch(reconciliation_token):
        raise ValueError("Invalid document receipt")
    # Reuse the same canonical-title/body validation as the Google renderer.
    build_transcript_document_style_requests(document_text)
    text = document_text.replace("\r\n", "\n").replace("\r", "\n")
    _xml(text)
    paragraphs = []
    in_body = False
    for index, line in enumerate(text.split("\n")):
        style = "Heading2" if index == 0 else (
            "Heading3" if not in_body and line in {TRANSCRIPT_BODY_LABEL, TRANSCRIPT_METADATA_LABEL} else "Normal")
        if line == TRANSCRIPT_BODY_LABEL and not in_body:
            in_body = True
        speaker = _SPEAKER.match(line) if in_body else None
        content = (_run(speaker[1], speaker=True) + _run(speaker[2])) if speaker else _run(line)
        paragraphs.append(f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>{content}</w:p>')
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W}"><w:body>' + "".join(paragraphs)
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
          '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>'
          '</w:sectPr></w:body></w:document>')
    styles = (f'<?xml version="1.0" encoding="UTF-8"?><w:styles xmlns:w="{_W}">'
        f'<w:docDefaults><w:rPrDefault><w:rPr><w:sz w:val="{TRANSCRIPT_BODY_FONT_SIZE_PT * 2}"/>'
        '<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/></w:rPr></w:rPrDefault></w:docDefaults>'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/>'
        '<w:pPr><w:spacing w:after="120"/></w:pPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/>'
        '<w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:outlineLvl w:val="1"/></w:pPr>'
        '<w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/>'
        '<w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:outlineLvl w:val="2"/></w:pPr>'
        '<w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style></w:styles>')
    types = ('<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/docProps/custom.xml" ContentType="application/vnd.openxmlformats-officedocument.custom-properties+xml"/>'
        '</Types>')
    relationships = ('<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties" Target="docProps/custom.xml"/>'
        '</Relationships>')
    style_relationships = ('<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>')
    properties = ('<?xml version="1.0" encoding="UTF-8"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        '<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="StudioOutputReceipt">'
        f'<vt:lpwstr>{reconciliation_token}</vt:lpwstr></property></Properties>')
    result = io.BytesIO()
    with ZipFile(result, "w", compression=ZIP_DEFLATED) as archive:
        for path, value in (("[Content_Types].xml", types), ("_rels/.rels", relationships),
                            ("word/document.xml", document), ("word/styles.xml", styles),
                            ("word/_rels/document.xml.rels", style_relationships),
                            ("docProps/custom.xml", properties)):
            info = ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 0
            info.external_attr = 0o600 << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, value.encode("utf-8"))
    return result.getvalue()
