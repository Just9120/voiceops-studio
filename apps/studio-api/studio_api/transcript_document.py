from __future__ import annotations

import re
from typing import Any


TRANSCRIPT_DOCUMENT_STANDARD = "transcript_doc"
TRANSCRIPT_METADATA_LABEL = "Метаданные транскрипта"
TRANSCRIPT_BODY_LABEL = "Транскрипция"
LEGACY_TRANSCRIPT_METADATA_LABEL = "Transcript metadata"
LEGACY_TRANSCRIPT_BODY_LABEL = "Transcript"
TRANSCRIPT_BODY_FONT_SIZE_PT = 11
TRANSCRIPT_SPEAKER_FONT_SIZE_PT = 14

_ENGLISH_SPEAKER_LABEL = re.compile(r"(?m)^Speaker\s+(\d+):")
_RUSSIAN_SPEAKER_LABEL = re.compile(r"(?m)^Спикер\s+\d+:")


def localize_transcript_speaker_labels(transcript_text: str) -> str:
    if not isinstance(transcript_text, str):
        raise ValueError("Transcript text must be a string")
    normalized = transcript_text.replace("\r\n", "\n").replace("\r", "\n")
    return _ENGLISH_SPEAKER_LABEL.sub(r"Спикер \1:", normalized)


def segment_transcript_for_readability(
    transcript_text: str, *, target_chars: int = 1_800,
) -> str:
    text = transcript_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    # Keep authored line breaks and speaker/timestamp layout intact.
    if "\n" in text or len(text) <= target_chars:
        return text
    paragraphs = []
    remaining = text
    while len(remaining) > target_chars:
        window = remaining[:target_chars + 1]
        whitespace = list(re.finditer(r"[^\S\n]+", window))
        if not whitespace:
            next_space = re.search(r"\s+", remaining)
            if next_space is None:
                break  # Never break an indivisible token.
            boundary = next_space.start()
        else:
            boundary = next((
                match.start() for match in reversed(whitespace)
                if match.start() >= target_chars // 2
                and match.start() > 0 and remaining[match.start() - 1] in ".!?…"
            ), whitespace[-1].start())
        paragraphs.append(remaining[:boundary])
        remaining = remaining[boundary:].lstrip()
    if remaining:
        paragraphs.append(remaining)
    return "\n\n".join(paragraphs)


def build_transcript_document_text(
    *,
    title: str,
    metadata_lines: list[str] | tuple[str, ...],
    transcript_text: str,
) -> str:
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Transcript document title is required")
    if not isinstance(metadata_lines, (list, tuple)) or not all(
        isinstance(line, str) and line.strip() for line in metadata_lines
    ):
        raise ValueError("Transcript metadata lines are required")
    body = segment_transcript_for_readability(localize_transcript_speaker_labels(transcript_text))
    metadata = "\n".join(line.strip() for line in metadata_lines)
    return (
        f"{title.strip()}\n\n{TRANSCRIPT_METADATA_LABEL}\n{metadata}\n\n"
        f"{TRANSCRIPT_BODY_LABEL}\n\n{body}"
    )


def build_transcript_document_style_requests(
    document_text: str,
    *,
    tab_id: str | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(document_text, str) or not document_text:
        raise ValueError("Transcript document text is required")
    normalized = document_text.replace("\r\n", "\n").replace("\r", "\n")
    title_end = normalized.find("\n")
    if title_end <= 0:
        raise ValueError("Transcript document title paragraph is required")
    body_marker = f"\n\n{TRANSCRIPT_BODY_LABEL}\n\n"
    marker_index = normalized.find(body_marker)
    if marker_index <= title_end:
        raise ValueError("Canonical transcript body label is required")
    body_start = marker_index + len(body_marker)

    requests: list[dict[str, Any]] = [
        {
            "updateParagraphStyle": {
                "range": _docs_range(normalized, 0, title_end + 1, tab_id),
                "paragraphStyle": {"namedStyleType": "HEADING_2"},
                "fields": "namedStyleType",
            }
        }
    ]
    if body_start < len(normalized):
        requests.append(
            {
                "updateTextStyle": {
                    "range": _docs_range(
                        normalized,
                        body_start,
                        len(normalized),
                        tab_id,
                    ),
                    "textStyle": {
                        "bold": False,
                        "fontSize": {
                            "magnitude": TRANSCRIPT_BODY_FONT_SIZE_PT,
                            "unit": "PT",
                        },
                    },
                    "fields": "bold,fontSize",
                }
            }
        )
    for match in _RUSSIAN_SPEAKER_LABEL.finditer(normalized, body_start):
        requests.append(
            {
                "updateTextStyle": {
                    "range": _docs_range(
                        normalized,
                        match.start(),
                        match.end(),
                        tab_id,
                    ),
                    "textStyle": {
                        "bold": True,
                        "fontSize": {
                            "magnitude": TRANSCRIPT_SPEAKER_FONT_SIZE_PT,
                            "unit": "PT",
                        },
                    },
                    "fields": "bold,fontSize",
                }
            }
        )
    return requests


def _docs_range(
    text: str,
    start_offset: int,
    end_offset: int,
    tab_id: str | None,
) -> dict[str, int | str]:
    if not (0 <= start_offset < end_offset <= len(text)):
        raise ValueError("Transcript document style range is invalid")
    result: dict[str, int | str] = {
        "startIndex": 1 + _utf16_length(text[:start_offset]),
        "endIndex": 1 + _utf16_length(text[:end_offset]),
    }
    if tab_id is not None:
        if not isinstance(tab_id, str) or not tab_id.strip():
            raise ValueError("Google Docs tab identity is invalid")
        result["tabId"] = tab_id
    return result


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2
