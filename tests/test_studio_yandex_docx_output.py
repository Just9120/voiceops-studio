"""DOCX formatting, complete content and non-destructive upload recovery."""
import io
from pathlib import Path
import sys
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
from studio_api.transcript_document import build_transcript_document_text
from studio_api.transcript_docx import DOCX_MIME_TYPE, render_transcript_docx
from studio_api.yandex_disk import YandexDiskError, resource_from_payload
from studio_api.yandex_docx_output import bind_document_receipt, ensure_document, prepare_document_upload

TOKEN = "or_" + "t" * 43
W = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def document():
    return build_transcript_document_text(title="Созвон 25.10.2026 & планы",
        metadata_lines=("Provider: ElevenLabs", "Model: scribe_v2", "Language: ru"),
        transcript_text="Спикер 1:\nОбсудим <план> & задачи.\n\nСпикер 2: Да, согласен.\n  Отступ\tтабуляция 🙂")


def upload():
    return prepare_document_upload(folder_path="disk:/Созвоны", title="Созвон 25.10.2026",
        document_text=document(), reconciliation_token=TOKEN)


def metadata(item, **kwargs):
    payload = {"resource_id": "opaque", "path": item.path, "name": item.path.rsplit("/", 1)[1],
        "type": "file", "size": item.size_bytes, "mime_type": DOCX_MIME_TYPE,
        "sha256": item.sha256, "md5": item.md5, "created": "2026-10-25T12:00:00Z"}
    payload.update(kwargs)
    return resource_from_payload(payload)


class Disk:
    def __init__(self, resource=None, *, payload=None, write_error=None):
        self.resource = resource
        self.payload = payload
        self.write_error = write_error
        self.writes = 0
        self.downloads = 0

    def metadata(self, path):
        if self.resource is None:
            raise YandexDiskError("not_found")
        assert self.resource.path == path
        return self.resource

    def upload_new(self, path, content):
        self.writes += 1
        if self.write_error:
            raise YandexDiskError(self.write_error)
        self.payload = content
        self.resource = metadata(upload())
        return self.resource

    def download_to(self, resource, target, *, maximum_bytes, check):
        self.downloads += 1
        assert len(self.payload) <= maximum_bytes
        check()
        target.write(self.payload)
        return len(self.payload)


def test_docx_preserves_complete_visible_text_and_formats_speakers_without_visible_receipt():
    text = document()
    content = render_transcript_docx(text, reconciliation_token=TOKEN)
    assert content == render_transcript_docx(text, reconciliation_token=TOKEN)
    with ZipFile(io.BytesIO(content)) as package:
        assert package.testzip() is None
        for name in package.namelist():
            ET.fromstring(package.read(name))
        root = ET.fromstring(package.read("word/document.xml"))
        lines = []
        for paragraph in root.findall(".//w:body/w:p", W):
            lines.append("".join(node.text or "" if node.tag.endswith("}t") else "\t"
                for node in paragraph.iter() if node.tag in {"{" + W["w"] + "}t", "{" + W["w"] + "}tab"}))
        assert "\n".join(lines) == text
        assert TOKEN.encode() not in package.read("word/document.xml")
        assert TOKEN.encode() in package.read("docProps/custom.xml")
        speaker_runs = [r for r in root.findall(".//w:r", W) if r.find("w:rPr/w:b", W) is not None]
        assert len(speaker_runs) == 2
        assert all(r.find("w:rPr/w:sz", W).get("{" + W["w"] + "}val") == "28" for r in speaker_runs)
        styles = ET.fromstring(package.read("word/styles.xml"))
        assert styles.find("w:docDefaults/w:rPrDefault/w:rPr/w:sz", W).get("{" + W["w"] + "}val") == "22"
        assert b"TargetMode=\"External\"" not in b"".join(package.read(n) for n in package.namelist())


def test_receipt_changes_bytes_but_never_visible_transcript():
    assert render_transcript_docx(document(), reconciliation_token=TOKEN) != render_transcript_docx(
        document(), reconciliation_token="or_" + "x" * 43)
    with pytest.raises(ValueError):
        render_transcript_docx(document() + "\0", reconciliation_token=TOKEN)
    with pytest.raises(ValueError):
        render_transcript_docx(document(), reconciliation_token="invalid")


@pytest.mark.parametrize("title", ["../созвон", "audio/docx", "recording.DOCX"])
def test_filename_stays_direct_child_of_selected_folder(title):
    item = prepare_document_upload(folder_path="disk:/Folder", title=title,
        document_text=document(), reconciliation_token=TOKEN)
    assert item.path.rpartition("/")[0] == "disk:/Folder"
    assert item.path.lower().endswith(".docx")
    assert "Созвон" not in repr(item) and document() not in repr(item)


def test_create_only_then_recover_lost_ack_does_not_upload_again():
    item = upload()
    disk = Disk()
    result = ensure_document(disk, item)
    assert result.path == item.path and disk.writes == 1
    assert ensure_document(disk, item) == result
    assert disk.writes == 1 and disk.downloads == 0


@pytest.mark.parametrize("change", [
    {"sha256": "0" * 64}, {"md5": "0" * 32}, {"size": 1},
    {"mime_type": "text/plain"}, {"type": "dir"},
])
def test_changed_user_document_is_conflict_without_writing(change):
    item = upload()
    disk = Disk(metadata(item, **change))
    with pytest.raises(YandexDiskError, match="document_conflict"):
        ensure_document(disk, item)
    assert disk.writes == disk.downloads == 0


def test_missing_strong_hash_is_verified_by_content_not_name_or_md5():
    item = upload()
    disk = Disk(metadata(item, sha256=None), payload=item.content)
    assert ensure_document(disk, item).path == item.path
    assert disk.downloads == 1 and disk.writes == 0
    disk.payload = b"x" * item.size_bytes
    with pytest.raises(YandexDiskError, match="document_conflict"):
        ensure_document(disk, item)
    assert disk.writes == 0


@pytest.mark.parametrize("reason", ["quota_exceeded", "permission_denied", "timeout"])
def test_failed_upload_is_not_success_or_silent_overwrite(reason):
    disk = Disk(write_error=reason)
    with pytest.raises(YandexDiskError, match=reason):
        ensure_document(disk, upload())
    assert disk.writes == 1 and disk.resource is None


def test_concurrent_create_conflict_requires_exact_content_readback():
    item = upload()
    disk = Disk()
    def concurrent_upload(path, content):
        disk.resource = metadata(item)
        raise YandexDiskError("conflict")
    disk.upload_new = concurrent_upload
    assert ensure_document(disk, item).path == item.path


def test_cancellation_prevents_new_upload():
    disk = Disk()
    def cancel():
        raise RuntimeError("cancelled")
    with pytest.raises(RuntimeError, match="cancelled"):
        ensure_document(disk, upload(), check=cancel)
    assert disk.writes == 0


def test_durable_receipt_cannot_be_rebound_to_different_bytes_or_provider():
    case = SimpleNamespace(expected_output_provider="yandex_disk", expected_docx_path=None,
        expected_document_sha256=None, expected_document_md5=None, expected_document_size_bytes=None)
    item = upload()
    bind_document_receipt(case, item)
    bind_document_receipt(case, item)
    other = prepare_document_upload(folder_path="disk:/Созвоны", title="Созвон 25.10.2026",
        document_text=document() + " изменено", reconciliation_token=TOKEN)
    with pytest.raises(YandexDiskError, match="document_conflict"):
        bind_document_receipt(case, other)
    assert case.expected_document_sha256 == item.sha256
    case.expected_output_provider = "google_drive"
    with pytest.raises(YandexDiskError, match="receipt_scope_mismatch"):
        bind_document_receipt(case, item)
