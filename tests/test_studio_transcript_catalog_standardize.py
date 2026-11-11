from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


def _document_payload(
    text: str,
    *,
    document_id: str = "private-document",
    revision_id: str = "private-revision",
    tab_id: str = "private-tab",
    extra_tabs: tuple[dict, ...] = (),
    unsupported_element: dict | None = None,
) -> dict:
    content = [
        {
            "endIndex": 1,
            "sectionBreak": {},
        }
    ]
    if unsupported_element is not None:
        content.append(unsupported_element)
    else:
        content.append(
            {
                "startIndex": 1,
                "endIndex": len(text) + 2,
                "paragraph": {
                    "elements": [
                        {
                            "startIndex": 1,
                            "endIndex": len(text) + 2,
                            "textRun": {"content": f"{text}\n"},
                        }
                    ]
                },
            }
        )
    return {
        "documentId": document_id,
        "revisionId": revision_id,
        "tabs": [
            {
                "tabProperties": {"tabId": tab_id},
                "documentTab": {"body": {"content": content}},
            },
            *extra_tabs,
        ],
    }


def _response(status_code: int, payload: object) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("GET", "https://docs.googleapis.test"),
    )


def test_document_forbidden_is_normalized_as_per_document_rejection():
    from studio_api.transcript_catalog_standardize import (
        CatalogGoogleDocumentSnapshot,
        CatalogGoogleWriteError,
        CatalogGoogleWriteReason,
        GoogleTranscriptCatalogStandardizer,
    )

    reader = GoogleTranscriptCatalogStandardizer(
        get=lambda *args, **kwargs: _response(
            403,
            {"error": "private-google-response"},
        )
    )
    with pytest.raises(CatalogGoogleWriteError) as read_error:
        reader.read_document(
            access_token="private-access-token",
            document_id="private-document",
        )

    writer = GoogleTranscriptCatalogStandardizer(
        post=lambda *args, **kwargs: _response(
            403,
            {"error": "private-google-response"},
        )
    )
    with pytest.raises(CatalogGoogleWriteError) as write_error:
        writer.replace_document_text(
            access_token="private-access-token",
            snapshot=CatalogGoogleDocumentSnapshot(
                document_id="private-document",
                revision_id="private-revision",
                tab_id="private-tab",
                document_text="Private text",
                end_index=2,
            ),
            document_text=(
                "Title\n\nМетаданные транскрипта\n"
                "Provider: unknown\nModel: unknown\nLanguage: unknown\n"
                "Speakers: unknown\nCreated at: 2026-07-01T00:00:00Z\n\n"
                "Транскрипция\n\nReplacement"
            ),
        )

    assert (
        read_error.value.reason
        == CatalogGoogleWriteReason.request_rejected
    )
    assert (
        write_error.value.reason
        == CatalogGoogleWriteReason.request_rejected
    )
    for raised in (read_error.value, write_error.value):
        rendered = str(raised)
        assert "private-access-token" not in rendered
        assert "private-document" not in rendered
        assert "private-google-response" not in rendered


def test_standardized_text_preserves_authoritative_metadata_and_body():
    from studio_api.transcript_catalog_standardize import (
        build_standardized_transcript_document_text,
    )
    from studio_api.transcript_catalog_migration import (
        CatalogDocumentStandardStatus,
    )
    from studio_api.transcript_catalog_scan import (
        classify_transcript_document_standard,
    )

    body = (
        "First sentence. Second sentence. Third sentence. "
        "Fourth sentence."
    )
    legacy = (
        "Old title\n\nTranscript metadata\n"
        "Source file: private-source.mp3\n"
        "Source mode: Google Drive\n"
        "Provider: ElevenLabs\n"
        "Model: scribe_v2\n"
        "Language: Русский\n"
        "Speakers: no\n"
        "Created at: 2026-06-02T10:26:00Z\n"
        "Segment project: Tivali\n"
        "Segment time range: 00:00-end\n"
        "Original source: Lecture.mp4\n\n"
        f"Transcript\n\n{body}"
    )

    result = build_standardized_transcript_document_text(
        document_name="Actual Drive title",
        existing_document_text=legacy,
        created_time="2026-05-01T00:00:00Z",
    )

    assert result.startswith(
        "Actual Drive title\n\nМетаданные транскрипта\n"
    )
    assert "Source file:" not in result
    assert "Source mode:" not in result
    assert "Provider: ElevenLabs" in result
    assert "Model: scribe_v2" in result
    assert "Language: Русский" in result
    assert "Speakers:" not in result
    assert "Created at: 2026-05-01T00:00:00Z" in result
    assert "Segment project:" not in result
    assert "Segment time range: 00:00-end" in result
    assert "Original source: Lecture.mp4" in result
    assert body in result
    assert (
        classify_transcript_document_standard(
            result,
            authoritative_created_at=datetime(
                2026, 5, 1, tzinfo=timezone.utc
            ),
        )
        == CatalogDocumentStandardStatus.current
    )


def test_unstructured_standardization_does_not_infer_settings():
    from studio_api.transcript_catalog_standardize import (
        build_standardized_transcript_document_text,
    )
    from studio_api.transcript_document import segment_transcript_for_readability

    body = "One sentence. Two sentence. Three sentence."
    result = build_standardized_transcript_document_text(
        document_name="Existing transcript",
        existing_document_text=f"Existing transcript\n\n{body}",
        created_time="2026-07-01T12:34:56Z",
    )

    assert "Provider: unknown" in result
    assert "Model: unknown" in result
    assert "Language: unknown" in result
    assert "Speakers:" not in result
    assert "Created at: 2026-07-01T12:34:56Z" in result
    assert "ElevenLabs" not in result
    assert "scribe_v2" not in result
    assert segment_transcript_for_readability(
        body,
        target_chars=15,
    ) == "One sentence.\n\nTwo sentence.\n\nThree sentence."


@pytest.mark.parametrize("punctuation", [".", ""])
def test_long_unbroken_transcript_is_segmented_and_recognized_in_existing_docs(punctuation):
    from studio_api.job_google_docs_output import format_transcript_doc
    from studio_api.transcript_catalog_migration import CatalogDocumentStandardStatus
    from studio_api.transcript_catalog_scan import classify_transcript_document_standard
    from studio_api.transcript_catalog_standardize import build_standardized_transcript_document_text

    speech = " ".join(f"Сохраняем смысл, порядок, термины и отрицания {index}{punctuation}" for index in range(200))
    formatted = format_transcript_doc(
        title="Лекция", transcript_text=speech, job_language="ru",
        detected_language_code=None, created_at=None,
    ).body
    header, body = formatted.split("\n\nТранскрипция\n\n", 1)
    assert len(body.split("\n\n")) > 1
    assert body.split() == speech.split()
    old = header + "\n\nТранскрипция\n\n" + speech
    assert classify_transcript_document_standard(old) == CatalogDocumentStandardStatus.outdated
    repaired = build_standardized_transcript_document_text(
        document_name="Лекция", existing_document_text=old, created_time=None,
    )
    assert repaired.split("\n\nТранскрипция\n\n", 1)[1] == body
    assert classify_transcript_document_standard(repaired) == CatalogDocumentStandardStatus.current


def test_standardized_text_replaces_opaque_timestamp_with_authority():
    from studio_api.transcript_catalog_standardize import (
        build_standardized_transcript_document_text,
    )

    result = build_standardized_transcript_document_text(
        document_name="unknown",
        existing_document_text=(
            "Old\n\nTranscript metadata\n"
            "Provider: unknown\n"
            "Model: unknown\n"
            "Language: unknown\n"
            "Speakers: unknown\n"
            "Created at: imported before timestamp policy\n\n"
            "Transcript\n\nBody"
        ),
        created_time="2026-07-01T12:34:56Z",
    )

    assert result.startswith("unknown\n\nМетаданные транскрипта\n")
    assert "Created at: 2026-07-01T12:34:56Z" in result
    assert "Created at: imported before timestamp policy" not in result


def test_legacy_standardization_preserves_existing_created_at_without_source():
    from studio_api.transcript_catalog_standardize import (
        build_standardized_transcript_document_text,
    )

    result = build_standardized_transcript_document_text(
        document_name="Legacy dated",
        existing_document_text=(
            "Old\n\nTranscript metadata\n"
            "Provider: ElevenLabs\nModel: scribe_v2\nLanguage: ru\n"
            "Speakers: yes\nCreated at: 2026-06-02T13:26:00+03:00\n\n"
            "Transcript\n\nBody"
        ),
        created_time=None,
    )

    assert result.count("Created at:") == 1
    assert "Created at: 2026-06-02T13:26:00+03:00" in result


def test_unstructured_legacy_header_preserves_date_outside_named_sections():
    from studio_api.transcript_catalog_standardize import (
        build_standardized_transcript_document_text,
    )

    result = build_standardized_transcript_document_text(
        document_name="Legacy dated",
        existing_document_text=(
            "Legacy dated\n\nProvider: ElevenLabs\n"
            "Created at: 2026-06-02T13:26:00+03:00\n\n"
            "Private body without section markers"
        ),
        created_time=None,
    )

    assert result.count("Created at:") == 1
    assert "Created at: 2026-06-02T13:26:00+03:00" in result
    assert result.endswith("Private body without section markers")


def test_legacy_standardization_omits_missing_or_invalid_created_at():
    from studio_api.transcript_catalog_migration import (
        CatalogDocumentStandardStatus,
    )
    from studio_api.transcript_catalog_scan import (
        classify_transcript_document_standard,
    )
    from studio_api.transcript_catalog_standardize import (
        build_standardized_transcript_document_text,
    )

    for original in (
        "Old\n\nBody",
        (
            "Old\n\nTranscript metadata\nProvider: unknown\n"
            "Model: unknown\nLanguage: unknown\nSpeakers: unknown\n"
            "Created at: unknown\n\nTranscript\n\nBody"
        ),
    ):
        result = build_standardized_transcript_document_text(
            document_name="Legacy undated",
            existing_document_text=original,
            created_time=None,
        )

        assert "Created at:" not in result
        assert (
            classify_transcript_document_standard(result)
            == CatalogDocumentStandardStatus.current
        )


def test_standardizer_reads_one_tab_and_redacts_private_snapshot():
    from studio_api.transcript_catalog_standardize import (
        CATALOG_STANDARDIZATION_GET_FIELDS,
        GoogleTranscriptCatalogStandardizer,
    )

    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return _response(200, _document_payload("Title\n\nBody"))

    snapshot = GoogleTranscriptCatalogStandardizer(get=get).read_document(
        access_token="private-access-token",
        document_id="private-document",
    )

    assert calls[0][0].endswith("/private-document")
    assert calls[0][1]["params"] == {
        "fields": CATALOG_STANDARDIZATION_GET_FIELDS,
        "includeTabsContent": "true",
        "suggestionsViewMode": "SUGGESTIONS_INLINE",
    }
    assert calls[0][1]["headers"]["Authorization"] == (
        "Bearer private-access-token"
    )
    assert snapshot.document_text == "Title\n\nBody"
    redacted = repr(snapshot)
    for private in (
        "private-document",
        "private-revision",
        "private-tab",
        "Title",
        "Body",
    ):
        assert private not in redacted


def test_standardizer_accepts_omitted_zero_index_on_initial_section_break():
    from studio_api.transcript_catalog_standardize import (
        normalize_standardization_snapshot,
    )

    payload = _document_payload("Title\n\nPlain text body")
    first = payload["tabs"][0]["documentTab"]["body"]["content"][0]
    assert "startIndex" not in first

    snapshot = normalize_standardization_snapshot(
        payload,
        expected_document_id="private-document",
    )

    assert snapshot.document_text == "Title\n\nPlain text body"


def test_standardizer_rejects_multiple_tabs_and_non_text_content():
    from studio_api.transcript_catalog_standardize import (
        CatalogGoogleWriteError,
        CatalogGoogleWriteReason,
        normalize_standardization_snapshot,
    )

    extra = {
        "tabProperties": {"tabId": "second-tab"},
        "documentTab": {"body": {"content": []}},
    }
    with pytest.raises(CatalogGoogleWriteError) as multiple:
        normalize_standardization_snapshot(
            _document_payload("Body", extra_tabs=(extra,)),
            expected_document_id="private-document",
        )
    assert multiple.value.reason == CatalogGoogleWriteReason.multiple_tabs

    with pytest.raises(CatalogGoogleWriteError) as unsupported:
        normalize_standardization_snapshot(
            _document_payload(
                "Body",
                unsupported_element={
                    "startIndex": 1,
                    "endIndex": 5,
                    "table": {},
                },
            ),
            expected_document_id="private-document",
        )
    assert (
        unsupported.value.reason
        == CatalogGoogleWriteReason.unsupported_content
    )

    payload = _document_payload("Body")
    payload["tabs"][0]["documentTab"]["headers"] = {
        "private-header": {"content": []}
    }
    with pytest.raises(CatalogGoogleWriteError) as hidden_content:
        normalize_standardization_snapshot(
            payload,
            expected_document_id="private-document",
        )
    assert (
        hidden_content.value.reason
        == CatalogGoogleWriteReason.unsupported_content
    )

    payload = _document_payload("Body")
    payload["tabs"][0]["documentTab"]["body"]["content"][0][
        "startIndex"
    ] = 2
    with pytest.raises(CatalogGoogleWriteError) as noninitial_break:
        normalize_standardization_snapshot(
            payload,
            expected_document_id="private-document",
        )
    assert (
        noninitial_break.value.reason
        == CatalogGoogleWriteReason.unsupported_content
    )


def test_in_place_standardization_uses_revision_and_same_document():
    from studio_api.transcript_catalog_migration import (
        CatalogDocumentStandardStatus,
    )
    from studio_api.transcript_catalog_standardize import (
        GoogleTranscriptCatalogStandardizer,
        standardize_transcript_document_in_place,
    )

    old_text = "Actual title\n\nA transcript body."
    posts = []

    def get(url, **kwargs):
        return _response(200, _document_payload(old_text))

    def post(url, **kwargs):
        posts.append((url, kwargs))
        return _response(200, {"documentId": "private-document"})

    result = standardize_transcript_document_in_place(
        access_token="private-access-token",
        document_id="private-document",
        document_name="Actual title",
        expected_status=CatalogDocumentStandardStatus.unstructured,
        created_time="2026-07-01T00:00:00Z",
        standardizer=GoogleTranscriptCatalogStandardizer(
            get=get,
            post=post,
        ),
    )

    assert result.status == CatalogDocumentStandardStatus.current
    assert result.changed is True
    assert len(posts) == 1
    url, kwargs = posts[0]
    assert url.endswith("/private-document:batchUpdate")
    assert kwargs["json"]["writeControl"] == {
        "requiredRevisionId": "private-revision"
    }
    delete, insert, heading, body_style = kwargs["json"]["requests"]
    assert delete == {
        "deleteContentRange": {
            "range": {
                "startIndex": 1,
                "endIndex": len(old_text) + 1,
                "tabId": "private-tab",
            }
        }
    }
    assert insert["insertText"]["location"] == {
        "index": 1,
        "tabId": "private-tab",
    }
    inserted_text = insert["insertText"]["text"]
    assert "Provider: unknown" in inserted_text
    assert "A transcript body." in inserted_text
    assert heading["updateParagraphStyle"]["paragraphStyle"] == {
        "namedStyleType": "HEADING_2"
    }
    assert body_style["updateTextStyle"]["textStyle"] == {
        "bold": False,
        "fontSize": {"magnitude": 11, "unit": "PT"},
    }
    encoded = json.dumps(result.__dict__)
    for private in (
        "private-access-token",
        "private-document",
        "private-revision",
        "A transcript body.",
    ):
        assert private not in encoded


def test_in_place_standardization_localizes_and_styles_speaker_labels():
    from studio_api.transcript_catalog_migration import (
        CatalogDocumentStandardStatus,
    )
    from studio_api.transcript_catalog_standardize import (
        GoogleTranscriptCatalogStandardizer,
        standardize_transcript_document_in_place,
    )

    legacy = (
        "Call\n\nTranscript metadata\n"
        "Provider: ElevenLabs\nModel: scribe_v2\nLanguage: ru\n"
        "Speakers: yes\nCreated at: 2026-07-01T00:00:00Z\n\n"
        "Transcript\n\nSpeaker 1:\nPrivate body"
    )
    posts = []

    result = standardize_transcript_document_in_place(
        access_token="private-access-token",
        document_id="private-document",
        document_name="Call",
        expected_status=CatalogDocumentStandardStatus.outdated,
        created_time="2026-07-01T00:00:00Z",
        standardizer=GoogleTranscriptCatalogStandardizer(
            get=lambda *args, **kwargs: _response(
                200,
                _document_payload(legacy),
            ),
            post=lambda url, **kwargs: (
                posts.append((url, kwargs))
                or _response(200, {"documentId": "private-document"})
            ),
        ),
    )

    assert result.changed is True
    requests = posts[0][1]["json"]["requests"]
    inserted = requests[1]["insertText"]["text"]
    assert "Спикер 1:\nPrivate body" in inserted
    assert "Speaker 1:" not in inserted
    speaker_style = requests[-1]["updateTextStyle"]
    assert speaker_style["textStyle"] == {
        "bold": True,
        "fontSize": {"magnitude": 14, "unit": "PT"},
    }


def test_current_document_is_idempotent_and_does_not_write():
    from studio_api.transcript_catalog_migration import (
        CatalogDocumentStandardStatus,
    )
    from studio_api.transcript_catalog_standardize import (
        GoogleTranscriptCatalogStandardizer,
        standardize_transcript_document_in_place,
    )

    current = (
        "Title\n\nМетаданные транскрипта\n"
        "Provider: unknown\nModel: unknown\nLanguage: unknown\n"
        "Speakers: unknown\nCreated at: 2026-07-01T00:00:00Z\n\n"
        "Транскрипция\n\nBody"
    )
    posts = []
    standardizer = GoogleTranscriptCatalogStandardizer(
        get=lambda *args, **kwargs: _response(
            200,
            _document_payload(current),
        ),
        post=lambda *args, **kwargs: posts.append((args, kwargs)),
    )

    result = standardize_transcript_document_in_place(
        access_token="private-access-token",
        document_id="private-document",
        document_name="Title",
        expected_status=CatalogDocumentStandardStatus.outdated,
        created_time="2026-07-01T00:00:00Z",
        standardizer=standardizer,
    )

    assert result.changed is False
    assert result.status == CatalogDocumentStandardStatus.current
    assert posts == []


def test_changed_classification_and_revision_rejection_fail_closed():
    from studio_api.transcript_catalog_migration import (
        CatalogDocumentStandardStatus,
    )
    from studio_api.transcript_catalog_standardize import (
        CatalogGoogleWriteError,
        CatalogGoogleWriteReason,
        GoogleTranscriptCatalogStandardizer,
        standardize_transcript_document_in_place,
    )

    standardizer = GoogleTranscriptCatalogStandardizer(
        get=lambda *args, **kwargs: _response(
            200,
            _document_payload("Title\n\nBody"),
        ),
        post=lambda *args, **kwargs: _response(
            400,
            {"error": {"message": "private raw Google error"}},
        ),
    )
    with pytest.raises(CatalogGoogleWriteError) as changed:
        standardize_transcript_document_in_place(
            access_token="private-access-token",
            document_id="private-document",
            document_name="Title",
            expected_status=CatalogDocumentStandardStatus.outdated,
            created_time="2026-07-01T00:00:00Z",
            standardizer=standardizer,
        )
    assert (
        changed.value.reason
        == CatalogGoogleWriteReason.classification_changed
    )

    with pytest.raises(CatalogGoogleWriteError) as rejected:
        standardize_transcript_document_in_place(
            access_token="private-access-token",
            document_id="private-document",
            document_name="Title",
            expected_status=CatalogDocumentStandardStatus.unstructured,
            created_time="2026-07-01T00:00:00Z",
            standardizer=standardizer,
        )
    assert (
        rejected.value.reason
        == CatalogGoogleWriteReason.revision_conflict_or_rejected
    )
    assert "private raw Google error" not in str(rejected.value)


def test_empty_transcript_is_never_rewritten():
    from studio_api.transcript_catalog_migration import (
        CatalogDocumentStandardStatus,
    )
    from studio_api.transcript_catalog_standardize import (
        CatalogGoogleWriteError,
        CatalogGoogleWriteReason,
        GoogleTranscriptCatalogStandardizer,
        standardize_transcript_document_in_place,
    )

    posts = []
    with pytest.raises(CatalogGoogleWriteError) as raised:
        standardize_transcript_document_in_place(
            access_token="private-access-token",
            document_id="private-document",
            document_name="Title",
            expected_status=CatalogDocumentStandardStatus.unstructured,
            created_time="2026-07-01T00:00:00Z",
            standardizer=GoogleTranscriptCatalogStandardizer(
                get=lambda *args, **kwargs: _response(
                    200,
                    _document_payload("Title"),
                ),
                post=lambda *args, **kwargs: posts.append((args, kwargs)),
            ),
        )
    assert raised.value.reason == CatalogGoogleWriteReason.empty_transcript
    assert posts == []
