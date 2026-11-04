from __future__ import annotations

import sys
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))

from studio_api.google_drive import (
    GOOGLE_FOLDER_MIME_TYPE,
    GoogleDriveFolderChildren,
    GoogleDriveMetadata,
    GoogleDriveMetadataError,
    list_drive_folder_children,
)
from studio_api.google_drive_folder_intake import (
    DriveFolderIntakeError,
    DriveFolderIntakeReason,
    drive_folder_preview_token,
    inspect_drive_source_folder,
)


def metadata(
    item_id: str,
    name: str,
    mime_type: str,
    *,
    size: int | None = 10,
    created_time: str | None = "2026-08-20T10:00:00Z",
):
    return GoogleDriveMetadata(
        item_id,
        name,
        mime_type,
        size,
        f"https://drive.google.com/file/d/{item_id}/view",
        created_time,
        None,
        mime_type == GOOGLE_FOLDER_MIME_TYPE,
    )


def inspect(children, *, max_upload_bytes=100):
    root = metadata("root", "Calls", GOOGLE_FOLDER_MIME_TYPE, size=None)

    def fetch_children(_token, folder_id, _page_size, page_token):
        return children[(folder_id, page_token)]

    return inspect_drive_source_folder(
        "access",
        "root",
        max_upload_bytes=max_upload_bytes,
        metadata_fetcher=lambda _token, _folder_id: root,
        children_fetcher=fetch_children,
    )


def test_preview_confirmation_is_invalidated_by_same_size_content_revision_change():
    from dataclasses import replace
    first = replace(metadata("audio", "call.mp3", "audio/mpeg"), head_revision_id="v1", md5_checksum="a"*32)
    changed = replace(first, head_revision_id="v2", md5_checksum="b"*32)
    previews = [inspect({("root", None): GoogleDriveFolderChildren("root", [item], None)}) for item in (first, changed)]
    tokens = [drive_folder_preview_token(preview, owner_user_id="owner", project_id="project") for preview in previews]
    assert tokens[0] != tokens[1]


def test_recursive_preview_is_deterministic_and_classifies_skips():
    nested = metadata("nested", "Nested", GOOGLE_FOLDER_MIME_TYPE, size=None)
    children = {
        ("root", None): GoogleDriveFolderChildren(
            "root",
            [
                metadata("unsupported", "notes.pdf", "application/pdf"),
                nested,
                metadata("b", "b.mp4", "video/mp4"),
                metadata("empty", "empty.mp3", "audio/mpeg", size=0),
            ],
            None,
        ),
        ("nested", None): GoogleDriveFolderChildren(
            "nested",
            [
                metadata("large", "large.ogg", "application/ogg", size=101),
                metadata("a", "a.mp3", "audio/mpeg"),
                metadata("no-created", "old.wav", "audio/wav", created_time=None),
            ],
            None,
        ),
    }

    preview = inspect(children)

    assert preview.complete is True
    assert preview.blocker is None
    assert preview.total_file_count == 6
    assert preview.folder_count == 2
    assert [item.metadata.id for item in preview.accepted] == ["b", "a"]
    assert [item.relative_path for item in preview.accepted] == [
        "Calls/b.mp4",
        "Calls/Nested/a.mp3",
    ]
    assert {item.reason.value for item in preview.skipped} == {
        "unsupported",
        "empty",
        "oversized",
        "creation_time_unavailable",
    }
    assert len(drive_folder_preview_token(
        preview, owner_user_id="owner", project_id="project"
    )) == 64


def test_preview_token_changes_on_metadata_or_binding_drift():
    children = {
        ("root", None): GoogleDriveFolderChildren(
            "root", [metadata("a", "a.mp3", "audio/mpeg")], None
        )
    }
    preview = inspect(children)
    token = drive_folder_preview_token(
        preview, owner_user_id="owner", project_id="project"
    )
    changed = {
        ("root", None): GoogleDriveFolderChildren(
            "root", [metadata("a", "renamed.mp3", "audio/mpeg")], None
        )
    }
    assert drive_folder_preview_token(
        inspect(changed), owner_user_id="owner", project_id="project"
    ) != token
    assert drive_folder_preview_token(
        preview, owner_user_id="other", project_id="project"
    ) != token


def test_more_than_fifty_supported_files_fails_closed_without_truncation():
    children = {
        ("root", None): GoogleDriveFolderChildren(
            "root",
            [
                metadata(str(index), f"{index:02}.mp3", "audio/mpeg")
                for index in range(51)
            ],
            None,
        )
    }
    preview = inspect(children)
    assert preview.blocker == "over_limit"
    assert preview.complete is False
    assert preview.supported_count == 51
    assert preview.accepted == ()
    with pytest.raises(ValueError):
        drive_folder_preview_token(
            preview, owner_user_id="owner", project_id="project"
        )


@pytest.mark.parametrize(
    ("children", "reason"),
    [
        (
            {
                ("root", None): GoogleDriveFolderChildren(
                    "root",
                    [metadata("root", "Cycle", GOOGLE_FOLDER_MIME_TYPE, size=None)],
                    None,
                )
            },
            DriveFolderIntakeReason.cycle,
        ),
        (
            {
                ("root", None): GoogleDriveFolderChildren(
                    "root", [], "same-token"
                ),
                ("root", "same-token"): GoogleDriveFolderChildren(
                    "root", [], "same-token"
                ),
            },
            DriveFolderIntakeReason.repeated_page_token,
        ),
    ],
)
def test_traversal_rejects_cycles_and_repeated_page_tokens(children, reason):
    with pytest.raises(DriveFolderIntakeError) as exc:
        inspect(children)
    assert exc.value.reason == reason


def test_duplicate_ids_across_folders_fail_closed():
    children = {
        ("root", None): GoogleDriveFolderChildren(
            "root",
            [
                metadata("nested", "Nested", GOOGLE_FOLDER_MIME_TYPE, size=None),
                metadata("same", "same.mp3", "audio/mpeg"),
            ],
            None,
        ),
        ("nested", None): GoogleDriveFolderChildren(
            "nested", [metadata("same", "same.mp3", "audio/mpeg")], None
        ),
    }
    with pytest.raises(DriveFolderIntakeError) as exc:
        inspect(children)
    assert exc.value.reason == DriveFolderIntakeReason.duplicate_id


def test_drive_children_transport_rejects_malformed_or_partial_payload(monkeypatch):
    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    import studio_api.google_drive as google_drive

    monkeypatch.setattr(
        google_drive,
        "urlopen",
        lambda *_args, **_kwargs: Response(
            {
                "files": [
                    {
                        "id": "file-a",
                        "name": "a.mp3",
                        "mimeType": "audio/mpeg",
                        "size": "10",
                        "createdTime": "2026-08-20T10:00:00Z",
                    }
                ],
                "nextPageToken": "next",
            }
        ),
    )
    page = list_drive_folder_children("access", "root")
    assert [item.id for item in page.items] == ["file-a"]
    assert page.next_page_token == "next"

    monkeypatch.setattr(
        google_drive,
        "urlopen",
        lambda *_args, **_kwargs: Response({"nextPageToken": "next"}),
    )
    with pytest.raises(GoogleDriveMetadataError):
        list_drive_folder_children("access", "root")
