"""Unit tests for pure text-processing helpers in the Colab workflow.

The canonical runtime file is a Colab-exported script with top-level shell magic,
Colab auth, widget setup, and Google service initialization.  Importing it in a
normal pytest process would either be invalid Python or trigger runtime side
effects, so these tests execute only the helper function definitions extracted
from the source file.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
import re
import time
import uuid

import pytest
from contextlib import contextmanager, nullcontext
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from typing import Optional
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SOURCE = ROOT / "elevenlabs_api.py"
HELPER_NAMES = {
    "normalize_speaker_project_data",
    "create_speaker_project",
    "rename_speaker_project",
    "archive_speaker_project",
    "add_project_speaker",
    "rename_project_speaker",
    "deactivate_project_speaker",
    "parse_google_doc_url_or_id",
    "docs_text_len",
    "detect_speakers_metadata_value",
    "detect_speaker_turns",
    "extract_meaningful_speaker_samples",
    "summarize_speaker_turns",
    "parse_speaker_mapping",
    "get_active_project_speaker_roster_snapshot",
    "speaker_mapping_text_fingerprint",
    "active_project_speaker_roster_fingerprint",
    "build_speaker_rename_plan",
    "apply_speaker_label_renames_to_plain_text",
    "build_startup_timing_summary",
    "build_timing_analysis",
    "build_transcript_metadata_lines",
    "upsert_transcript_document",
    "write_title_and_text_to_doc",
    "read_colab_stt_reservations",
    "write_colab_stt_reservations",
    "reserve_colab_stt",
    "complete_colab_stt_reservation",
    "resolve_colab_stt_reservation",
    "transcribe_guarded_colab_source",
    "complete_guarded_colab_source",
    "localize_transcript_speaker_labels",
    "build_structured_transcript_document_text",
    "find_structured_transcript_section_indices",
    "split_unstructured_transcript_header",
    "build_transcript_doc_style_requests",
    "build_backfilled_transcript_document_text",
    "chunk_text_for_docs",
    "extract_unstructured_transcript_body_for_backfill",
    "format_transcript_metadata_value",
    "get_existing_google_doc_created_at_source",
    "resolve_existing_google_doc_created_at",
    "extract_existing_transcript_created_at",
    "format_visible_transcript_timestamp",
    "is_preservable_transcript_timestamp",
    "existing_google_doc_backfill_metadata_needs_refresh",
    "extract_structured_transcript_metadata_values",
    "is_visible_transcript_timestamp",
    "is_structured_transcript_document_text",
    "normalize_doc_plain_text",
    "segment_plain_transcript_for_docs",
    "normalize_text_for_overlap_match",
    "trim_duplicate_prefix_by_token_overlap",
    "merge_transcript_parts_with_overlap",
    "get_openai_split_reason",
    "find_nearby_silence_split_point",
    "choose_openai_split_duration",
    "create_openai_audio_chunk",
    "split_openai_audio_if_needed",
    "format_openai_chunk_size",
    "format_openai_chunk_seconds",
    "build_openai_chunk_timing_diagnostics",
    "print_openai_chunk_timing_diagnostics",
    "get_openai_diarize_chunking_preflight_warning",
    "collect_existing_google_docs_for_standardization",
    "build_docs_only_standardized_transcript_document_text",
    "standardize_existing_google_docs_in_folder",
    "json_sha256",
    "read_manifest_file_raw_by_id",
    "read_manifest_file_by_id",
    "load_manifest_read_only",
    "normalize_manifest_data",
    "make_manifest_default",
    "make_manifest_v2_default",
    "is_manifest_v2",
    "should_skip_by_manifest",
    "parse_iso_datetime",
    "normalize_authoritative_source_created_at",
    "extract_embedded_media_creation_candidates",
    "resolve_source_creation_authority",
    "with_source_creation_authority",
    "get_runtime_language_code",
    "get_language_mode_label",
    "build_existing_google_doc_manifest_signature",
    "get_manifest_entry",
    "classify_existing_google_doc_transcript_standard",
    "build_existing_google_doc_link",
    "extract_google_doc_id_from_url",
    "build_transcript_standard_check",
    "standard_check_from_structured_status",
    "build_manifest_v2_document_entry",
    "normalize_manifest_source_entry",
    "put_manifest_source_entry",
    "with_output_folder_context",
    "upsert_manifest_v2_document_for_completed_source",
    "link_manifest_v2_source_to_document",
    "refresh_manifest_v2_summary",
    "build_manifest_v2_from_existing_manifest_and_docs",
    "comparable_manifest_v2_for_material_change",
    "manifest_v2_material_changes_needed",
    "create_manifest_backup",
    "write_active_manifest_v2",
    "clear_manifest_catalog",
    "build_manifest_clear_report_text",
    "standardize_manifest_to_v2_for_existing_google_docs",
    "is_existing_google_doc_registry_entry",
    "find_manifest_entries_referencing_google_doc",
    "build_existing_google_doc_manifest_entry",
    "build_existing_google_doc_manifest_document_entry",
    "existing_google_doc_manifest_document_needs_update",
    "comparable_standard_check_observation",
    "comparable_manifest_source_meta",
    "existing_google_doc_manifest_entry_needs_update",
    "upsert_existing_google_doc_manifest_entry",
    "register_existing_google_docs_in_manifest",
    "set_manifest_entry",
    "mark_manifest_in_progress",
    "mark_manifest_done",
    "mark_manifest_failed",
    "merge_manifest_data",
    "save_manifest",
    "summarize_manifest_catalog_for_report",
    "comparable_manifest_v2_document_for_report",
    "build_standardize_existing_docs_report_text",
    "print_standardize_existing_docs_report",
    "yes_no",
    "build_standardize_manifest_v2_report_text",
    "print_standardize_manifest_v2_report",
    "is_supported_filename",
    "normalize_local_folder_relative_path",
    "make_local_folder_upload_state",
    "accumulate_local_folder_upload_event",
    "finalize_local_folder_upload",
    "validate_drive_multi_selected_items",
    "summarize_drive_multi_selection",
    "get_drive_source_double_click_action",
    "format_timing_line",
    "parse_user_segment_time",
    "validate_user_segment_label",
    "parse_user_segment_plan",
    "make_user_segment_builder_row",
    "get_initial_user_segment_builder_rows",
    "add_user_segment_builder_row",
    "remove_last_user_segment_builder_row",
    "normalize_user_segment_builder_rows",
    "get_user_segment_builder_start_labels",
    "validate_user_segment_builder_add_result",
    "validate_user_segment_builder_add_end",
    "try_add_user_segment_builder_row",
    "normalize_optional_user_segment_document_title",
    "build_user_segments_from_builder",
    "validate_user_segment_document_title",
    "build_user_segment_requested_document_titles",
    "reject_duplicate_user_segment_requested_titles",
    "allocate_user_segment_document_titles",
    "apply_user_segment_document_titles",
    "get_existing_document_names_from_index",
    "build_user_segment_preview_text",
    "user_segment_mode_unavailable_message",
    "build_user_segment_source_signature",
    "build_user_segment_source_name",
    "build_user_segment_meta",
    "create_user_segment_media_file",
    "cleanup_user_segment_paths",
    "process_user_segments_for_source",
    "count_user_segment_conflict_hits",
    "build_safe_user_segment_source_check_text",
}


def load_text_helpers() -> dict[str, object]:
    """Load selected pure helper definitions without importing Colab runtime code."""

    source = CANONICAL_SOURCE.read_text(encoding="utf-8")
    python_source = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("!")
    )
    module = ast.parse(python_source, filename=str(CANONICAL_SOURCE))

    selected_nodes: list[ast.stmt] = []
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {
                    "DOC_INSERT_CHUNK_SIZE",
                    "DOC_REPLACEMENT_MAX_BYTES",
                    "COLAB_STT_RESERVATION_HEADER",
                    "COLAB_STT_RESERVATION_MAX_CHARS",
                    "STRUCTURED_TRANSCRIPT_METADATA_LABEL",
                    "STRUCTURED_TRANSCRIPT_BODY_LABEL",
                    "LEGACY_STRUCTURED_TRANSCRIPT_METADATA_LABEL",
                    "LEGACY_STRUCTURED_TRANSCRIPT_BODY_LABEL",
                    "STRUCTURED_TRANSCRIPT_REQUIRED_METADATA_PREFIXES",
                    "STRUCTURED_TRANSCRIPT_DATE_METADATA_PREFIX",
                    "STRUCTURED_TRANSCRIPT_OPTIONAL_METADATA_PREFIXES",
                    "STRUCTURED_TRANSCRIPT_LEGACY_METADATA_PREFIXES",
                    "FOLDER_MIME",
                    "DOC_MIME",
                    "DOCS_ONLY_STANDARDIZATION_SOURCE_FILE",
                    "DOCS_ONLY_STANDARDIZATION_SOURCE_MODE",
                    "DOCS_ONLY_STANDARDIZATION_DEFAULT_MAX_FOLDERS_SCANNED",
                    "DOCS_ONLY_STANDARDIZATION_DEFAULT_MAX_GOOGLE_DOCS_SCANNED",
                    "DOCS_ONLY_STANDARDIZATION_NESTED_FOLDER_HINT",
                    "EXISTING_DOCS_BACKFILL_METADATA_DEFAULTS_SOURCE",
                    "EXISTING_DOCS_BACKFILL_SPEAKERS_ENABLED",
                    "EXISTING_DOCS_BACKFILL_LANGUAGE",
                    "EXISTING_DOCS_BACKFILL_PROVIDER_MODEL",
                    "EXISTING_DOCS_BACKFILL_PROVIDER",
                    "MANIFEST_CACHE",
                    "MANIFEST_FILE_NAME",
                    "MANIFEST_FOLDER_NAME",
                    "STATE_FOLDER_NAME",
                    "EXISTING_GOOGLE_DOC_MANIFEST_NOTICE",
                    "EXISTING_GOOGLE_DOC_REGISTRATION_MODE",
                    "EXISTING_GOOGLE_DOC_MANIFEST_STATUS",
                    "EXISTING_GOOGLE_DOC_MANIFEST_STANDARD",
                    "EXISTING_GOOGLE_DOC_STRUCTURED_UNREADABLE",
                    "EXISTING_GOOGLE_DOC_STRUCTURED_UNSTRUCTURED",
                    "EXISTING_GOOGLE_DOC_STRUCTURED_OUTDATED",
                    "EXISTING_GOOGLE_DOC_STRUCTURED_CURRENT",
                    "TRANSCRIPT_STANDARD_CHECKER_VERSION",
                    "TRANSCRIPT_STANDARD_TARGET",
                    "DEFAULT_LANGUAGE_MODE",
                    "MANIFEST_BACKUP_FOLDER_NAME",
                    "MANIFEST_V2_TARGET_VERSION",
                    "MANIFEST_V2_SCHEMA",
                    "AUDIO_EXTENSIONS",
                    "VIDEO_EXTENSIONS",
                    "SUPPORTED_EXTENSIONS",
                    "STARTUP_TIMING_PHASES",
                    "STARTUP_TIMING_VARIABILITY_NOTE",
                    "STARTUP_BOOTSTRAP_LIMITATION_NOTE",
                    "SPEAKER_TURN_LABEL_RE",
                    "OPENAI_UPLOAD_LIMIT_BYTES",
                    "OPENAI_SEGMENT_TARGET_BYTES",
                    "OPENAI_PROVIDER_MAX_DURATION_SECONDS",
                    "OPENAI_SEGMENT_TARGET_DURATION_SECONDS",
                    "OPENAI_MIN_SPLIT_DURATION_SECONDS",
                    "OPENAI_SPLIT_OVERLAP_SECONDS",
                    "OPENAI_SILENCE_SEARCH_BEFORE_SECONDS",
                    "OPENAI_SILENCE_NOISE_LEVEL",
                    "OPENAI_SILENCE_MIN_DURATION_SECONDS",
                    "OPENAI_MERGE_MAX_OVERLAP_TOKENS",
                    "OPENAI_MERGE_MIN_OVERLAP_TOKENS",
                    "OPENAI_PREP_AUDIO_BITRATE",
                    "OPENAI_PREP_AUDIO_CHANNELS",
                    "PROJECT_TEMP_PREFIX",
                    "SOURCE_CREATION_TAG_KEYS",
                    "MANIFEST_CLEAR_CONFIRMATION",
                    "LOCAL_FOLDER_UPLOAD_CHUNK_BYTES",
                    "LOCAL_FOLDER_UPLOAD_MAX_FILES",
                    "LOCAL_FOLDER_UPLOAD_MAX_FILE_BYTES",
                    "LOCAL_FOLDER_UPLOAD_MAX_TOTAL_BYTES",
                    "LOCAL_FOLDER_UPLOAD_MAX_RELATIVE_PATH_CHARS",
                    "LOCAL_FOLDER_UPLOAD_MAX_DEPTH",
                }:
                    selected_nodes.append(node)
                    break
        elif isinstance(node, ast.ClassDef) and node.name == "RunTimer":
            selected_nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in HELPER_NAMES:
            selected_nodes.append(node)

    found_names = {
        node.name for node in selected_nodes if isinstance(node, ast.FunctionDef)
    }
    assert found_names == HELPER_NAMES

    helper_module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(helper_module)

    namespace: dict[str, object] = {
        "hashlib": hashlib,
        "base64": base64,
        "json": json,
        "datetime": datetime,
        "timedelta": timedelta,
        "timezone": timezone,
        "re": re,
        "time": time,
        "uuid": uuid,
        "contextmanager": contextmanager,
        "nullcontext": nullcontext,
        "Optional": Optional,
        "Path": Path,
        "_STARTUP_TOTAL_STARTED": time.perf_counter(),
        "os": os,
        "subprocess": __import__("subprocess"),
        "tempfile": __import__("tempfile"),
        "get_media_duration_seconds": lambda _path: 0.0,
        "MANIFEST_IN_PROGRESS_TTL_HOURS": 12,
        "list_drive_folder_children": lambda _folder_id: [],
        "find_file_in_folder": lambda _folder_id, _file_name: None,
        "read_manifest_file_by_id": lambda _file_id: {"version": 1, "entries": {}},
        "get_or_create_manifest_file": lambda: (_ for _ in ()).throw(AssertionError("get_or_create_manifest_file called")),
        "extract_google_doc_plain_text": lambda _document_id: "",
        "write_title_and_text_to_doc": lambda **_kwargs: None,
        "load_manifest": lambda: {"version": 1, "entries": {}},
        "save_manifest": lambda _manifest: None,
        "utc_now_iso": lambda: "2026-06-01T00:00:00+00:00",
    }
    exec(compile(helper_module, str(CANONICAL_SOURCE), "exec"), namespace)
    namespace["read_google_doc_for_edit"] = lambda document_id: {
        "document_id": document_id,
        "revision_id": "fixture-revision",
        "end_index": 20,
        "text": namespace["extract_google_doc_plain_text"](document_id),
    }
    return namespace


HELPERS = load_text_helpers()
write_google_doc = HELPERS["write_title_and_text_to_doc"]
HELPERS["write_title_and_text_to_doc"] = lambda **_kwargs: None
build_transcript_metadata_lines = HELPERS["build_transcript_metadata_lines"]
localize_transcript_speaker_labels = HELPERS["localize_transcript_speaker_labels"]
build_structured_transcript_document_text = HELPERS["build_structured_transcript_document_text"]
build_transcript_doc_style_requests = HELPERS["build_transcript_doc_style_requests"]
build_backfilled_transcript_document_text = HELPERS["build_backfilled_transcript_document_text"]
chunk_text_for_docs = HELPERS["chunk_text_for_docs"]
extract_unstructured_transcript_body_for_backfill = HELPERS["extract_unstructured_transcript_body_for_backfill"]
format_transcript_metadata_value = HELPERS["format_transcript_metadata_value"]
format_visible_transcript_timestamp = HELPERS["format_visible_transcript_timestamp"]
existing_google_doc_backfill_metadata_needs_refresh = HELPERS["existing_google_doc_backfill_metadata_needs_refresh"]
extract_existing_transcript_created_at = HELPERS["extract_existing_transcript_created_at"]
resolve_existing_google_doc_created_at = HELPERS["resolve_existing_google_doc_created_at"]
get_existing_google_doc_created_at_source = HELPERS["get_existing_google_doc_created_at_source"]
is_structured_transcript_document_text = HELPERS["is_structured_transcript_document_text"]
normalize_doc_plain_text = HELPERS["normalize_doc_plain_text"]
segment_plain_transcript_for_docs = HELPERS["segment_plain_transcript_for_docs"]
trim_duplicate_prefix_by_token_overlap = HELPERS["trim_duplicate_prefix_by_token_overlap"]
merge_transcript_parts_with_overlap = HELPERS["merge_transcript_parts_with_overlap"]
get_openai_split_reason = HELPERS["get_openai_split_reason"]
choose_openai_split_duration = HELPERS["choose_openai_split_duration"]
split_openai_audio_if_needed = HELPERS["split_openai_audio_if_needed"]
build_openai_chunk_timing_diagnostics = HELPERS["build_openai_chunk_timing_diagnostics"]
get_openai_diarize_chunking_preflight_warning = HELPERS[
    "get_openai_diarize_chunking_preflight_warning"
]
collect_existing_google_docs_for_standardization = HELPERS[
    "collect_existing_google_docs_for_standardization"
]
build_docs_only_standardized_transcript_document_text = HELPERS[
    "build_docs_only_standardized_transcript_document_text"
]
standardize_existing_google_docs_in_folder = HELPERS["standardize_existing_google_docs_in_folder"]

build_standardize_existing_docs_report_text = HELPERS["build_standardize_existing_docs_report_text"]
print_standardize_existing_docs_report = HELPERS["print_standardize_existing_docs_report"]
build_standardize_manifest_v2_report_text = HELPERS["build_standardize_manifest_v2_report_text"]
print_standardize_manifest_v2_report = HELPERS["print_standardize_manifest_v2_report"]

build_existing_google_doc_manifest_signature = HELPERS["build_existing_google_doc_manifest_signature"]
classify_existing_google_doc_transcript_standard = HELPERS["classify_existing_google_doc_transcript_standard"]
register_existing_google_docs_in_manifest = HELPERS["register_existing_google_docs_in_manifest"]
extract_google_doc_id_from_url = HELPERS["extract_google_doc_id_from_url"]
find_manifest_entries_referencing_google_doc = HELPERS["find_manifest_entries_referencing_google_doc"]
load_manifest_read_only = HELPERS["load_manifest_read_only"]
ORIGINAL_LOAD_MANIFEST_READ_ONLY = load_manifest_read_only
should_skip_by_manifest = HELPERS["should_skip_by_manifest"]
normalize_authoritative_source_created_at = HELPERS["normalize_authoritative_source_created_at"]
extract_embedded_media_creation_candidates = HELPERS["extract_embedded_media_creation_candidates"]
resolve_source_creation_authority = HELPERS["resolve_source_creation_authority"]
with_source_creation_authority = HELPERS["with_source_creation_authority"]
get_runtime_language_code = HELPERS["get_runtime_language_code"]
get_language_mode_label = HELPERS["get_language_mode_label"]

make_manifest_v2_default = HELPERS["make_manifest_v2_default"]
build_transcript_standard_check = HELPERS["build_transcript_standard_check"]
build_manifest_v2_from_existing_manifest_and_docs = HELPERS["build_manifest_v2_from_existing_manifest_and_docs"]
standardize_manifest_to_v2_for_existing_google_docs = HELPERS["standardize_manifest_to_v2_for_existing_google_docs"]
comparable_manifest_v2_for_material_change = HELPERS["comparable_manifest_v2_for_material_change"]
manifest_v2_material_changes_needed = HELPERS["manifest_v2_material_changes_needed"]
clear_manifest_catalog = HELPERS["clear_manifest_catalog"]
build_manifest_clear_report_text = HELPERS["build_manifest_clear_report_text"]
mark_manifest_in_progress = HELPERS["mark_manifest_in_progress"]
mark_manifest_done = HELPERS["mark_manifest_done"]
mark_manifest_failed = HELPERS["mark_manifest_failed"]
get_manifest_entry = HELPERS["get_manifest_entry"]
save_manifest = HELPERS["save_manifest"]
DOC_MIME = HELPERS["DOC_MIME"]
FOLDER_MIME = HELPERS["FOLDER_MIME"]
validate_drive_multi_selected_items = HELPERS["validate_drive_multi_selected_items"]
summarize_drive_multi_selection = HELPERS["summarize_drive_multi_selection"]
normalize_local_folder_relative_path = HELPERS["normalize_local_folder_relative_path"]
make_local_folder_upload_state = HELPERS["make_local_folder_upload_state"]
accumulate_local_folder_upload_event = HELPERS["accumulate_local_folder_upload_event"]
finalize_local_folder_upload = HELPERS["finalize_local_folder_upload"]
get_drive_source_double_click_action = HELPERS["get_drive_source_double_click_action"]
RunTimer = HELPERS["RunTimer"]
build_startup_timing_summary = HELPERS["build_startup_timing_summary"]
build_timing_analysis = HELPERS["build_timing_analysis"]
format_timing_line = HELPERS["format_timing_line"]
normalize_speaker_project_data = HELPERS["normalize_speaker_project_data"]
create_speaker_project = HELPERS["create_speaker_project"]
rename_speaker_project = HELPERS["rename_speaker_project"]
archive_speaker_project = HELPERS["archive_speaker_project"]
add_project_speaker = HELPERS["add_project_speaker"]
rename_project_speaker = HELPERS["rename_project_speaker"]
deactivate_project_speaker = HELPERS["deactivate_project_speaker"]
parse_google_doc_url_or_id = HELPERS["parse_google_doc_url_or_id"]
detect_speakers_metadata_value = HELPERS["detect_speakers_metadata_value"]
detect_speaker_turns = HELPERS["detect_speaker_turns"]
extract_meaningful_speaker_samples = HELPERS["extract_meaningful_speaker_samples"]
parse_speaker_mapping = HELPERS["parse_speaker_mapping"]
get_active_project_speaker_roster_snapshot = HELPERS["get_active_project_speaker_roster_snapshot"]
speaker_mapping_text_fingerprint = HELPERS["speaker_mapping_text_fingerprint"]
active_project_speaker_roster_fingerprint = HELPERS["active_project_speaker_roster_fingerprint"]
build_speaker_rename_plan = HELPERS["build_speaker_rename_plan"]
apply_speaker_label_renames_to_plain_text = HELPERS["apply_speaker_label_renames_to_plain_text"]


def test_startup_timing_summary_formats_expected_phase_names() -> None:
    timer = RunTimer()
    timer.add_duration("startup_total", 3.25)
    timer.add_duration("startup_imports_or_bootstrap", 0.10)
    timer.add_duration("startup_secret_load", 0.20)
    timer.add_duration("startup_google_auth", 1.50)
    timer.add_duration("startup_google_client_build", 0.40)
    timer.add_duration("startup_destination_folder_refresh", 0.60)
    timer.add_duration("startup_ui_render", 0.30)
    timer.add_duration("startup_js_hooks", 0.15)

    summary = build_startup_timing_summary(timer)

    assert "=== Startup timing summary (local) ===" in summary
    assert "- startup_total: 3.25s" in summary
    for label in [
        "startup_imports_or_bootstrap",
        "startup_secret_load",
        "startup_google_auth",
        "startup_google_client_build",
        "startup_temp_cleanup",
        "startup_destination_folder_refresh",
        "startup_ui_render",
        "startup_js_hooks",
    ]:
        assert label in summary
    assert "not run during UI startup" in summary
    assert "Colab cold start" in summary
    assert "top-level pip install" in summary


def test_startup_timing_summary_does_not_include_secret_like_values() -> None:
    timer = RunTimer()
    timer.add_duration("startup_total", 1.0)
    timer.add_duration("startup_secret_load", 0.01)
    secret_like_values = [
        "sk-test-secret-value",
        "ELEVENLABS_API_KEY_VALUE",
        "/content/drive/MyDrive/private/path",
        "raw provider response body",
        "Google Docs body content",
    ]

    summary = build_startup_timing_summary(timer)

    assert "startup_secret_load" in summary
    for value in secret_like_values:
        assert value not in summary


def test_existing_run_timing_summary_helpers_still_work() -> None:
    timer = RunTimer()
    timer.add_duration("runtime_context_build", 1.0)
    timer.add_duration("source_collect", 2.0)
    timer.add_duration("source_processing_total", 5.0)
    timer.add_duration("provider_transcription", 4.5)
    timer.add_duration("run_total", 10.0)

    analysis = build_timing_analysis(timer)
    line = format_timing_line(timer, "provider_transcription", analysis["run_total"])

    assert analysis["run_total"] == 10.0
    assert analysis["known_measured_total"] == 8.0
    assert analysis["approx_unaccounted_run_time"] == 2.0
    assert line == "- provider_transcription: 4.50s (45.0% of run_total)"
    assert any("Provider transcription dominated" in hint for hint in analysis["bottleneck_hints"])


def test_validate_drive_multi_selected_items_preserves_order_and_normalizes() -> None:
    items = [
        {
            "id": "file-1",
            "name": "Lecture.mp3",
            "mimeType": "audio/mpeg",
            "webViewLink": "https://drive/file-1",
            "modifiedTime": "2026-06-01T00:00:00Z",
            "size": "123",
        },
        {"id": "file-2", "name": "Demo.MP4", "mimeType": "video/mp4", "display_name": "Folder/Demo.MP4"},
    ]

    normalized = validate_drive_multi_selected_items(items)

    assert [item["id"] for item in normalized] == ["file-1", "file-2"]
    assert normalized[0]["display_name"] == "Lecture.mp3"
    assert normalized[1]["display_name"] == "Folder/Demo.MP4"
    assert normalized[0]["size"] == "123"


def test_validate_drive_multi_selected_items_rejects_empty_folders_and_unsupported() -> None:
    for items, expected in [
        ([], "Выбери один или несколько файлов"),
        ([{"id": "folder-1", "name": "Nested", "mimeType": FOLDER_MIME}], "Папку нельзя выбрать"),
        ([{"id": "txt-1", "name": "notes.txt", "mimeType": "text/plain"}], "Неподдерживаемое расширение"),
    ]:
        try:
            validate_drive_multi_selected_items(items)
        except ValueError as error:
            assert expected in str(error)
        else:
            raise AssertionError("Expected ValueError")


def test_summarize_drive_multi_selection_is_compact_and_limits_names() -> None:
    items = [{"id": str(idx), "name": f"file-{idx}.mp3", "mimeType": "audio/mpeg"} for idx in range(12)]

    summary = summarize_drive_multi_selection(items, limit=10)

    assert summary.startswith("Выбрано файлов: 12")
    assert "- file-0.mp3" in summary
    assert "- file-9.mp3" in summary
    assert "file-10.mp3" not in summary
    assert "... ещё 2" in summary


def test_local_folder_relative_path_normalization_preserves_safe_nested_path() -> None:
    assert normalize_local_folder_relative_path("Course\\Week 1\\lecture.MP3") == "Course/Week 1/lecture.MP3"

    for unsafe in ["", "/root/audio.mp3", "C:\\private\\audio.mp3", "folder/../audio.mp3", "folder//audio.mp3", "folder/\x00audio.mp3"]:
        with pytest.raises(ValueError):
            normalize_local_folder_relative_path(unsafe)


def test_local_folder_chunk_accumulator_round_trips_supported_files() -> None:
    state = make_local_folder_upload_state()
    payload = b"bounded-audio"
    path = "Project A/meeting.mp3"

    assert accumulate_local_folder_upload_event(state, {"event": "start", "path": path, "size": len(payload)})["offset"] == 0
    assert accumulate_local_folder_upload_event(
        state,
        {"event": "chunk", "path": path, "offset": 0, "data": base64.b64encode(payload).decode("ascii")},
    )["offset"] == len(payload)
    assert accumulate_local_folder_upload_event(state, {"event": "end", "path": path})["size"] == len(payload)
    assert finalize_local_folder_upload(state) == {path: payload}


def test_local_folder_chunk_accumulator_rejects_ambiguous_or_incomplete_transfer() -> None:
    state = make_local_folder_upload_state()
    accumulate_local_folder_upload_event(state, {"event": "start", "path": "Folder/Call.mp3", "size": 1})
    with pytest.raises(ValueError, match="duplicate relative paths"):
        accumulate_local_folder_upload_event(state, {"event": "start", "path": "folder/call.MP3", "size": 1})
    with pytest.raises(ValueError, match="не завершена"):
        finalize_local_folder_upload(state)
    with pytest.raises(ValueError, match="порядок chunks"):
        accumulate_local_folder_upload_event(
            state,
            {"event": "chunk", "path": "Folder/Call.mp3", "offset": 1, "data": base64.b64encode(b"x").decode("ascii")},
        )


def test_local_folder_ui_and_colab_bridge_static_contract() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")
    bridge = source.split("def upload_local_folder_from_browser", 1)[1].split("def conflict_mode_result_hint", 1)[0]
    process_local = source.split("def process_local_uploaded", 1)[1].split("def process_drive_file_input", 1)[0]

    assert '("Компьютер: папка", "local_folder")' in source
    assert 'elif mode == "local_folder":' in source
    assert "upload_local_folder_from_browser()" in source
    assert "webkitdirectory directory multiple" in bridge
    assert "const chunkBytes = {LOCAL_FOLDER_UPLOAD_CHUNK_BYTES};" in bridge
    assert ".next()" in bridge
    assert "colab_output.eval_js" in bridge
    assert "lastModified" not in bridge
    assert "webkitRelativePath || file.name" in bridge
    assert '"selection_mode": source_mode' in process_local
    assert "source_name=display_name" in process_local


def test_drive_source_double_click_action_mapping_is_conservative() -> None:
    assert get_drive_source_double_click_action("drive_file", True) == "open"
    assert get_drive_source_double_click_action("drive_file", False) == "select"
    assert get_drive_source_double_click_action("drive_folder", True) == "open"
    assert get_drive_source_double_click_action("drive_folder", False) == "none"
    assert get_drive_source_double_click_action("drive_multi", True) == "open"
    assert get_drive_source_double_click_action("drive_multi", False) == "none"
    assert get_drive_source_double_click_action("local_file", True) == "none"
    assert get_drive_source_double_click_action("local_file", False) == "none"
    assert get_drive_source_double_click_action("local_multi", True) == "none"
    assert get_drive_source_double_click_action("local_multi", False) == "none"



def test_drive_multi_source_double_click_navigation_is_folder_only() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")

    assert "elevenlabs-drive-source-select-multi" in source
    assert "const MULTI_CLASS = 'elevenlabs-drive-source-select-multi';" in source
    assert "[SINGLE_CLASS, MULTI_CLASS].forEach" in source
    assert "bindMultiSelect(selectElement)" in source
    assert "DOUBLE_CLICK_THRESHOLD_MS" in source
    assert "addEventListener('dblclick'" in source
    assert "addEventListener('click'" in source
    assert "addEventListener('mousedown'" in source
    assert "__elevenlabsLastMultiClickValue" in source
    assert "event.target.closest('option')" in source

    double_click_callback = source.split("def on_source_item_double_clicked", 1)[1].split(
        "def install_drive_source_double_click_js",
        1,
    )[0]
    drive_multi_block = double_click_callback.split('if mode == "drive_multi":', 1)[1].split(
        'if selected_id and selected_id in source_picker_state["item_map"]:',
        1,
    )[0]

    assert 'selected_ids = list(source_items_select_multi.value or [])' in drive_multi_block
    assert 'len(selected_ids) != 1' in drive_multi_block
    assert 'source_items_select_multi.value = (selected_id,)' in drive_multi_block
    assert "on_source_open_clicked(None)" in drive_multi_block
    assert "on_source_select_clicked(None)" not in drive_multi_block
    assert "В режиме Google Drive: несколько файлов двойной клик может открыть папку" in source
    assert "выбор файлов и запуск набора остаются явными через кнопку «Выбрать файлы»" in source


def test_drive_multi_file_double_click_cannot_finalize_batch() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")
    double_click_callback = source.split("def on_source_item_double_clicked", 1)[1].split(
        "def install_drive_source_double_click_js",
        1,
    )[0]
    drive_multi_block = double_click_callback.split('if mode == "drive_multi":', 1)[1].split(
        'if selected_id and selected_id in source_picker_state["item_map"]:',
        1,
    )[0]

    assert 'action = get_drive_source_double_click_action(mode, is_folder)' in drive_multi_block
    assert 'if action == "open":' in drive_multi_block
    assert 'elif action == "select":' not in drive_multi_block
    assert "on_source_select_clicked(None)" not in drive_multi_block

    action_helper = source.split("def get_drive_source_double_click_action", 1)[1].split(
        "def validate_drive_multi_selected_items",
        1,
    )[0]
    drive_multi_action_block = action_helper.split('if mode == "drive_multi":', 1)[1].split(
        'return "none"',
        1,
    )[0]
    assert 'return "open" if is_folder else "none"' in drive_multi_action_block


def test_destination_folder_double_click_navigation_is_conservative() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")

    assert "elevenlabs.destinationFolderDoubleClick" in source
    assert "elevenlabs-destination-folder-picker" in source
    assert "elevenlabs-destination-folder-select" in source
    assert "data-elevenlabs-destination-folder-dblclick-bound" in source
    double_click_callback = source.split("def on_picker_folder_double_clicked", 1)[1].split(
        "def install_destination_folder_double_click_js",
        1,
    )[0]

    assert "on_picker_open_clicked(None)" in double_click_callback
    assert "on_picker_select_clicked(None)" not in double_click_callback
    assert "двойной клик по папке в списке может открыть" in source
    assert "Выбор папки назначения остаётся явным" in source


def test_source_input_ui_uses_picker_only_internal_drive_value() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")

    assert "source_input_mode_widget" not in source
    assert "Путь / ссылка" not in source
    assert 'description="Служебный источник:"' in source


def test_get_source_input_value_guards_against_stale_drive_mode_selection() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")

    expected = '''def get_source_input_value() -> str:
    current_mode = mode_widget.value
    if current_mode in {"drive_file", "drive_multi", "drive_folder"}:
        if source_picker_state.get("selected_mode") != current_mode:
            return ""
        return source_picker_state["selected_input"].strip()
    return ""
'''
    assert expected in source


def test_conflict_mode_widget_defaults_to_safe_skip() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")

    conflict_options = re.search(r"CONFLICT_MODE_OPTIONS = \[([\s\S]*?)\n\]", source)
    assert conflict_options is not None
    for mode in ['"skip"', '"update"', '"archive_recreate"', '"copy_suffix"']:
        assert mode in conflict_options.group(1)

    conflict_widget = re.search(r"conflict_mode_widget = widgets\.Dropdown\(([\s\S]*?)\n\)", source)
    assert conflict_widget is not None
    assert 'options=CONFLICT_MODE_OPTIONS' in conflict_widget.group(1)
    assert 'value="skip"' in conflict_widget.group(1)
    assert 'value="update"' not in conflict_widget.group(1)


def test_drive_source_selected_html_uses_dark_theme_readable_colors() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")

    selected_source_block = re.search(
        r'source_selected_html\.value = f?"""([\s\S]*?<b>Выбран источник:</b>[\s\S]*?</div>)',
        source,
    )
    assert selected_source_block is not None
    selected_html = selected_source_block.group(1)

    assert "background:#eef6ff;" in selected_html
    assert "color:#202124;" in selected_html
    assert '<code style="' in selected_html
    assert "color:#202124;" in selected_html.split("<code", 1)[1].split(">", 1)[0]
    assert "white-space:pre-wrap;" in selected_html.split("<code", 1)[1].split(">", 1)[0]
    assert "format_drive_multi_summary_html" in source


def test_docs_do_not_describe_drive_multi_as_unavailable() -> None:
    docs_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [Path("README.md"), Path("docs/project-spec.md"), Path("docs/runbooks/validation.md")]
    )

    stale_phrases = [
        "drive_multi not added",
        "drive_multi не добав",
        "drive_multi planned",
        "drive_multi план",
    ]
    assert not any(phrase.casefold() in docs_text.casefold() for phrase in stale_phrases)


def build_legacy_standard_document(title: str = "Call", body: str = "Hello world.") -> str:
    return (
        f"{title}\n\n"
        "Transcript metadata\n"
        "Source file: not available\n"
        "Source mode: existing_google_doc_standardization\n"
        "Provider: unknown\n"
        "Model: unknown\n"
        "Language: unknown\n"
        "Speakers: unknown\n"
        "Created at: 2026-06-02T10:26:40.369268+00:00\n\n"
        "Transcript\n\n"
        f"{body}"
    )


def test_format_transcript_metadata_value_normalizes_blank_values() -> None:
    assert format_transcript_metadata_value(None) == "unknown"
    assert format_transcript_metadata_value("  alpha\n beta  ") == "alpha beta"


def test_colab_language_modes_include_english_without_changing_auto_detection() -> None:
    assert get_runtime_language_code("ru") == "ru"
    assert get_runtime_language_code("en") == "en"
    assert get_runtime_language_code("detect") is None
    assert get_language_mode_label("en") == "English"
    assert HELPERS["DEFAULT_LANGUAGE_MODE"] == "detect"


def test_source_creation_timestamp_requires_timezone_and_normalizes_to_iso_8601_utc() -> None:
    assert normalize_authoritative_source_created_at("2026-08-24T15:10:11+03:00") == "2026-08-24T12:10:11Z"
    assert normalize_authoritative_source_created_at("2026-08-24T12:10:11.987Z") == "2026-08-24T12:10:11Z"
    assert normalize_authoritative_source_created_at("2026-08-24T12:10:11") is None
    assert normalize_authoritative_source_created_at("") is None


def test_source_creation_authority_prefers_embedded_media_then_drive_created_time(monkeypatch) -> None:
    globals_dict = resolve_source_creation_authority.__globals__
    monkeypatch.setitem(
        globals_dict,
        "extract_embedded_media_creation_candidates",
        lambda _path: [{"created_at": "2024-01-02T03:04:05Z", "authority": "embedded_media.format.creation_time"}],
    )
    assert resolve_source_creation_authority(
        "media.mp4",
        {"createdTime": "2025-02-03T04:05:06Z", "modifiedTime": "2099-01-01T00:00:00Z"},
    ) == {
        "created_at": "2024-01-02T03:04:05Z",
        "authority": "embedded_media.format.creation_time",
        "status": "confirmed",
    }

    monkeypatch.setitem(globals_dict, "extract_embedded_media_creation_candidates", lambda _path: [])
    assert resolve_source_creation_authority(
        "media.mp4",
        {"createdTime": "2025-02-03T07:05:06+03:00", "modifiedTime": "2099-01-01T00:00:00Z"},
    ) == {
        "created_at": "2025-02-03T04:05:06Z",
        "authority": "google_drive.createdTime",
        "status": "confirmed",
    }


def test_source_creation_authority_fails_closed_on_conflict_or_missing_authority(monkeypatch) -> None:
    globals_dict = resolve_source_creation_authority.__globals__
    monkeypatch.setitem(
        globals_dict,
        "extract_embedded_media_creation_candidates",
        lambda _path: [
            {"created_at": "2024-01-02T03:04:05Z", "authority": "embedded_media.format.creation_time"},
            {"created_at": "2024-01-02T04:04:05Z", "authority": "embedded_media.stream:0.creation_time"},
        ],
    )
    assert resolve_source_creation_authority("media.mp4", {"createdTime": "2025-02-03T04:05:06Z"}) == {
        "created_at": "unknown",
        "authority": "embedded_media_conflict",
        "status": "conflict",
    }

    monkeypatch.setitem(globals_dict, "extract_embedded_media_creation_candidates", lambda _path: [])
    assert resolve_source_creation_authority(
        "media.mp4",
        {"modifiedTime": "2025-02-03T04:05:06Z"},
    ) == {"created_at": "unknown", "authority": "unavailable", "status": "unavailable"}


def test_embedded_source_creation_extractor_accepts_only_creation_tags(monkeypatch) -> None:
    class Completed:
        stdout = json.dumps({
            "format": {"tags": {
                "creation_time": "2024-01-02T03:04:05Z",
                "date": "2099-01-01T00:00:00Z",
            }},
            "streams": [{"tags": {"com.apple.quicktime.creationdate": "2024-01-02T03:04:05Z"}}],
        })

    subprocess_module = extract_embedded_media_creation_candidates.__globals__["subprocess"]
    monkeypatch.setattr(subprocess_module, "run", lambda *_args, **_kwargs: Completed())

    assert extract_embedded_media_creation_candidates("media.mov") == [{
        "created_at": "2024-01-02T03:04:05Z",
        "authority": "embedded_media.format.creation_time",
    }]


def test_new_transcript_output_never_uses_job_time_as_source_creation_time() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")
    function_block = source.split("def upsert_transcript_document(", 1)[1].split("\ndef ", 1)[0]

    assert "created_at=source_created_at" in function_block
    assert "created_at=utc_now_iso()" not in function_block
    assert source.count('source_created_at=source_meta.get("source_created_at", "unknown")') == 6
    assert 'source_created_at=segment_meta.get("source_created_at", "unknown")' in source


@pytest.mark.parametrize(
    ("created_at", "expected_date"),
    [("unknown", None), ("2026-06-03 11:46 UTC", "2026-06-03 11:46 UTC")],
)
def test_new_colab_document_only_displays_known_recording_date(
    monkeypatch, created_at, expected_date
) -> None:
    upsert = HELPERS["upsert_transcript_document"]
    doc = {"id": "synthetic", "name": "Call", "webViewLink": ""}
    writes = []
    for name, helper in {
        "get_single_existing_doc_match": lambda *_: None,
        "get_source_mode_label": lambda mode: mode,
        "get_unique_name": lambda _folder, name, _mime: name,
        "create_google_doc": lambda *_: doc,
        "write_title_and_text_to_doc": lambda **request: writes.append(request),
        "add_doc_record_to_index": lambda *_: None,
    }.items():
        monkeypatch.setitem(HELPERS, name, helper)
    options = SimpleNamespace(
        language_label="Русский",
        language_code="ru",
        provider_label="ElevenLabs",
        provider_model_label="scribe_v2",
        separate_speakers=False,
    )

    result = upsert("Call", "Реплика.", "folder", {}, "skip", "Call.wav", "drive", options, created_at)

    assert result["action"] == "created"
    body = writes[0]["transcript_text"]
    assert "Реплика." in body
    if expected_date is None:
        assert "Created at:" not in body
    else:
        assert f"Created at: {expected_date}" in body


def test_format_visible_transcript_timestamp_handles_iso_and_visible_values() -> None:
    assert format_visible_transcript_timestamp("2026-06-03T11:46:04.472894+00:00") == "2026-06-03 11:46 UTC"
    assert format_visible_transcript_timestamp("2026-06-03T11:46:04Z") == "2026-06-03 11:46 UTC"
    assert format_visible_transcript_timestamp("2026-06-03T14:46:04+03:00") == "2026-06-03 11:46 UTC"
    assert format_visible_transcript_timestamp("2026-06-03 11:46 UTC") == "2026-06-03 11:46 UTC"
    assert format_visible_transcript_timestamp("") == "unknown"
    assert format_visible_transcript_timestamp("  not a timestamp  ") == "not a timestamp"


@pytest.mark.parametrize("failure", [None, "stale revision", "batch rejected"])
def test_colab_existing_doc_replacement_is_one_revision_guarded_batch(monkeypatch, failure):
    original = "Original recording text"
    state = {"text": original}
    calls = []
    replacement = build_structured_transcript_document_text(
        document_title="Call", transcript_text="Новая реплика.", metadata_lines=["Provider: ElevenLabs"]
    )
    snapshot = {
        "document_id": "doc",
        "revision_id": "preview-revision",
        "end_index": len(original) + 2,
    }

    def batch_update(*, documentId, body):
        calls.append(body)
        assert documentId == "doc"
        assert body["writeControl"] == {"requiredRevisionId": "preview-revision"}
        assert body["requests"][0] == {
            "deleteContentRange": {"range": {"startIndex": 1, "endIndex": snapshot["end_index"] - 1}}
        }
        assert body["requests"][1]["insertText"]["text"] == replacement
        assert "updateParagraphStyle" in body["requests"][2]

        def execute():
            if failure:
                raise RuntimeError(failure)
            state["text"] = body["requests"][1]["insertText"]["text"]
        return SimpleNamespace(execute=execute)

    documents = SimpleNamespace(batchUpdate=batch_update)
    monkeypatch.setitem(HELPERS, "docs_service", SimpleNamespace(documents=lambda: documents))
    if failure:
        with pytest.raises(RuntimeError, match=failure):
            write_google_doc("doc", "Call", replacement, clear_first=True, edit_snapshot=snapshot)
        assert state["text"] == original
    else:
        write_google_doc("doc", "Call", replacement, clear_first=True, edit_snapshot=snapshot)
        assert state["text"] == replacement
    assert len(calls) == 1


def test_colab_folder_apply_rejects_changed_preview_without_writing(monkeypatch):
    monkeypatch.setitem(HELPERS, "list_drive_folder_children", lambda _folder: [
        {"id": "doc", "name": "Call", "mimeType": DOC_MIME},
    ])
    snapshot = {"document_id": "doc", "revision_id": "before", "end_index": 25, "text": "Call\n\nOriginal"}
    monkeypatch.setitem(HELPERS, "read_google_doc_for_edit", lambda _doc: snapshot.copy())
    writes = []
    monkeypatch.setitem(HELPERS, "write_title_and_text_to_doc", lambda **request: writes.append(request))

    preview = standardize_existing_google_docs_in_folder("root")
    assert preview["preview_revisions"] == {"doc": "before"}
    snapshot.update(revision_id="after", text="Call\n\nEdited directly")
    applied = standardize_existing_google_docs_in_folder("root", dry_run=False,
                                                          preview_revisions=preview["preview_revisions"])
    assert not writes
    assert not applied["standardized"]
    assert "изменился" in applied["errors"][0]["reason"]


def test_colab_oversized_replacement_stops_before_the_first_write(monkeypatch):
    snapshot = {"document_id": "doc", "revision_id": "revision", "end_index": 5}
    replacement = build_structured_transcript_document_text(
        document_title="Call", transcript_text="A valid body", metadata_lines=["Provider: ElevenLabs"]
    )
    monkeypatch.setitem(HELPERS, "DOC_REPLACEMENT_MAX_BYTES", 1)
    monkeypatch.setitem(HELPERS, "docs_service", None)
    with pytest.raises(ValueError, match="слишком большой"):
        write_google_doc("doc", "Call", replacement, clear_first=True, edit_snapshot=snapshot)


def test_colab_stt_reservation_allows_one_concurrent_request(monkeypatch):
    reserve = HELPERS["reserve_colab_stt"]
    both_read = Barrier(2)
    lock = Lock()
    document = {"revision": 1, "text": ""}

    def read(document_id):
        with lock:
            snapshot = {"document_id": document_id, "revision_id": str(document["revision"]),
                        "end_index": len(document["text"]) + 2, "text": document["text"]}
        both_read.wait(timeout=5)
        return snapshot

    def batch_update(*, documentId, body):
        assert documentId == "guard"

        def execute():
            with lock:
                if body["writeControl"]["requiredRevisionId"] != str(document["revision"]):
                    raise RuntimeError("stale revision")
                document["text"] = body["requests"][-1]["insertText"]["text"]
                document["revision"] += 1
        return SimpleNamespace(execute=execute)

    monkeypatch.setitem(HELPERS, "read_google_doc_for_edit", read)
    docs = SimpleNamespace(batchUpdate=batch_update)
    monkeypatch.setitem(HELPERS, "docs_service", SimpleNamespace(documents=lambda: docs))
    dispatched = []

    def dispatch():
        try:
            claim = reserve("guard", "source", "settings")
        except RuntimeError as error:
            return str(error)
        dispatched.append(claim)
        return "provider called"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: dispatch(), range(2))) == ["provider called", "stale revision"]
    assert len(dispatched) == 1


def test_colab_stt_reservation_lost_acknowledgment_blocks_automatic_retry(monkeypatch):
    reserve = HELPERS["reserve_colab_stt"]
    header = HELPERS["COLAB_STT_RESERVATION_HEADER"]
    stored = {}
    writes = []

    def read(document_id):
        return {"document_id": document_id, "revision_id": "latest", "end_index": 2,
                "text": header + json.dumps(stored) if stored else ""}

    def fail_after_write(_snapshot, records):
        stored.update(records)
        writes.append(1)
        raise RuntimeError("lost acknowledgment")

    monkeypatch.setitem(HELPERS, "read_google_doc_for_edit", read)
    monkeypatch.setitem(HELPERS, "write_colab_stt_reservations", fail_after_write)
    with pytest.raises(RuntimeError, match="lost acknowledgment"):
        reserve("guard", "source", "settings")
    with pytest.raises(ValueError, match="исход неизвестен"):
        reserve("guard", "source", "settings", allow_repeat=True)
    assert writes == [1]


def test_colab_stt_reservation_finishes_only_the_exact_claim(monkeypatch):
    reserve = HELPERS["reserve_colab_stt"]
    complete = HELPERS["complete_colab_stt_reservation"]
    header = HELPERS["COLAB_STT_RESERVATION_HEADER"]
    stored = {}

    def read(document_id):
        return {"document_id": document_id, "revision_id": "latest", "end_index": 2,
                "text": header + json.dumps(stored) if stored else ""}

    monkeypatch.setitem(HELPERS, "read_google_doc_for_edit", read)
    monkeypatch.setitem(HELPERS, "write_colab_stt_reservations", lambda _snap, records: stored.update(records))
    key, token = reserve("guard", "source", "settings")
    with pytest.raises(ValueError, match="изменился"):
        complete("guard", key, "other-token")
    assert stored[key]["status"] == "pending"
    complete("guard", key, token)
    complete("guard", key, token)
    with pytest.raises(ValueError, match="подтверждён результат"):
        reserve("guard", "source", "settings")
    same_key, new_token = reserve("guard", "source", "settings", allow_repeat=True)
    assert same_key == key and new_token != token


@pytest.mark.parametrize("result_url", ["", "https://docs.google.com/document/d/result_12345/edit"])
def test_colab_stt_recovery_requires_confirmation_and_does_not_dispatch(monkeypatch, result_url):
    resolve = HELPERS["resolve_colab_stt_reservation"]
    key = "a" * 64
    records = {key: {"status": "pending", "token": "owner"}}
    writes = []
    monkeypatch.setitem(HELPERS, "read_colab_stt_reservations", lambda _doc: ({}, records.copy()))
    monkeypatch.setitem(HELPERS, "extract_google_doc_plain_text", lambda _doc: "Recovered transcript")
    monkeypatch.setitem(HELPERS, "write_colab_stt_reservations", lambda _snapshot, updated: writes.append(updated))
    with pytest.raises(ValueError, match="ЗАКРЫТЬ РЕЗЕРВ"):
        resolve("guard", key, result_url, "")
    assert not writes
    resolve("guard", key, result_url, "ЗАКРЫТЬ РЕЗЕРВ")
    if result_url:
        assert writes[0][key]["status"] == "done"
    else:
        assert key not in writes[0]


def test_colab_paid_dispatch_requires_an_acknowledged_reservation(monkeypatch):
    dispatch = HELPERS["transcribe_guarded_colab_source"]
    ctx = SimpleNamespace(stt_reservation_doc_id="guard", ignore_manifest=True,
                          settings_signature="settings", options=object())
    calls = []

    def reserve(*_args, **_kwargs):
        calls.append("reserve")
        raise RuntimeError("reservation acknowledgment lost")

    monkeypatch.setitem(HELPERS, "reserve_colab_stt", reserve)
    monkeypatch.setitem(HELPERS, "transcribe_media_path", lambda **_kwargs: calls.append("STT"))
    with pytest.raises(RuntimeError, match="acknowledgment lost"):
        dispatch(ctx, "source", input_path="synthetic.wav", original_filename="synthetic.wav")
    assert calls == ["reserve"]


def test_extract_existing_transcript_created_at_reads_current_and_legacy_metadata_only() -> None:
    current = build_structured_transcript_document_text(
        document_title="Call",
        transcript_text="Body",
        metadata_lines=build_transcript_metadata_lines(
            source_name="ignored",
            source_mode="ignored",
            provider="ElevenLabs",
            provider_model="scribe_v2",
            language="Русский",
            speakers_enabled=None,
            created_at="2026-06-03 11:46 UTC",
        ),
    )
    legacy = build_legacy_standard_document()

    assert extract_existing_transcript_created_at(current) == "2026-06-03 11:46 UTC"
    assert extract_existing_transcript_created_at(legacy) == "2026-06-02T10:26:40.369268+00:00"
    assert extract_existing_transcript_created_at("Call\n\nTranscript metadata\nProvider: ElevenLabs\n\nTranscript\n\nBody") == ""
    assert extract_existing_transcript_created_at(
        "Call\n\nCreated at: 2026-06-03T11:46:04Z\nBody",
        "Call",
    ) == "2026-06-03T11:46:04Z"
    assert extract_existing_transcript_created_at(
        "First body paragraph\n\nCreated at: 2026-06-03T11:46:04Z"
    ) == ""
    assert extract_existing_transcript_created_at(
        "Call\n\nTranscript metadata\nProvider: ElevenLabs\nModel: scribe_v2\nLanguage: Русский\n"
        "Speakers: unknown\nCreated at: 2026-06-01T00:00:00+00:00\n\nTranscript\n\n"
        "Created at: 2099-01-01T00:00:00+00:00"
    ) == "2026-06-01T00:00:00+00:00"


def test_resolve_existing_google_doc_created_at_priority_and_no_now_fallback() -> None:
    existing = build_legacy_standard_document()

    assert resolve_existing_google_doc_created_at(
        existing,
        {"createdTime": "2026-06-03T11:46:04Z"},
    ) == "2026-06-02T10:26:40.369268+00:00"
    assert resolve_existing_google_doc_created_at(
        existing,
        {"createdTime": "2026-06-03T11:46:04Z"},
        prefer_drive_created_time_for_metadata_refresh=True,
    ) == "2026-06-02T10:26:40.369268+00:00"
    assert get_existing_google_doc_created_at_source(existing, {"createdTime": "2026-06-03T11:46:04Z"}) == "existing_metadata"
    assert get_existing_google_doc_created_at_source(
        existing,
        {"createdTime": "2026-06-03T11:46:04Z"},
        prefer_drive_created_time_for_metadata_refresh=True,
    ) == "existing_metadata"
    assert resolve_existing_google_doc_created_at(
        "Call\n\nBody",
        {"createdTime": "2026-06-03T11:46:04Z"},
    ) == ""
    assert get_existing_google_doc_created_at_source(
        "Call\n\nBody",
        {"createdTime": "2026-06-03T11:46:04Z"},
    ) == "unknown"
    assert resolve_existing_google_doc_created_at("Call\n\nBody", {}) == ""
    assert get_existing_google_doc_created_at_source("Call\n\nBody", {}) == "unknown"
    assert resolve_existing_google_doc_created_at("Call\n\nBody", {}) != HELPERS["utc_now_iso"]()


def test_build_transcript_metadata_lines_supports_unknown_speakers_for_backfill() -> None:
    lines = build_transcript_metadata_lines(
        source_name="legacy.mp3",
        source_mode="Google Drive: папка",
        provider="unknown",
        provider_model="unknown",
        language="unknown",
        speakers_enabled=None,
        created_at="2026-06-01T00:00:00+00:00",
    )

    assert "Speakers: unknown" in lines


def test_build_transcript_metadata_lines_uses_stable_labels() -> None:
    lines = build_transcript_metadata_lines(
        source_name="lecture.mp3",
        source_mode="Google Drive: 1 файл",
        provider="ElevenLabs",
        provider_model="scribe_v2",
        language="Русский (ru)",
        speakers_enabled=True,
        created_at="2026-06-01T00:00:00+00:00",
    )

    assert "Source file: lecture.mp3" not in lines
    assert "Source mode: Google Drive: 1 файл" not in lines
    assert lines == [
        "Provider: ElevenLabs",
        "Model: scribe_v2",
        "Language: Русский (ru)",
        "Speakers: yes",
        "Created at: 2026-06-01T00:00:00+00:00",
    ]


def test_segment_plain_transcript_for_docs_splits_long_single_block_without_losing_text() -> None:
    text = "First sentence. Second sentence. Third sentence. Fourth sentence."

    segmented = segment_plain_transcript_for_docs(text, target_chars=25)

    assert segmented == "First sentence.\n\nSecond sentence.\n\nThird sentence.\n\nFourth sentence."
    assert segmented.replace("\n\n", " ") == text


def test_segment_plain_transcript_for_docs_preserves_speaker_labeled_blocks() -> None:
    text = "Спикер 1:\nПривет.\nСпикер 2:\nЗдравствуйте."

    assert segment_plain_transcript_for_docs(text, target_chars=10) == text


def test_build_structured_transcript_document_text_has_llm_readable_sections() -> None:
    metadata = [
        "Provider: OpenAI",
        "Model: gpt-4o-transcribe",
        "Language: Автоопределение",
        "Speakers: no",
        "Created at: 2026-06-01T00:00:00+00:00",
    ]

    document_text = build_structured_transcript_document_text(
        document_title="call",
        transcript_text="Hello world.",
        metadata_lines=metadata,
    )

    assert document_text == (
        "call\n\n"
        "Метаданные транскрипта\n"
        "Provider: OpenAI\n"
        "Model: gpt-4o-transcribe\n"
        "Language: Автоопределение\n"
        "Speakers: no\n"
        "Created at: 2026-06-01T00:00:00+00:00\n\n"
        "Транскрипция\n\n"
        "Hello world."
    )
    assert "Source file:" not in document_text
    assert "Source mode:" not in document_text


def test_new_transcript_document_localizes_speakers_and_uses_versionless_standard() -> None:
    document_text = build_structured_transcript_document_text(
        document_title="Созвон",
        transcript_text="Speaker 1:\nПривет.\nSpeaker 2:\nЗдравствуйте.",
        metadata_lines=[
            "Provider: ElevenLabs",
            "Model: scribe_v2",
            "Language: Русский",
            "Speakers: yes",
            "Created at: 2026-08-28 10:00 UTC",
        ],
    )

    assert HELPERS["TRANSCRIPT_STANDARD_TARGET"] == "transcript_doc"
    assert "Метаданные транскрипта" in document_text
    assert "Транскрипция" in document_text
    assert "Спикер 1:\nПривет." in document_text
    assert "Спикер 2:\nЗдравствуйте." in document_text
    assert "Speaker 1:" not in document_text


def test_transcript_doc_style_requests_use_h2_11pt_14pt_and_utf16_ranges() -> None:
    document_text = build_structured_transcript_document_text(
        document_title="😀 Call",
        transcript_text="Speaker 1:\nПривет 😀.",
        metadata_lines=[
            "Provider: ElevenLabs",
            "Model: scribe_v2",
            "Language: Русский",
            "Speakers: yes",
            "Created at: 2026-08-28 10:00 UTC",
        ],
    )

    requests = build_transcript_doc_style_requests(document_text)
    title_style = requests[0]["updateParagraphStyle"]
    body_style = requests[1]["updateTextStyle"]
    speaker_style = requests[2]["updateTextStyle"]
    speaker_start = document_text.index("Спикер 1:")
    utf16_len = lambda value: len(value.encode("utf-16-le")) // 2

    assert title_style["paragraphStyle"] == {"namedStyleType": "HEADING_2"}
    assert title_style["range"] == {
        "startIndex": 1,
        "endIndex": 1 + utf16_len("😀 Call\n"),
    }
    assert body_style["textStyle"] == {
        "bold": False,
        "fontSize": {"magnitude": 11, "unit": "PT"},
    }
    assert speaker_style["range"] == {
        "startIndex": 1 + utf16_len(document_text[:speaker_start]),
        "endIndex": 1 + utf16_len(document_text[:speaker_start + len("Спикер 1:")]),
    }
    assert speaker_style["textStyle"] == {
        "bold": True,
        "fontSize": {"magnitude": 14, "unit": "PT"},
    }


def test_colab_writer_applies_current_styles_after_bounded_text_inserts() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")
    writer = source.split("def write_title_and_text_to_doc(", 1)[1].split("\ndef ", 1)[0]

    assert '"namedStyleType": "TITLE"' not in writer
    assert "build_transcript_doc_style_requests(document_text)" in writer
    assert 'operation_label="docs_batch_update_styles"' in writer


def test_openai_diarize_chunking_preflight_warning_is_limited_to_risky_configuration() -> None:
    warning = get_openai_diarize_chunking_preflight_warning(
        provider="openai",
        separate_speakers=True,
        source_mode="drive_file",
    )

    assert warning is not None
    assert "experimental/high-risk" in warning
    assert "speaker labels may be inconsistent across chunks" in warning
    assert "text-based, not speaker-aware" in warning
    assert get_openai_diarize_chunking_preflight_warning("elevenlabs", True, "drive_file") is None
    assert get_openai_diarize_chunking_preflight_warning("openai", False, "drive_file") is None
    assert get_openai_diarize_chunking_preflight_warning("openai", True, "unknown") is None


def test_openai_diarize_chunking_preflight_warning_covers_supported_source_modes() -> None:
    source_modes = ["local_file", "local_multi", "drive_file", "drive_folder"]

    for source_mode in source_modes:
        assert get_openai_diarize_chunking_preflight_warning("openai", True, source_mode)


def test_chunk_text_for_docs_returns_empty_chunk_for_empty_text() -> None:
    assert chunk_text_for_docs("", max_chars=10) == [""]


def test_chunk_text_for_docs_keeps_small_text_and_normalizes_newlines() -> None:
    assert chunk_text_for_docs("first\r\nsecond\rthird", max_chars=100) == [
        "first\nsecond\nthird"
    ]


def test_chunk_text_for_docs_splits_large_text_without_losing_content_order() -> None:
    text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"

    chunks = chunk_text_for_docs(text, max_chars=18)

    assert len(chunks) > 1
    assert "".join(chunks) == text
    assert chunks == ["alpha beta gamma ", "delta epsilon ", "zeta eta theta ", "iota kappa"]


def test_chunk_text_for_docs_hard_splits_when_no_good_boundary_exists() -> None:
    text = "abcdefghijklmnopqrstuvwxyz"

    chunks = chunk_text_for_docs(text, max_chars=10)

    assert chunks == ["abcdefghij", "klmnopqrst", "uvwxyz"]
    assert "".join(chunks) == text


def test_chunk_text_for_docs_preserves_unicode_cyrillic_content_across_chunks() -> None:
    text = "Первый абзац с текстом.\n\nВторой абзац продолжается без потерь."

    chunks = chunk_text_for_docs(text, max_chars=32)

    assert len(chunks) > 1
    assert "".join(chunks) == text
    assert chunks[0].startswith("Первый")
    assert chunks[-1].endswith("потерь.")


def test_trim_duplicate_prefix_by_token_overlap_removes_overlapping_prefix() -> None:
    overlap = "alpha beta gamma delta epsilon"
    previous_text = f"Earlier transcript context. {overlap}"
    current_text = f"{overlap} unique continuation"

    assert (
        trim_duplicate_prefix_by_token_overlap(previous_text, current_text)
        == "unique continuation"
    )


def test_trim_duplicate_prefix_by_token_overlap_preserves_text_without_overlap() -> None:
    previous_text = "alpha beta gamma delta epsilon"
    current_text = "zeta eta theta iota kappa"

    assert trim_duplicate_prefix_by_token_overlap(previous_text, current_text) == current_text


def test_trim_duplicate_prefix_by_token_overlap_handles_cyrillic_case_and_spacing() -> None:
    previous_text = "Вступление. Привет большой мир сегодня снова"
    current_text = "привет   большой\nмир сегодня снова продолжаем расшифровку"

    assert (
        trim_duplicate_prefix_by_token_overlap(previous_text, current_text)
        == "продолжаем расшифровку"
    )


def test_merge_transcript_parts_with_overlap_trims_duplicate_boundary_text() -> None:
    first = "Segment one. alpha beta gamma delta epsilon"
    second = "alpha beta gamma delta epsilon segment two continues"

    assert merge_transcript_parts_with_overlap([first, second]) == (
        "Segment one. alpha beta gamma delta epsilon\n\nsegment two continues"
    )


def test_merge_transcript_parts_with_overlap_preserves_parts_without_overlap() -> None:
    assert merge_transcript_parts_with_overlap(["first part", "second part"]) == (
        "first part\n\nsecond part"
    )


def test_merge_transcript_parts_with_overlap_ignores_blank_parts() -> None:
    assert merge_transcript_parts_with_overlap(["  ", "first", "", "second  "]) == (
        "first\n\nsecond"
    )


def test_is_structured_transcript_document_text_requires_pr19_sections() -> None:
    structured = build_structured_transcript_document_text(
        document_title="call",
        transcript_text="Hello world.",
        metadata_lines=build_transcript_metadata_lines(
            source_name="call.flac",
            source_mode="Google Drive: 1 файл",
            provider="unknown",
            provider_model="unknown",
            language="unknown",
            speakers_enabled=None,
            created_at="2026-06-01T00:00:00+00:00",
        ),
    )

    assert is_structured_transcript_document_text(structured)
    assert not is_structured_transcript_document_text("call\n\nHello world.")
    assert not is_structured_transcript_document_text("Transcript metadata\nTranscript\nHello world.")



def test_is_structured_transcript_document_text_rejects_legacy_metadata_standard() -> None:
    legacy = build_legacy_standard_document()

    assert not is_structured_transcript_document_text(legacy)


def test_is_structured_transcript_document_text_requires_exact_current_metadata_block() -> None:
    valid_metadata = [
        "Provider: unknown",
        "Model: unknown",
        "Language: unknown",
        "Speakers: unknown",
        "Created at: 2026-06-01T00:00:00+00:00",
    ]

    def build_with(metadata_lines: list[str]) -> str:
        return build_structured_transcript_document_text(
            document_title="Call",
            transcript_text="Hello world.",
            metadata_lines=metadata_lines,
        )

    assert is_structured_transcript_document_text(build_with(valid_metadata))
    assert is_structured_transcript_document_text(build_with(valid_metadata[:-1]))

    invalid_cases = [
        [valid_metadata[1], valid_metadata[0], *valid_metadata[2:]],
        [*valid_metadata, valid_metadata[-1]],
        [*valid_metadata, "Duration: unknown"],
        [*valid_metadata[:-1], "Created at: unknown"],
        ["Source file: call.mp3", *valid_metadata],
        ["Source mode: Google Drive: 1 файл", *valid_metadata],
    ]
    for metadata_lines in invalid_cases:
        assert not is_structured_transcript_document_text(build_with(metadata_lines))


def test_extract_unstructured_transcript_body_for_backfill_drops_duplicate_title() -> None:
    text = "Legacy Call\n\nFirst line.\nSecond line."

    assert extract_unstructured_transcript_body_for_backfill(text, "Legacy Call") == "First line.\nSecond line."
    assert extract_unstructured_transcript_body_for_backfill("First line.", "Legacy Call") == "First line."
    assert extract_unstructured_transcript_body_for_backfill(
        "First line.\nSecond line.",
        "Different title",
    ) == "First line.\nSecond line."


def test_build_backfilled_transcript_document_text_uses_temporary_existing_docs_defaults() -> None:
    document_text = build_backfilled_transcript_document_text(
        document_title="Legacy Call",
        source_name="Legacy Call.mp3",
        source_mode="Google Drive: папка",
        existing_document_text="Legacy Call\n\nHello world.",
        created_at="2026-06-01T00:00:00+00:00",
    )

    assert document_text == (
        "Legacy Call\n\n"
        "Метаданные транскрипта\n"
        "Provider: ElevenLabs\n"
        "Model: scribe_v2\n"
        "Language: Русский\n"
        "Speakers: unknown\n"
        "Created at: 2026-06-01T00:00:00+00:00\n\n"
        "Транскрипция\n\n"
        "Hello world."
    )
    assert "Source file:" not in document_text
    assert "Source mode:" not in document_text
    assert "Standardized at:" not in document_text
    assert is_structured_transcript_document_text(document_text)


def test_docs_only_scan_indexes_google_docs() -> None:
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-1", "name": "Call", "mimeType": DOC_MIME, "webViewLink": "https://docs/1"},
    ]

    docs, scan = collect_existing_google_docs_for_standardization("root", recursive=False)

    assert scan["skipped_non_google_docs"] == 0
    assert docs == [
        {
            "id": "doc-1",
            "name": "Call",
            "mimeType": DOC_MIME,
            "webViewLink": "https://docs/1",
            "display_name": "Call",
        }
    ]


def test_recursive_docs_scan_finds_nested_google_docs() -> None:
    children = {
        "root": [{"id": "folder-1", "name": "Nested", "mimeType": FOLDER_MIME}],
        "folder-1": [{"id": "doc-1", "name": "Nested Call", "mimeType": DOC_MIME}],
    }
    HELPERS["list_drive_folder_children"] = lambda folder_id: children[folder_id]

    docs, scan = collect_existing_google_docs_for_standardization("root", recursive=True)

    assert scan["skipped_non_google_docs"] == 0
    assert [(doc["id"], doc["display_name"]) for doc in docs] == [("doc-1", "Nested/Nested Call")]


def test_docs_only_scan_ignores_pdfs_audio_video_and_other_files() -> None:
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-1", "name": "Call", "mimeType": DOC_MIME},
        {"id": "pdf-1", "name": "Call.pdf", "mimeType": "application/pdf"},
        {"id": "aud-1", "name": "Call.mp3", "mimeType": "audio/mpeg"},
        {"id": "vid-1", "name": "Call.mp4", "mimeType": "video/mp4"},
        {"id": "txt-1", "name": "Call.txt", "mimeType": "text/plain"},
    ]

    docs, scan = collect_existing_google_docs_for_standardization("root", recursive=False)

    assert [doc["id"] for doc in docs] == ["doc-1"]
    assert scan["skipped_non_google_docs"] == 4



def test_docs_only_scan_counts_nested_folders_when_not_recursive() -> None:
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "folder-1", "name": "Nested", "mimeType": FOLDER_MIME},
        {"id": "doc-1", "name": "Top Call", "mimeType": DOC_MIME},
    ]

    docs, scan = collect_existing_google_docs_for_standardization("root", recursive=False)

    assert [doc["id"] for doc in docs] == ["doc-1"]
    assert scan["folders_seen"] == 1
    assert scan["skipped_non_google_docs"] == 0


def test_docs_only_top_level_only_nested_folders_exposes_hint() -> None:
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "folder-1", "name": "Module 1", "mimeType": FOLDER_MIME},
        {"id": "folder-2", "name": "Module 2", "mimeType": FOLDER_MIME},
    ]

    report = standardize_existing_google_docs_in_folder("root", recursive=False, dry_run=True)

    assert report["google_docs_scanned"] == 0
    assert report["folders_seen"] == 2
    assert report["skipped_non_google_docs"] == 0
    assert "В выбранной папке верхнего уровня Google Docs не найдены" in report["hint"]


def test_recursive_docs_scan_uses_visited_folder_ids() -> None:
    calls = []
    children = {
        "root": [
            {"id": "folder-a", "name": "A", "mimeType": FOLDER_MIME},
            {"id": "folder-a", "name": "A Shortcut", "mimeType": FOLDER_MIME},
        ],
        "folder-a": [
            {"id": "root", "name": "Back To Root", "mimeType": FOLDER_MIME},
            {"id": "doc-1", "name": "Nested Call", "mimeType": DOC_MIME},
        ],
    }

    def list_children(folder_id):
        calls.append(folder_id)
        return children[folder_id]

    HELPERS["list_drive_folder_children"] = list_children

    docs, scan = collect_existing_google_docs_for_standardization("root", recursive=True)

    assert calls == ["root", "folder-a"]
    assert scan["folders_seen"] == 3
    assert [(doc["id"], doc["display_name"]) for doc in docs] == [("doc-1", "A/Nested Call")]


def test_recursive_docs_scan_stops_when_folder_limit_exceeded() -> None:
    children = {
        "root": [{"id": "folder-a", "name": "A", "mimeType": FOLDER_MIME}],
        "folder-a": [{"id": "doc-1", "name": "Nested Call", "mimeType": DOC_MIME}],
    }
    HELPERS["list_drive_folder_children"] = lambda folder_id: children[folder_id]

    report = standardize_existing_google_docs_in_folder(
        "root", recursive=True, dry_run=True, max_folders_scanned=1
    )

    assert report["google_docs_scanned"] == 0
    assert report["errors"]
    assert "лимит сканирования папок" in report["errors"][0]["reason"]


def test_docs_only_scan_stops_when_doc_limit_exceeded() -> None:
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-1", "name": "Call 1", "mimeType": DOC_MIME},
        {"id": "doc-2", "name": "Call 2", "mimeType": DOC_MIME},
    ]

    report = standardize_existing_google_docs_in_folder(
        "root", recursive=False, dry_run=True, max_google_docs_scanned=1
    )

    assert report["google_docs_scanned"] == 1
    assert report["errors"]
    assert "лимит сканирования Google Docs" in report["errors"][0]["reason"]

def test_docs_only_already_structured_docs_are_skipped() -> None:
    structured = build_structured_transcript_document_text(
        document_title="Call",
        transcript_text="Hello world.",
        metadata_lines=build_transcript_metadata_lines(
            source_name="call.mp3",
            source_mode="Google Drive: 1 файл",
            provider="ElevenLabs",
            provider_model="scribe_v2",
            language="Русский",
            speakers_enabled=None,
            created_at="2026-06-01 00:00 UTC",
        ),
    )
    writes = []
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-1", "name": "Call", "mimeType": DOC_MIME},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: structured
    HELPERS["write_title_and_text_to_doc"] = lambda **kwargs: writes.append(kwargs)

    report = standardize_existing_google_docs_in_folder("root", dry_run=False)

    assert report["google_docs_scanned"] == 1
    assert len(report["already_structured"]) == 1
    assert report["standardized"] == []
    assert writes == []


def test_docs_only_dry_run_counts_would_standardize_without_writing() -> None:
    writes = []
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-1", "name": "Call", "mimeType": DOC_MIME},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: "Call\n\nHello world."
    HELPERS["write_title_and_text_to_doc"] = lambda **kwargs: writes.append(kwargs)

    report = standardize_existing_google_docs_in_folder("root", dry_run=True)

    assert report["would_standardize"] == [{
        "doc_name": "Call",
        "link": "",
        "structured_status": "unstructured",
        "created_at_source": "unknown",
        "metadata_defaults_source": "temporary_existing_docs_backfill_defaults",
    }]
    assert report["standardized"] == []
    assert writes == []


def test_docs_only_apply_omits_missing_date_instead_of_using_doc_created_time() -> None:
    writes = []
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {
            "id": "doc-1",
            "name": "Call",
            "mimeType": DOC_MIME,
            "createdTime": "2026-06-03T11:46:04Z",
        },
    ]
    HELPERS["extract_google_doc_plain_text"] = (
        lambda document_id: "Call\n\nHello world."
    )
    HELPERS["write_title_and_text_to_doc"] = (
        lambda **kwargs: writes.append(kwargs)
    )

    report = standardize_existing_google_docs_in_folder(
        "root",
        dry_run=False,
    )

    assert report["standardized"][0]["created_at_source"] == "unknown"
    rewritten_text = writes[0]["transcript_text"]
    assert "Created at:" not in rewritten_text
    assert is_structured_transcript_document_text(rewritten_text)


def test_docs_only_apply_preserves_unstructured_header_date_once() -> None:
    writes = []
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {
            "id": "doc-1",
            "name": "Call",
            "mimeType": DOC_MIME,
            "createdTime": "2099-01-01T00:00:00Z",
        },
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: (
        "Call\n\nCreated at: 2026-06-03T11:46:04Z\n\nHello world."
    )
    HELPERS["write_title_and_text_to_doc"] = (
        lambda **kwargs: writes.append(kwargs)
    )

    standardize_existing_google_docs_in_folder("root", dry_run=False)

    rewritten_text = writes[0]["transcript_text"]
    assert rewritten_text.count("Created at:") == 1
    assert "Created at: 2026-06-03T11:46:04Z" in rewritten_text
    assert rewritten_text.endswith("Hello world.")



def test_docs_only_dry_run_counts_old_standard_as_would_standardize() -> None:
    writes = []
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-1", "name": "Call", "mimeType": DOC_MIME},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_legacy_standard_document()
    HELPERS["write_title_and_text_to_doc"] = lambda **kwargs: writes.append(kwargs)

    report = standardize_existing_google_docs_in_folder("root", dry_run=True)

    assert report["would_standardize"] == [{
        "doc_name": "Call",
        "link": "",
        "structured_status": "outdated",
        "created_at_source": "existing_metadata",
        "metadata_defaults_source": "temporary_existing_docs_backfill_defaults",
    }]
    assert report["already_structured"] == []
    assert report["standardized"] == []
    assert writes == []


def test_docs_only_apply_rewrites_old_standard_to_current_and_preserves_body() -> None:
    title = "Бонусный урок. Личные финансы для помогающего практика"
    body = (
        "Сегодня поговорим о личных финансах помогающего практика.\n\n"
        "Важно сохранять опору, не переписывать смысл и не терять исходные слова."
    )
    legacy = build_legacy_standard_document(title=title, body=body)
    writes = []
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-1", "name": title, "mimeType": DOC_MIME},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: legacy
    HELPERS["write_title_and_text_to_doc"] = lambda **kwargs: writes.append(kwargs)

    report = standardize_existing_google_docs_in_folder("root", dry_run=False)

    assert [item["doc_name"] for item in report["standardized"]] == [title]
    assert report["already_structured"] == []
    assert len(writes) == 1
    rewritten_text = writes[0]["transcript_text"]
    assert "Source file:" not in rewritten_text
    assert "Source mode:" not in rewritten_text
    assert "Provider: ElevenLabs" in rewritten_text
    assert "Model: scribe_v2" in rewritten_text
    assert "Language: Русский" in rewritten_text
    assert "Speakers: unknown" in rewritten_text
    assert "Created at: 2026-06-02T10:26:40.369268+00:00" in rewritten_text
    assert body in rewritten_text
    assert is_structured_transcript_document_text(rewritten_text)

    HELPERS["extract_google_doc_plain_text"] = lambda document_id: rewritten_text
    subsequent_dry_run = standardize_existing_google_docs_in_folder("root", dry_run=True)
    assert subsequent_dry_run["would_standardize"] == []
    assert [item["doc_name"] for item in subsequent_dry_run["already_structured"]] == [title]


def test_docs_only_standardization_localizes_legacy_speaker_labels() -> None:
    rewritten_text = build_docs_only_standardized_transcript_document_text(
        document_title="Созвон",
        existing_document_text=build_legacy_standard_document(
            title="Созвон",
            body="Speaker 1:\nПривет.\nSpeaker 2:\nЗдравствуйте.",
        ),
        created_at="2026-06-02T10:26:40.369268+00:00",
    )

    assert "Спикер 1:\nПривет." in rewritten_text
    assert "Спикер 2:\nЗдравствуйте." in rewritten_text
    assert "Speaker 1:" not in rewritten_text
    assert classify_existing_google_doc_transcript_standard(rewritten_text) == "current_standard"


def test_docs_only_apply_rewrites_only_not_yet_structured_google_docs() -> None:
    structured = build_structured_transcript_document_text(
        document_title="Done",
        transcript_text="Already done.",
        metadata_lines=build_transcript_metadata_lines(
            source_name="not available",
            source_mode="existing_google_doc_standardization",
            provider="ElevenLabs",
            provider_model="scribe_v2",
            language="Русский",
            speakers_enabled=None,
            created_at="2026-06-01 00:00 UTC",
        ),
    )
    texts = {"doc-1": "Todo\n\nHello world.", "doc-2": structured}
    writes = []
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-1", "name": "Todo", "mimeType": DOC_MIME},
        {"id": "doc-2", "name": "Done", "mimeType": DOC_MIME},
        {"id": "pdf-1", "name": "Ignored.pdf", "mimeType": "application/pdf"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: texts[document_id]
    HELPERS["write_title_and_text_to_doc"] = lambda **kwargs: writes.append(kwargs)

    report = standardize_existing_google_docs_in_folder("root", dry_run=False)

    assert report["google_docs_scanned"] == 2
    assert report["skipped_non_google_docs"] == 1
    assert [item["doc_name"] for item in report["standardized"]] == ["Todo"]
    assert [item["doc_name"] for item in report["already_structured"]] == ["Done"]
    assert len(writes) == 1
    assert writes[0]["document_id"] == "doc-1"
    assert writes[0]["title"] == "Todo"
    assert writes[0]["clear_first"] is True
    assert "Hello world." in writes[0]["transcript_text"]


def test_docs_only_metadata_is_honest_and_conservative() -> None:
    document_text = build_docs_only_standardized_transcript_document_text(
        document_title="Existing Doc",
        existing_document_text="Existing Doc\n\nHello world.",
        created_at="2026-06-01T00:00:00+00:00",
    )

    assert "Source file:" not in document_text
    assert "Source mode:" not in document_text
    assert "Provider: ElevenLabs" in document_text
    assert "Model: scribe_v2" in document_text
    assert "Language: Русский" in document_text
    assert "Speakers: unknown" in document_text
    assert "Created at: 2026-06-01T00:00:00+00:00" in document_text


def test_docs_only_flow_does_not_call_provider_create_doc_or_manifest_helpers() -> None:
    forbidden_calls = []
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-1", "name": "Call", "mimeType": DOC_MIME},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: "Call\n\nHello world."
    HELPERS["write_title_and_text_to_doc"] = lambda **kwargs: None
    for name in [
        "transcribe_fileobj",
        "transcribe_openai_fileobj",
        "transcribe_media_path",
        "create_google_doc",
        "save_manifest",
        "mark_manifest_done",
        "mark_manifest_failed",
    ]:
        HELPERS[name] = lambda *args, _name=name, **kwargs: forbidden_calls.append(_name)

    standardize_existing_google_docs_in_folder("root", dry_run=False)

    assert forbidden_calls == []


def test_current_shaped_old_backfill_metadata_needs_refresh() -> None:
    document_text = build_old_backfill_current_standard_document(title="Old Backfill", body="Original body.")

    assert is_structured_transcript_document_text(document_text)
    assert existing_google_doc_backfill_metadata_needs_refresh(document_text)


def test_docs_only_dry_run_refreshes_current_shaped_old_backfill_without_writing() -> None:
    writes = []
    document_text = build_old_backfill_current_standard_document(title="Old Backfill", body="Original body.")
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-1", "name": "Old Backfill", "mimeType": DOC_MIME, "createdTime": "2026-06-03T11:46:04Z"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: document_text
    HELPERS["write_title_and_text_to_doc"] = lambda **kwargs: writes.append(kwargs)

    report = standardize_existing_google_docs_in_folder("root", dry_run=True)

    assert report["would_standardize"] == [{
        "doc_name": "Old Backfill",
        "link": "",
        "structured_status": "current_metadata_refresh",
        "created_at_source": "existing_metadata",
        "metadata_defaults_source": "temporary_existing_docs_backfill_defaults",
    }]
    assert report["already_structured"] == []
    assert writes == []


def test_docs_only_apply_refreshes_old_backfill_and_preserves_existing_date() -> None:
    body = "First line.\n\nSecond line stays exactly the same."
    document_text = build_old_backfill_current_standard_document(title="Old Backfill", body=body)
    writes = []
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {
            "id": "doc-1",
            "name": "Old Backfill",
            "mimeType": DOC_MIME,
            "createdTime": "2026-06-03T11:46:04Z",
        },
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: document_text
    HELPERS["write_title_and_text_to_doc"] = lambda **kwargs: writes.append(kwargs)

    report = standardize_existing_google_docs_in_folder("root", dry_run=False)

    assert [item["structured_status"] for item in report["standardized"]] == ["current_metadata_refresh"]
    assert len(writes) == 1
    rewritten_text = writes[0]["transcript_text"]
    assert "Provider: ElevenLabs" in rewritten_text
    assert "Model: scribe_v2" in rewritten_text
    assert "Language: Русский" in rewritten_text
    assert "Speakers: unknown" in rewritten_text
    assert "Created at: 2026-06-01T00:00:00+00:00" in rewritten_text
    assert "Created at: 2026-06-03 11:46 UTC" not in rewritten_text
    assert "Source file:" not in rewritten_text
    assert "Source mode:" not in rewritten_text
    assert "Standardized at:" not in rewritten_text
    assert body in rewritten_text
    assert is_structured_transcript_document_text(rewritten_text)


def test_current_shaped_correct_backfill_and_openai_docs_are_already_current() -> None:
    correct_backfill = build_structured_transcript_document_text(
        document_title="Correct Backfill",
        transcript_text="Backfill body.",
        metadata_lines=build_transcript_metadata_lines(
            source_name="ignored",
            source_mode="ignored",
            provider="ElevenLabs",
            provider_model="scribe_v2",
            language="Русский",
            speakers_enabled=None,
            created_at="2026-06-03 11:46 UTC",
        ),
    )
    openai_doc = build_structured_transcript_document_text(
        document_title="OpenAI Doc",
        transcript_text="OpenAI body.",
        metadata_lines=build_transcript_metadata_lines(
            source_name="ignored",
            source_mode="ignored",
            provider="OpenAI",
            provider_model="gpt-4o-transcribe",
            language="Автоопределение",
            speakers_enabled=False,
            created_at="2026-06-03T11:46:04Z",
        ),
    )
    texts = {"doc-1": correct_backfill, "doc-2": openai_doc}
    writes = []
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-1", "name": "Correct Backfill", "mimeType": DOC_MIME},
        {"id": "doc-2", "name": "OpenAI Doc", "mimeType": DOC_MIME},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: texts[document_id]
    HELPERS["write_title_and_text_to_doc"] = lambda **kwargs: writes.append(kwargs)

    report = standardize_existing_google_docs_in_folder("root", dry_run=False)

    assert not existing_google_doc_backfill_metadata_needs_refresh(correct_backfill)
    assert not existing_google_doc_backfill_metadata_needs_refresh(openai_doc)
    assert report["would_standardize"] == []
    assert report["standardized"] == []
    assert [item["doc_name"] for item in report["already_structured"]] == ["Correct Backfill", "OpenAI Doc"]
    assert writes == []

def build_old_backfill_current_standard_document(title: str = "Call", body: str = "Hello world.") -> str:
    return build_structured_transcript_document_text(
        document_title=title,
        transcript_text=body,
        metadata_lines=build_transcript_metadata_lines(
            source_name="ignored.mp3",
            source_mode="Google Drive: 1 файл",
            provider="unknown",
            provider_model="unknown",
            language="unknown",
            speakers_enabled=None,
            created_at="2026-06-01T00:00:00+00:00",
        ),
    )


def build_current_standard_document(title: str = "Call", body: str = "Hello world.") -> str:
    return build_structured_transcript_document_text(
        document_title=title,
        transcript_text=body,
        metadata_lines=build_transcript_metadata_lines(
            source_name="ignored.mp3",
            source_mode="Google Drive: 1 файл",
            provider="ElevenLabs",
            provider_model="scribe_v2",
            language="Русский",
            speakers_enabled=None,
            created_at="2026-06-01 00:00 UTC",
        ),
    )


def test_existing_google_doc_manifest_signature_is_stable_doc_id_based_and_name_independent() -> None:
    first = build_existing_google_doc_manifest_signature("doc-1")
    second = build_existing_google_doc_manifest_signature("doc-1")
    other = build_existing_google_doc_manifest_signature("doc-2")

    assert first == second
    assert first != other
    assert first == HELPERS["json_sha256"]({"source_type": "existing_google_doc", "doc_id": "doc-1"})


def test_classify_existing_google_doc_transcript_standard_current_outdated_unstructured() -> None:
    assert classify_existing_google_doc_transcript_standard(build_current_standard_document()) == "current_standard"
    assert classify_existing_google_doc_transcript_standard(build_legacy_standard_document()) == "outdated_standard"
    assert classify_existing_google_doc_transcript_standard("Meeting notes without transcript headings") == "unstructured"



def test_extract_google_doc_id_from_url_parses_google_docs_links() -> None:
    assert extract_google_doc_id_from_url("https://docs.google.com/document/d/doc-123/edit") == "doc-123"
    assert extract_google_doc_id_from_url("https://docs.google.com/document/d/doc-123/edit?usp=drivesdk") == "doc-123"
    assert extract_google_doc_id_from_url("") == ""
    assert extract_google_doc_id_from_url("not a google doc url") == ""
    assert extract_google_doc_id_from_url("https://example.com/document/d/doc-123/edit") == ""


def test_find_manifest_entries_referencing_google_doc_finds_source_entries_by_doc_link() -> None:
    manifest = {
        "version": 1,
        "entries": {
            "source-a": {
                "status": "done",
                "source_name": "Lecture.mp3",
                "doc_name": "Lecture",
                "doc_link": "https://docs.google.com/document/d/doc-123/edit?usp=drivesdk",
            },
            "source-b": {
                "status": "done",
                "source_name": "Other.mp3",
                "doc_link": "https://docs.google.com/document/d/doc-999/edit",
            },
        },
    }

    matches = find_manifest_entries_referencing_google_doc(manifest, "doc-123")

    assert len(matches) == 1
    assert matches[0]["source_signature"] == "source-a"
    assert matches[0]["source_linked_manifest_match_type"] == "doc_id_from_doc_link"


def test_find_manifest_entries_referencing_google_doc_finds_source_entries_by_explicit_doc_id() -> None:
    manifest = {
        "version": 1,
        "entries": {
            "source-a": {
                "status": "done",
                "source_name": "Lecture.mp3",
                "doc_id": "doc-123",
            },
        },
    }

    matches = find_manifest_entries_referencing_google_doc(manifest, "doc-123")

    assert len(matches) == 1
    assert matches[0]["source_linked_manifest_match_type"] == "doc_id"


def test_find_manifest_entries_referencing_google_doc_excludes_doc_registry_entries() -> None:
    signature = build_existing_google_doc_manifest_signature("doc-123")
    manifest = {
        "version": 1,
        "entries": {
            signature: {
                "source_signature": signature,
                "source_type": "existing_google_doc",
                "status": "doc_registered",
                "doc_id": "doc-123",
                "doc_link": "https://docs.google.com/document/d/doc-123/edit",
                "source_meta": {"registration_mode": "existing_google_doc_manifest_registration"},
            },
            "source-a": {
                "status": "doc_registered",
                "doc_id": "doc-123",
            },
            "source-b": {
                "status": "done",
                "source_meta": {"registration_mode": "existing_google_doc_manifest_registration"},
                "doc_id": "doc-123",
            },
        },
    }

    assert find_manifest_entries_referencing_google_doc(manifest, "doc-123") == []


def test_manifest_registration_dry_run_reports_source_linked_manifest_match_without_already_registered() -> None:
    manifest = {
        "version": 1,
        "entries": {
            "old-source": {
                "status": "done",
                "source_name": "Lecture.mp3",
                "doc_name": "Lecture",
                "doc_link": "https://docs.google.com/document/d/doc-123/edit",
            },
        },
    }
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-123", "name": "Lecture", "mimeType": DOC_MIME, "webViewLink": "https://docs.google.com/document/d/doc-123/edit"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document(title="Lecture")
    HELPERS["load_manifest_read_only"] = lambda: manifest

    report = register_existing_google_docs_in_manifest("folder-root", dry_run=True)

    assert len(report["would_register"]) == 1
    assert report["already_registered"] == []
    assert report["source_linked_manifest_matches"] == 1
    assert len(report["docs_with_source_linked_manifest_matches"]) == 1
    assert len(report["would_register_with_source_linked_match"]) == 1
    assert report["would_register_without_source_linked_match"] == []
    result_item = report["would_register"][0]
    assert result_item["source_linked_manifest_match_count"] == 1
    assert result_item["source_linked_manifest_statuses"] == ["done"]
    assert result_item["source_linked_manifest_doc_names"] == ["Lecture"]
    assert result_item["source_linked_manifest_match_type"] == "doc_id_from_doc_link"


def test_manifest_registration_dry_run_reports_no_source_linked_manifest_match() -> None:
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-123", "name": "Lecture", "mimeType": DOC_MIME},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document(title="Lecture")
    HELPERS["load_manifest_read_only"] = lambda: {"version": 1, "entries": {}}

    report = register_existing_google_docs_in_manifest("folder-root", dry_run=True)

    assert len(report["would_register"]) == 1
    assert report["source_linked_manifest_matches"] == 0
    assert report["docs_with_source_linked_manifest_matches"] == []
    assert report["would_register_with_source_linked_match"] == []
    assert len(report["would_register_without_source_linked_match"]) == 1


def test_manifest_registration_already_registered_is_only_existing_google_doc_registry_entry() -> None:
    source_manifest = {
        "version": 1,
        "entries": {
            "old-source": {
                "status": "done",
                "source_name": "Lecture.mp3",
                "doc_link": "https://docs.google.com/document/d/doc-123/edit",
            },
        },
    }
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-123", "name": "Lecture", "mimeType": DOC_MIME},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document(title="Lecture")
    HELPERS["load_manifest_read_only"] = lambda: source_manifest

    source_only = register_existing_google_docs_in_manifest("folder-root", dry_run=True)

    assert len(source_only["would_register"]) == 1
    assert source_only["already_registered"] == []

    signature = build_existing_google_doc_manifest_signature("doc-123")
    registry_manifest = {"version": 1, "entries": dict(source_manifest["entries"])}
    registry_manifest["entries"][signature] = {
        "source_signature": signature,
        "source_type": "existing_google_doc",
        "status": "doc_registered",
        "standard": "transcript_doc",
        "doc_id": "doc-123",
        "doc_name": "Lecture",
        "doc_link": "https://docs.google.com/document/d/doc-123/edit",
        "doc_path": "Lecture",
        "doc_mime_type": DOC_MIME,
        "structured_status": "current_standard",
        "source_name": "Lecture",
        "note": "",
        "updated_at": "2026-06-01T00:00:00+00:00",
        "source_meta": {
            "folder_id": "folder-root",
            "folder_path": "",
            "recursive_scan": False,
            "registration_mode": "existing_google_doc_manifest_registration",
        },
    }
    HELPERS["load_manifest_read_only"] = lambda: registry_manifest

    registered = register_existing_google_docs_in_manifest("folder-root", dry_run=True)

    assert [item["doc_id"] for item in registered["already_registered"]] == ["doc-123"]
    assert registered["source_linked_manifest_matches"] == 1
    assert len(registered["already_registered_with_source_linked_match"]) == 1


def test_manifest_registration_apply_creates_registry_entry_and_preserves_source_linked_entry() -> None:
    saved = []
    manifest = {
        "version": 1,
        "entries": {
            "old-source": {
                "status": "done",
                "source_name": "Lecture.mp3",
                "doc_name": "Lecture",
                "doc_link": "https://docs.google.com/document/d/doc-123/edit",
            },
        },
    }
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-123", "name": "Lecture", "mimeType": DOC_MIME, "webViewLink": "https://docs.google.com/document/d/doc-123/edit"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document(title="Lecture")
    HELPERS["load_manifest"] = lambda: manifest
    HELPERS["save_manifest"] = lambda incoming: saved.append(json.loads(json.dumps(incoming)))

    report = register_existing_google_docs_in_manifest("folder-root", dry_run=False)

    assert [item["doc_id"] for item in report["registered"]] == ["doc-123"]
    assert report["source_linked_manifest_matches"] == 1
    signature = build_existing_google_doc_manifest_signature("doc-123")
    assert set(manifest["entries"]) == {"old-source", signature}
    assert manifest["entries"]["old-source"]["status"] == "done"
    assert manifest["entries"][signature]["source_type"] == "existing_google_doc"
    assert manifest["entries"][signature]["status"] == "doc_registered"
    assert len([entry for entry in manifest["entries"].values() if entry.get("source_type") == "existing_google_doc"]) == 1
    assert saved


def test_manifest_registration_dry_run_does_not_call_manifest_write_docs_or_provider_helpers() -> None:
    calls = []
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-123", "name": "Lecture", "mimeType": DOC_MIME},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document(title="Lecture")
    HELPERS["load_manifest_read_only"] = lambda: {"version": 1, "entries": {}}
    HELPERS["get_or_create_manifest_file"] = lambda: calls.append("get_or_create_manifest_file")
    HELPERS["save_manifest"] = lambda manifest: calls.append("save_manifest")
    HELPERS["write_title_and_text_to_doc"] = lambda **kwargs: calls.append("write_title_and_text_to_doc")
    for name in [
        "transcribe_fileobj",
        "transcribe_openai_fileobj",
        "transcribe_media_path",
        "create_google_doc",
    ]:
        HELPERS[name] = lambda *args, _name=name, **kwargs: calls.append(_name)

    register_existing_google_docs_in_manifest("folder-root", dry_run=True)

    assert calls == []

def test_manifest_registration_dry_run_scans_classifies_and_does_not_save_or_mutate_docs() -> None:
    calls = []
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-1", "name": "Current", "mimeType": DOC_MIME, "webViewLink": "https://docs/doc-1"},
        {"id": "pdf-1", "name": "Ignored.pdf", "mimeType": "application/pdf"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document()
    HELPERS["load_manifest"] = lambda: {"version": 1, "entries": {}}
    HELPERS["save_manifest"] = lambda manifest: calls.append("save_manifest")
    HELPERS["write_title_and_text_to_doc"] = lambda **kwargs: calls.append("write_title_and_text_to_doc")
    for name in [
        "transcribe_fileobj",
        "transcribe_openai_fileobj",
        "transcribe_media_path",
        "create_google_doc",
    ]:
        HELPERS[name] = lambda *args, _name=name, **kwargs: calls.append(_name)

    report = register_existing_google_docs_in_manifest(
        "folder-root", output_folder_path="MyDrive/Transcripts", dry_run=True
    )

    assert report["google_docs_scanned"] == 1
    assert report["skipped_non_google_docs"] == 1
    assert report["current_standard"] == 1
    assert [item["doc_id"] for item in report["would_register"]] == ["doc-1"]
    assert report["registered"] == []
    assert calls == []
    assert report["notice"] == "Manifest registration does not change Google Docs content."


def test_manifest_registration_apply_writes_existing_google_doc_manifest_entry_without_docs_mutation() -> None:
    saved = []
    writes = []
    manifest = {"version": 1, "entries": {}}
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-1", "name": "Call", "mimeType": DOC_MIME, "webViewLink": "https://docs/doc-1"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document(title="Call")
    HELPERS["load_manifest"] = lambda: manifest
    HELPERS["save_manifest"] = lambda incoming: saved.append(json.loads(json.dumps(incoming)))
    HELPERS["write_title_and_text_to_doc"] = lambda **kwargs: writes.append(kwargs)

    report = register_existing_google_docs_in_manifest(
        "folder-root", output_folder_path="MyDrive/Transcripts", dry_run=False
    )

    assert [item["doc_id"] for item in report["registered"]] == ["doc-1"]
    assert saved
    assert writes == []
    signature = build_existing_google_doc_manifest_signature("doc-1")
    entry = saved[-1]["entries"][signature]
    assert entry["source_signature"] == signature
    assert entry["source_type"] == "existing_google_doc"
    assert entry["status"] == "doc_registered"
    assert entry["doc_id"] == "doc-1"
    assert entry["doc_name"] == "Call"
    assert entry["doc_link"] == "https://docs/doc-1"
    assert entry["doc_path"] == "MyDrive/Transcripts/Call"
    assert entry["structured_status"] == "current_standard"
    assert entry["source_meta"]["registration_mode"] == "existing_google_doc_manifest_registration"


def test_manifest_registration_apply_twice_does_not_duplicate_and_detects_already_registered() -> None:
    saved = []
    manifest = {"version": 1, "entries": {}}
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-1", "name": "Call", "mimeType": DOC_MIME, "webViewLink": "https://docs/doc-1"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document(title="Call")
    HELPERS["load_manifest"] = lambda: manifest
    HELPERS["load_manifest_read_only"] = lambda: manifest
    HELPERS["save_manifest"] = lambda incoming: saved.append(json.loads(json.dumps(incoming)))

    first = register_existing_google_docs_in_manifest("folder-root", dry_run=False)
    second = register_existing_google_docs_in_manifest("folder-root", dry_run=False)
    dry_run = register_existing_google_docs_in_manifest("folder-root", dry_run=True)
    HELPERS["load_manifest_read_only"] = ORIGINAL_LOAD_MANIFEST_READ_ONLY

    assert len(manifest["entries"]) == 1
    assert len(first["registered"]) == 1
    assert second["registered"] == []
    assert [item["doc_id"] for item in second["already_registered"]] == ["doc-1"]
    assert [item["doc_id"] for item in dry_run["already_registered"]] == ["doc-1"]


def test_manifest_registration_records_outdated_current_and_unstructured_status_without_changing_content() -> None:
    original_texts = {
        "doc-old": build_legacy_standard_document(title="Old"),
        "doc-current": build_current_standard_document(title="Current"),
        "doc-plain": "Plain notes only",
    }
    texts = dict(original_texts)
    manifest = {"version": 1, "entries": {}}
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-old", "name": "Old", "mimeType": DOC_MIME},
        {"id": "doc-current", "name": "Current", "mimeType": DOC_MIME},
        {"id": "doc-plain", "name": "Plain", "mimeType": DOC_MIME},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: texts[document_id]
    HELPERS["load_manifest"] = lambda: manifest
    HELPERS["save_manifest"] = lambda incoming: None
    HELPERS["write_title_and_text_to_doc"] = lambda **kwargs: texts.__setitem__(kwargs["document_id"], kwargs["transcript_text"])

    report = register_existing_google_docs_in_manifest("folder-root", dry_run=False)

    statuses = {entry["doc_id"]: entry["structured_status"] for entry in manifest["entries"].values()}
    assert statuses == {
        "doc-current": "current_standard",
        "doc-old": "outdated_standard",
        "doc-plain": "unstructured",
    }
    assert report["current_standard"] == 1
    assert report["outdated_standard"] == 1
    assert report["unstructured"] == 1
    assert texts == original_texts


def test_manifest_registration_recursive_scan_uses_visited_folders_and_reports_limits() -> None:
    calls = []
    children = {
        "root": [
            {"id": "folder-a", "name": "A", "mimeType": FOLDER_MIME},
            {"id": "folder-a", "name": "A Shortcut", "mimeType": FOLDER_MIME},
        ],
        "folder-a": [
            {"id": "root", "name": "Back", "mimeType": FOLDER_MIME},
            {"id": "doc-1", "name": "Nested", "mimeType": DOC_MIME},
        ],
    }

    def list_children(folder_id):
        calls.append(folder_id)
        return children[folder_id]

    HELPERS["list_drive_folder_children"] = list_children
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document()
    HELPERS["load_manifest"] = lambda: {"version": 1, "entries": {}}

    report = register_existing_google_docs_in_manifest("root", recursive=True, dry_run=True)
    assert calls == ["root", "folder-a"]
    assert report["folders_seen"] == 3
    assert [item["doc_name"] for item in report["would_register"]] == ["A/Nested"]

    HELPERS["list_drive_folder_children"] = lambda folder_id: children[folder_id]
    limited = register_existing_google_docs_in_manifest("root", recursive=True, dry_run=True, max_folders=1)
    assert limited["errors"]
    assert "лимит сканирования папок" in limited["errors"][0]["reason"]

    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-1", "name": "One", "mimeType": DOC_MIME},
        {"id": "doc-2", "name": "Two", "mimeType": DOC_MIME},
    ]
    doc_limited = register_existing_google_docs_in_manifest("root", dry_run=True, max_docs=1)
    assert doc_limited["google_docs_scanned"] == 1
    assert "лимит сканирования Google Docs" in doc_limited["errors"][0]["reason"]


def test_normal_transcription_manifest_skip_behavior_remains_unchanged() -> None:
    now = datetime.now(timezone.utc).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
    manifest = {
        "version": 1,
        "entries": {
            "done": {"status": "done", "settings_signature": "settings-a"},
            "imported": {"status": "imported_done", "settings_signature": "other"},
            "fresh": {"status": "in_progress", "started_at": now},
            "stale": {"status": "in_progress", "started_at": old},
        },
    }

    assert should_skip_by_manifest(manifest, "done", "settings-a")[0] is True
    assert should_skip_by_manifest(manifest, "done", "settings-b")[0] is False
    assert should_skip_by_manifest(manifest, "imported", "settings-b")[0] is True
    assert should_skip_by_manifest(manifest, "fresh", "settings-b")[0] is True
    assert should_skip_by_manifest(manifest, "stale", "settings-b")[0] is False


def reset_manifest_cache_for_test() -> None:
    HELPERS["load_manifest_read_only"] = ORIGINAL_LOAD_MANIFEST_READ_ONLY
    HELPERS["MANIFEST_CACHE"].update({
        "state_folder_id": None,
        "manifest_folder_id": None,
        "file_id": None,
        "data": None,
    })


def test_manifest_registration_dry_run_read_only_loader_does_not_create_or_save_when_manifest_missing() -> None:
    reset_manifest_cache_for_test()
    calls = []
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-new", "name": "New", "mimeType": DOC_MIME},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document(title="New")
    HELPERS["find_file_in_folder"] = lambda folder_id, file_name: calls.append(("find", folder_id, file_name)) or None
    HELPERS["get_or_create_manifest_file"] = lambda: calls.append(("get_or_create",))
    HELPERS["load_manifest"] = lambda: calls.append(("load_manifest",)) or {"version": 1, "entries": {}}
    HELPERS["save_manifest"] = lambda manifest: calls.append(("save_manifest",))

    report = register_existing_google_docs_in_manifest("folder-root", dry_run=True)

    assert [item["doc_id"] for item in report["would_register"]] == ["doc-new"]
    assert ("get_or_create",) not in calls
    assert ("load_manifest",) not in calls
    assert ("save_manifest",) not in calls
    assert calls == [("find", "root", "VoiceOps Workspace")]


def test_manifest_registration_dry_run_reads_existing_manifest_without_creation() -> None:
    reset_manifest_cache_for_test()
    calls = []
    signature = build_existing_google_doc_manifest_signature("doc-1")
    existing_entry = {
        "source_signature": signature,
        "source_type": "existing_google_doc",
        "status": "doc_registered",
        "standard": "transcript_doc",
        "doc_id": "doc-1",
        "doc_name": "Call",
        "doc_link": "https://docs/doc-1",
        "doc_path": "Call",
        "doc_mime_type": DOC_MIME,
        "structured_status": "current_standard",
        "source_name": "Call",
        "note": "",
        "updated_at": "2026-06-01T00:00:00+00:00",
        "source_meta": {
            "folder_id": "folder-root",
            "folder_path": "",
            "recursive_scan": False,
            "registration_mode": "existing_google_doc_manifest_registration",
        },
    }
    existing_manifest = {"version": 1, "entries": {signature: existing_entry}}

    def find_file(folder_id, file_name):
        calls.append(("find", folder_id, file_name))
        found = {
            ("root", "VoiceOps Workspace"): {"id": "state-id", "name": "VoiceOps Workspace"},
            ("state-id", "manifest"): {"id": "manifest-folder-id", "name": "manifest"},
            ("manifest-folder-id", "elevenlabs_transcription_manifest.json"): {
                "id": "manifest-file-id",
                "name": "elevenlabs_transcription_manifest.json",
            },
        }
        return found.get((folder_id, file_name))

    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-1", "name": "Call", "mimeType": DOC_MIME, "webViewLink": "https://docs/doc-1"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document(title="Call")
    HELPERS["find_file_in_folder"] = find_file
    HELPERS["read_manifest_file_by_id"] = lambda file_id: calls.append(("read", file_id)) or existing_manifest
    HELPERS["get_or_create_manifest_file"] = lambda: calls.append(("get_or_create",))
    HELPERS["save_manifest"] = lambda manifest: calls.append(("save_manifest",))

    report = register_existing_google_docs_in_manifest("folder-root", dry_run=True)

    assert [item["doc_id"] for item in report["already_registered"]] == ["doc-1"]
    assert ("read", "manifest-file-id") in calls
    assert ("get_or_create",) not in calls
    assert ("save_manifest",) not in calls


def test_manifest_registration_apply_uses_existing_load_and_save_behavior() -> None:
    reset_manifest_cache_for_test()
    calls = []
    manifest = {"version": 1, "entries": {}}
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-apply", "name": "Apply", "mimeType": DOC_MIME},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document(title="Apply")
    HELPERS["load_manifest"] = lambda: calls.append(("load_manifest",)) or manifest
    HELPERS["load_manifest_read_only"] = lambda: calls.append(("load_manifest_read_only",)) or manifest
    HELPERS["save_manifest"] = lambda incoming: calls.append(("save_manifest", json.loads(json.dumps(incoming))))

    report = register_existing_google_docs_in_manifest("folder-root", dry_run=False)

    assert [item["doc_id"] for item in report["registered"]] == ["doc-apply"]
    assert [call[0] for call in calls] == ["load_manifest", "save_manifest"]
    assert "load_manifest_read_only" not in [call[0] for call in calls]


def test_manifest_v2_default_schema_has_decoupled_summary_standard_check() -> None:
    manifest = make_manifest_v2_default(updated_at="2026-06-01T00:00:00+00:00")

    assert manifest["version"] == 2
    assert manifest["schema"] == "voiceops_manifest_v2"
    assert manifest["documents"] == {}
    assert manifest["sources"] == {}
    assert manifest["summary"]["standard_check"]["target_standard"] == "transcript_doc"
    assert "transcript_standard" not in manifest
    assert "structured_status" not in manifest


def test_build_transcript_standard_check_current_legacy_unstructured_and_unreadable() -> None:
    checked_at = "2026-06-01T00:00:00+00:00"

    current = build_transcript_standard_check(build_current_standard_document(), checked_at)
    legacy = build_transcript_standard_check(build_legacy_standard_document(), checked_at)
    plain = build_transcript_standard_check("Just plain notes", checked_at)
    unreadable = build_transcript_standard_check("", checked_at, unreadable=True)
    future = build_transcript_standard_check(build_current_standard_document(), checked_at, target_standard="transcript_doc_v1.3")
    manifest = make_manifest_v2_default(updated_at=checked_at)

    assert current["status"] == "current"
    assert current["detected_standard"] == "transcript_doc"
    assert legacy["status"] == "outdated"
    assert legacy["detected_standard"] == "legacy_v1"
    assert plain["status"] == "unstructured"
    assert unreadable["status"] == "unreadable"
    assert future["target_standard"] == "transcript_doc_v1.3"
    assert manifest["version"] == 2


def test_v1_to_v2_migration_separates_documents_sources_links_and_omits_text() -> None:
    checked_at = "2026-06-01T00:00:00+00:00"
    registry_sig = build_existing_google_doc_manifest_signature("doc-a")
    manifest_v1 = {
        "version": 1,
        "entries": {
            registry_sig: {
                "source_signature": registry_sig,
                "source_type": "existing_google_doc",
                "status": "doc_registered",
                "doc_id": "doc-a",
                "doc_name": "Doc A",
                "doc_link": "https://docs.google.com/document/d/doc-a/edit",
                "structured_status": "current_standard",
                "transcript_text": "SHOULD_NOT_BE_COPIED_TO_DOCUMENT",
                "source_meta": {"folder_id": "old-folder", "folder_path": "Old"},
            },
            "source-by-link": {
                "source_signature": "source-by-link",
                "source_type": "drive",
                "source_name": "Audio A",
                "settings_signature": "settings",
                "status": "done",
                "doc_name": "Doc A",
                "doc_link": "https://docs.google.com/document/d/doc-a/edit",
                "source_meta": {"file_id": "file-a"},
                "transcript_text": "SHOULD_NOT_BE_COPIED_TO_SOURCE",
            },
            "source-by-id": {
                "source_signature": "source-by-id",
                "source_type": "drive",
                "source_name": "Audio B",
                "status": "done",
                "doc_id": "doc-b",
            },
            "orphan": {
                "source_signature": "orphan",
                "source_type": "local_path",
                "source_name": "No match",
                "status": "done",
            },
        },
    }
    docs = [
        {"id": "doc-a", "name": "Doc A", "mimeType": DOC_MIME, "display_name": "Doc A"},
        {"id": "doc-b", "name": "Doc B", "mimeType": DOC_MIME, "display_name": "Doc B"},
    ]
    checks = {
        "doc-a": build_transcript_standard_check(build_current_standard_document("Doc A"), checked_at),
        "doc-b": build_transcript_standard_check("plain", checked_at),
    }

    manifest_v2, counters = build_manifest_v2_from_existing_manifest_and_docs(
        manifest_v1, docs, checks, "folder-root", "MyDrive/Psych", False, checked_at
    )

    assert manifest_v2["version"] == 2
    assert manifest_v2["schema"] == "voiceops_manifest_v2"
    assert "entries" not in manifest_v2
    assert set(manifest_v2["documents"]) == {"doc-a", "doc-b"}
    assert set(manifest_v2["sources"]) == {"source-by-link", "source-by-id", "orphan"}
    assert manifest_v2["sources"]["source-by-link"]["doc_id"] == "doc-a"
    assert manifest_v2["sources"]["source-by-id"]["doc_id"] == "doc-b"
    assert manifest_v2["sources"]["orphan"]["doc_id"] == ""
    assert "source-by-link" in manifest_v2["documents"]["doc-a"]["source_signatures"]
    assert "source-by-id" in manifest_v2["documents"]["doc-b"]["source_signatures"]
    assert counters == {"source_entries_migrated": 3, "doc_registry_entries_migrated": 1}
    serialized = json.dumps(manifest_v2)
    assert "SHOULD_NOT_BE_COPIED" not in serialized


def test_existing_v2_rebuild_is_idempotent_preserves_sources_and_updates_standard_check() -> None:
    checked_at = "2026-06-01T00:00:00+00:00"
    v2 = make_manifest_v2_default(updated_at="old")
    v2["documents"]["doc-a"] = {
        "doc_id": "doc-a",
        "doc_name": "Doc A",
        "doc_link": "https://docs.google.com/document/d/doc-a/edit",
        "doc_path": "Doc A",
        "doc_mime_type": DOC_MIME,
        "document_type": "google_doc_transcript",
        "registration_status": "registered",
        "source_signatures": ["source-a"],
        "standard_check": {"target_standard": "transcript_doc", "detected_standard": "unknown", "status": "unstructured", "checked_at": "old", "checker_version": "transcript_standard_checker_v1"},
        "updated_at": "old",
        "source_meta": {},
    }
    v2["sources"]["source-a"] = {"source_signature": "source-a", "source_type": "drive", "source_name": "Audio", "status": "done", "doc_id": "doc-a", "doc_link": "https://docs.google.com/document/d/doc-a/edit", "source_meta": {}, "updated_at": "old"}
    HELPERS["refresh_manifest_v2_summary"](v2)

    rebuilt, counters = build_manifest_v2_from_existing_manifest_and_docs(
        v2,
        [{"id": "doc-a", "name": "Doc A", "mimeType": DOC_MIME}],
        {"doc-a": build_transcript_standard_check(build_current_standard_document("Doc A"), checked_at)},
        "folder-root",
        "",
        False,
        checked_at,
    )

    assert counters == {"source_entries_migrated": 0, "doc_registry_entries_migrated": 0}
    assert list(rebuilt["documents"]) == ["doc-a"]
    assert list(rebuilt["sources"]) == ["source-a"]
    assert rebuilt["documents"]["doc-a"]["standard_check"]["status"] == "current"
    assert rebuilt["sources"]["source-a"]["doc_id"] == "doc-a"


def test_manifest_v2_compatibility_helpers_update_sources_and_skip_logic() -> None:
    now = datetime.now(timezone.utc).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
    manifest = make_manifest_v2_default(updated_at=now)
    manifest["sources"].update({
        "done": {"source_signature": "done", "status": "done", "settings_signature": "settings-a"},
        "imported": {"source_signature": "imported", "status": "imported_done"},
        "fresh": {"source_signature": "fresh", "status": "in_progress", "started_at": now},
        "stale": {"source_signature": "stale", "status": "in_progress", "started_at": old},
    })
    manifest["documents"]["doc-1"] = {
        "doc_id": "doc-1",
        "doc_name": "Doc",
        "doc_link": "https://docs.google.com/document/d/doc-1/edit",
        "doc_path": "Doc",
        "doc_mime_type": DOC_MIME,
        "document_type": "google_doc_transcript",
        "registration_status": "registered",
        "source_signatures": [],
        "standard_check": build_transcript_standard_check("plain", now),
        "updated_at": now,
        "source_meta": {},
    }
    saved = []
    HELPERS["save_manifest"] = lambda incoming: saved.append(json.loads(json.dumps(incoming)))

    assert get_manifest_entry(manifest, "done")["status"] == "done"
    assert should_skip_by_manifest({"version": 1, "entries": {"v1": {"status": "done", "settings_signature": "x"}}}, "v1", "x")[0] is True
    assert should_skip_by_manifest(manifest, "done", "settings-a")[0] is True
    assert should_skip_by_manifest(manifest, "done", "settings-b")[0] is False
    assert should_skip_by_manifest(manifest, "imported", "settings-b")[0] is True
    assert should_skip_by_manifest(manifest, "fresh", "settings-b")[0] is True
    assert should_skip_by_manifest(manifest, "stale", "settings-b")[0] is False

    mark_manifest_in_progress(manifest, "new", "settings", "New Source")
    mark_manifest_done(manifest, "new", "settings", "New Source", "Doc", "https://docs.google.com/document/d/doc-1/edit")
    mark_manifest_failed(manifest, "failed", "settings", "Failed Source", "boom")

    assert manifest["sources"]["new"]["status"] == "done"
    assert manifest["sources"]["new"]["doc_id"] == "doc-1"
    assert "new" in manifest["documents"]["doc-1"]["source_signatures"]
    assert manifest["sources"]["failed"]["status"] == "failed"
    assert saved


def test_mark_manifest_done_v2_upserts_document_and_summary_immediately() -> None:
    manifest = make_manifest_v2_default(updated_at="2026-06-01T00:00:00+00:00")
    saved = []
    HELPERS["save_manifest"] = lambda incoming: saved.append(json.loads(json.dumps(incoming)))

    mark_manifest_done(
        manifest,
        "source-new",
        "settings",
        "Audio.mp3",
        "Transcript Doc",
        "https://docs.google.com/document/d/doc-new/edit",
        {"type": "drive", "output_folder_id": "folder-root", "output_folder_path": "MyDrive/Calls"},
    )

    source = manifest["sources"]["source-new"]
    document = manifest["documents"]["doc-new"]
    assert source["status"] == "done"
    assert source["doc_id"] == "doc-new"
    assert document["doc_id"] == "doc-new"
    assert document["doc_name"] == "Transcript Doc"
    assert document["doc_link"] == "https://docs.google.com/document/d/doc-new/edit"
    assert "source-new" in document["source_signatures"]
    assert document["standard_check"]["status"] == "current"
    assert document["source_meta"]["folder_id"] == "folder-root"
    assert document["source_meta"]["folder_path"] == "MyDrive/Calls"
    assert document["source_meta"]["registration_mode"] == "transcription_completion"
    assert manifest["summary"]["documents_total"] == 1
    assert manifest["summary"]["sources_total"] == 1
    assert manifest["summary"]["documents_with_sources"] == 1
    assert manifest["summary"]["orphan_sources"] == 0
    assert saved


def test_mark_manifest_done_v2_preserves_existing_document_source_signatures() -> None:
    manifest = make_manifest_v2_default(updated_at="2026-06-01T00:00:00+00:00")
    manifest["documents"]["doc-keep"] = make_registered_v2_document(doc_id="doc-keep", doc_name="Doc Keep")
    manifest["documents"]["doc-keep"]["source_signatures"] = ["source-existing"]
    HELPERS["refresh_manifest_v2_summary"](manifest)
    HELPERS["save_manifest"] = lambda incoming: None

    mark_manifest_done(manifest, "source-new", "settings", "Audio", "Doc Keep", "https://docs.google.com/document/d/doc-keep/edit")

    assert manifest["documents"]["doc-keep"]["source_signatures"] == ["source-existing", "source-new"]


def test_mark_manifest_done_v1_does_not_create_documents_catalog() -> None:
    manifest = {"version": 1, "entries": {}}
    saved = []
    HELPERS["save_manifest"] = lambda incoming: saved.append(json.loads(json.dumps(incoming)))

    mark_manifest_done(manifest, "source-v1", "settings", "Audio", "Doc", "https://docs.google.com/document/d/doc-v1/edit")

    assert manifest["entries"]["source-v1"]["status"] == "done"
    assert "documents" not in manifest
    assert saved


def test_mark_manifest_done_without_confirmed_google_doc_does_not_persist_source() -> None:
    manifest = make_manifest_v2_default(updated_at="2026-06-01T00:00:00+00:00")
    saved = []
    HELPERS["save_manifest"] = lambda incoming: saved.append(incoming)

    with pytest.raises(ValueError, match="подтверждённого Google Docs результата"):
        mark_manifest_done(manifest, "source-no-doc", "settings", "Audio", "", "")

    assert "source-no-doc" not in manifest["sources"]
    assert manifest["documents"] == {}
    assert manifest["summary"]["sources_total"] == 0
    assert manifest["summary"]["orphan_sources"] == 0
    assert saved == []


def make_non_empty_manifest_for_clear() -> dict:
    manifest = make_manifest_v2_default(updated_at="2026-06-01T00:00:00+00:00")
    HELPERS["save_manifest"] = lambda _incoming: None
    mark_manifest_done(
        manifest,
        "source-a",
        "settings",
        "Audio",
        "Transcript",
        "https://docs.google.com/document/d/doc-clear/edit",
    )
    return manifest


def test_manifest_clear_dry_run_is_read_only_and_reports_catalog(monkeypatch) -> None:
    current = make_non_empty_manifest_for_clear()
    globals_dict = clear_manifest_catalog.__globals__
    calls = []
    monkeypatch.setitem(globals_dict, "load_manifest_read_only", lambda force_reload=False: calls.append(("read", force_reload)) or current)
    monkeypatch.setitem(globals_dict, "load_manifest", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("mutable load")))
    monkeypatch.setitem(globals_dict, "create_manifest_backup", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("backup")))
    monkeypatch.setitem(globals_dict, "write_active_manifest_v2", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("write")))

    report = clear_manifest_catalog(dry_run=True)

    assert calls == [("read", True)]
    assert report["records_total"] == 2
    assert report["would_create_backup"] is True
    assert report["would_clear_manifest"] is True
    assert report["backup_created"] is False
    assert report["manifest_cleared"] is False
    assert report["source_files_deleted"] is False
    assert report["google_docs_deleted"] is False


def test_manifest_clear_apply_requires_exact_confirmation_before_read(monkeypatch) -> None:
    globals_dict = clear_manifest_catalog.__globals__
    monkeypatch.setitem(globals_dict, "load_manifest_read_only", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("read")))

    with pytest.raises(ValueError, match="ОЧИСТИТЬ MANIFEST"):
        clear_manifest_catalog(dry_run=False, confirmation_text="очистить")


def test_manifest_clear_apply_backs_up_then_writes_empty_v2(monkeypatch) -> None:
    current = make_non_empty_manifest_for_clear()
    globals_dict = clear_manifest_catalog.__globals__
    calls = []
    monkeypatch.setitem(globals_dict, "load_manifest_read_only", lambda force_reload=False: calls.append(("read_only", force_reload)) or current)
    monkeypatch.setitem(globals_dict, "load_manifest", lambda force_reload=False: calls.append(("read_current", force_reload)) or current)
    monkeypatch.setitem(
        globals_dict,
        "create_manifest_backup",
        lambda manifest, timestamp: calls.append(("backup", manifest is current, timestamp)) or {"name": f"backup.{timestamp}.json"},
    )
    monkeypatch.setitem(
        globals_dict,
        "write_active_manifest_v2",
        lambda manifest: calls.append(("write", manifest)),
    )

    report = clear_manifest_catalog(
        dry_run=False,
        confirmation_text=HELPERS["MANIFEST_CLEAR_CONFIRMATION"],
    )

    assert [call[0] for call in calls] == ["read_only", "read_current", "backup", "write"]
    written = calls[-1][1]
    assert written["version"] == HELPERS["MANIFEST_V2_TARGET_VERSION"]
    assert written["documents"] == {}
    assert written["sources"] == {}
    assert report["backup_created"] is True
    assert report["manifest_cleared"] is True
    assert report["manifest_after"]["documents_total"] == 0
    assert report["manifest_after"]["sources_total"] == 0
    assert "doc-clear" not in build_manifest_clear_report_text(report)


def test_manifest_clear_never_writes_when_backup_fails(monkeypatch) -> None:
    current = make_non_empty_manifest_for_clear()
    globals_dict = clear_manifest_catalog.__globals__
    writes = []
    monkeypatch.setitem(globals_dict, "load_manifest_read_only", lambda force_reload=False: current)
    monkeypatch.setitem(globals_dict, "load_manifest", lambda force_reload=False: current)
    monkeypatch.setitem(globals_dict, "create_manifest_backup", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("backup failed")))
    monkeypatch.setitem(globals_dict, "write_active_manifest_v2", lambda manifest: writes.append(manifest))

    with pytest.raises(RuntimeError, match="backup failed"):
        clear_manifest_catalog(
            dry_run=False,
            confirmation_text=HELPERS["MANIFEST_CLEAR_CONFIRMATION"],
        )

    assert writes == []


def test_manifest_maintenance_does_not_count_transcription_created_document_as_add() -> None:
    manifest = make_manifest_v2_default(updated_at="2026-06-01T00:00:00+00:00")
    HELPERS["save_manifest"] = lambda incoming: None
    mark_manifest_done(
        manifest,
        "source-a",
        "settings",
        "Audio",
        "Doc A",
        "https://docs.google.com/document/d/doc-a/edit",
        {"type": "drive", "output_folder_id": "folder-root", "output_folder_path": ""},
    )
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-a", "name": "Doc A", "mimeType": DOC_MIME, "webViewLink": "https://docs.google.com/document/d/doc-a/edit"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document(title="Doc A")
    HELPERS["load_manifest_read_only"] = lambda: manifest

    report = standardize_manifest_to_v2_for_existing_google_docs("folder-root", dry_run=True)

    assert report["selected_would_add_documents"] == 0


def test_completed_source_document_entry_does_not_store_transcript_text() -> None:
    manifest = make_manifest_v2_default(updated_at="2026-06-01T00:00:00+00:00")
    HELPERS["save_manifest"] = lambda incoming: None

    mark_manifest_done(
        manifest,
        "source-text",
        "settings",
        "Audio",
        "Doc",
        "https://docs.google.com/document/d/doc-text/edit",
        {"type": "drive", "transcript_text": "SHOULD_NOT_STORE", "document_text": "SHOULD_NOT_STORE"},
    )

    document_json = json.dumps(manifest["documents"]["doc-text"], ensure_ascii=False)
    assert "SHOULD_NOT_STORE" not in document_json
    assert "transcript_text" not in document_json
    assert "document_text" not in document_json


def test_save_manifest_v2_merge_does_not_reintroduce_entries() -> None:
    calls = []
    latest = make_manifest_v2_default(updated_at="old")
    latest["documents"]["doc-old"] = {"doc_id": "doc-old", "standard_check": build_transcript_standard_check("plain", "old"), "source_signatures": []}
    incoming = make_manifest_v2_default(updated_at="new")
    incoming["sources"]["source-new"] = {"source_signature": "source-new", "status": "done", "doc_id": ""}

    HELPERS["get_or_create_manifest_file"] = lambda: ("manifest-folder", "manifest-file")
    HELPERS["load_manifest"] = lambda force_reload=False: latest
    class DummyMedia:
        def __init__(self, *args, **kwargs):
            pass
    class DummyUpdate:
        def update(self, **kwargs):
            calls.append(("update", kwargs))
            return object()
    class DummyDrive:
        def files(self):
            return DummyUpdate()
    HELPERS["MediaInMemoryUpload"] = DummyMedia
    HELPERS["drive_service"] = DummyDrive()
    HELPERS["execute_google_request_with_retry"] = lambda request, operation_label: calls.append(("execute", operation_label))

    save_manifest(incoming)

    merged = HELPERS["MANIFEST_CACHE"]["data"]
    assert merged["version"] == 2
    assert "entries" not in merged
    assert "doc-old" in merged["documents"]
    assert "source-new" in merged["sources"]
    assert ("execute", "drive_file_update") in calls


def test_manifest_v2_migration_flow_dry_run_is_read_only_and_apply_backs_up_and_writes() -> None:
    calls = []
    manifest_v1 = {
        "version": 1,
        "entries": {
            "source-a": {"source_signature": "source-a", "source_type": "drive", "status": "done", "doc_link": "https://docs.google.com/document/d/doc-a/edit"},
            "orphan": {"source_signature": "orphan", "source_type": "drive", "status": "done"},
        },
    }
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-a", "name": "Doc A", "mimeType": DOC_MIME, "webViewLink": "https://docs.google.com/document/d/doc-a/edit"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document("Doc A")
    HELPERS["load_manifest_read_only"] = lambda: calls.append(("load_read_only",)) or manifest_v1
    HELPERS["load_manifest"] = lambda: calls.append(("load",)) or manifest_v1
    HELPERS["save_manifest"] = lambda manifest: calls.append(("save",))
    HELPERS["get_or_create_manifest_file"] = lambda: calls.append(("get_or_create",)) or ("folder", "file")
    HELPERS["create_manifest_backup"] = lambda manifest, timestamp: calls.append(("backup", json.loads(json.dumps(manifest)))) or {"file_id": "backup"}
    HELPERS["write_active_manifest_v2"] = lambda manifest: calls.append(("write_v2", json.loads(json.dumps(manifest))))

    dry = standardize_manifest_to_v2_for_existing_google_docs("folder-root", dry_run=True)

    assert dry["dry_run"] is True
    assert dry["current_manifest_version"] == 1
    assert dry["target_manifest_version"] == 2
    assert dry["would_backup_manifest"] is True
    assert dry["would_write_manifest_v2"] is True
    assert dry["manifest_v2_written"] is False
    assert "Старый формат manifest будет обновлён до актуального." in dry["notice"]
    assert dry["google_docs_scanned"] == 1
    assert dry["documents_total"] == 1
    assert dry["sources_total"] == 2
    assert dry["orphan_sources"] == 1
    assert ("load_read_only",) in calls
    assert not any(call[0] in {"save", "get_or_create", "backup", "write_v2"} for call in calls)

    calls.clear()
    applied = standardize_manifest_to_v2_for_existing_google_docs("folder-root", dry_run=False)

    assert applied["backup_created"] is True
    assert applied["manifest_v2_written"] is True
    assert calls[0][0] == "load"
    assert calls[1][0] == "backup"
    assert calls[2][0] == "write_v2"
    written = calls[2][1]
    assert written["version"] == 2
    assert written["schema"] == "voiceops_manifest_v2"
    assert written["sources"]["source-a"]["doc_id"] == "doc-a"
    assert written["sources"]["orphan"]["doc_id"] == ""

    calls.clear()
    HELPERS["load_manifest_read_only"] = lambda: calls.append(("load_read_only",)) or written
    second = standardize_manifest_to_v2_for_existing_google_docs("folder-root", dry_run=True)
    assert second["current_manifest_version"] == 2
    assert second["target_manifest_version"] == 2
    assert second["source_entries_migrated"] == 0
    assert second["doc_registry_entries_migrated"] == 0
    assert second["documents_total"] == 1
    assert second["sources_total"] == 2
    assert second["would_backup_manifest"] is False
    assert second["would_refresh_manifest_v2"] is False
    assert second["would_write_manifest_v2"] is False
    assert second["manifest_v2_up_to_date"] is True
    assert "Manifest уже в актуальном формате" in second["notice"]
    assert "entries" not in second["manifest_v2_preview"]



def test_manifest_v2_dry_run_checked_at_only_change_is_up_to_date() -> None:
    manifest = make_manifest_v2_default(updated_at="2026-05-01T00:00:00+00:00")
    manifest["documents"]["doc-v2"] = make_registered_v2_document(checked_at="2026-05-01T00:00:00+00:00")
    HELPERS["refresh_manifest_v2_summary"](manifest)
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-v2", "name": "Doc V2", "mimeType": DOC_MIME, "webViewLink": "https://docs.google.com/document/d/doc-v2/edit"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document(title="Doc V2")
    HELPERS["load_manifest_read_only"] = lambda: manifest

    report = standardize_manifest_to_v2_for_existing_google_docs("folder-root", dry_run=True)

    assert report["current_manifest_version"] == 2
    assert report["target_manifest_version"] == 2
    assert report["would_backup_manifest"] is False
    assert report["backup_created"] is False
    assert report["would_refresh_manifest_v2"] is False
    assert report["would_write_manifest_v2"] is False
    assert report["manifest_v2_written"] is False
    assert report["manifest_v2_up_to_date"] is True
    assert "мигр" not in report["notice"].lower()
    assert "entries" not in report["manifest_v2_preview"]


def test_manifest_v2_apply_refreshes_material_changes_without_mixed_entries_or_backup() -> None:
    calls = []
    manifest = make_manifest_v2_default(updated_at="2026-05-01T00:00:00+00:00")
    manifest["documents"]["doc-v2"] = make_registered_v2_document(doc_name="Old Name", doc_path="Old Name")
    manifest["entries"] = {"legacy": {"status": "done"}}
    HELPERS["refresh_manifest_v2_summary"](manifest)
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-v2", "name": "Doc V2", "mimeType": DOC_MIME, "webViewLink": "https://docs.google.com/document/d/doc-v2/edit"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document(title="Doc V2")
    HELPERS["load_manifest"] = lambda: calls.append(("load",)) or manifest
    HELPERS["create_manifest_backup"] = lambda manifest, timestamp: (_ for _ in ()).throw(AssertionError("backup should not be created for v2 refresh"))
    HELPERS["write_active_manifest_v2"] = lambda incoming: calls.append(("write_v2", json.loads(json.dumps(incoming))))
    HELPERS["write_title_and_text_to_doc"] = lambda **kwargs: (_ for _ in ()).throw(AssertionError("Google Docs mutation called"))
    HELPERS["create_google_doc"] = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("create_google_doc called"))
    HELPERS["transcribe_fileobj"] = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("provider called"))

    report = standardize_manifest_to_v2_for_existing_google_docs("folder-root", dry_run=False)

    assert report["current_manifest_version"] == 2
    assert report["backup_created"] is False
    assert report["manifest_v2_written"] is True
    written = calls[-1][1]
    assert written["documents"]["doc-v2"]["doc_name"] == "Doc V2"
    assert written["documents"]["doc-v2"]["standard_check"]["status"] == "current"
    assert "entries" not in written


def test_manifest_ui_exposes_single_unified_manifest_action() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")

    assert "Проверить / зарегистрировать существующие Google Docs в manifest" not in source
    assert "Регистрация существующих Google Docs в manifest" not in source
    assert source.count("Проверить / обновить manifest") == 1
    assert source.count("Только проверить manifest, не изменять") == 1
    assert "Manifest" in source
    assert "standardize_manifest_to_v2_for_existing_google_docs" in source
    assert "register_existing_docs_manifest_button.on_click" not in source


def test_unified_manifest_handler_uses_v2_standardization_flow() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")
    handler_match = re.search(r"def on_standardize_manifest_v2_clicked\(_\):(?P<body>.*?)(?:\ndef |\nclass |\Z)", source, re.S)
    assert handler_match is not None
    body = handler_match.group("body")

    assert "standardize_manifest_to_v2_for_existing_google_docs" in body
    assert "register_existing_google_docs_in_manifest" not in body
    assert "standardize_manifest_v2_dry_run_widget.value" in body

def test_manifest_v2_migration_flow_does_not_call_docs_or_provider_mutators() -> None:
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-a", "name": "Doc A", "mimeType": DOC_MIME},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: "plain"
    HELPERS["load_manifest_read_only"] = lambda: {"version": 1, "entries": {}}
    HELPERS["write_title_and_text_to_doc"] = lambda **kwargs: (_ for _ in ()).throw(AssertionError("write_title_and_text_to_doc called"))
    HELPERS["create_google_doc"] = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("create_google_doc called"))
    HELPERS["transcribe_fileobj"] = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("provider called"))
    HELPERS["save_manifest"] = lambda manifest: (_ for _ in ()).throw(AssertionError("save_manifest called"))
    HELPERS["create_manifest_backup"] = lambda manifest, timestamp: (_ for _ in ()).throw(AssertionError("backup called"))

    report = standardize_manifest_to_v2_for_existing_google_docs("folder-root", dry_run=True)

    assert report["standard_check"]["unstructured"] == 1
    assert report["manifest_v2_written"] is False


def make_registered_v2_document(
    doc_id: str = "doc-v2",
    doc_name: str = "Doc V2",
    doc_path: str = "Doc V2",
    status: str = "current",
    checked_at: str = "2026-05-01T00:00:00+00:00",
) -> dict:
    detected = "transcript_doc" if status == "current" else ("legacy_v1" if status == "outdated" else "unknown")
    return {
        "doc_id": doc_id,
        "doc_name": doc_name,
        "doc_link": f"https://docs.google.com/document/d/{doc_id}/edit",
        "doc_path": doc_path,
        "doc_mime_type": DOC_MIME,
        "document_type": "google_doc_transcript",
        "registration_status": "registered",
        "source_signatures": [],
        "standard_check": {
            "target_standard": "transcript_doc",
            "detected_standard": detected,
            "status": status,
            "checked_at": checked_at,
            "checker_version": "transcript_standard_checker_v1",
        },
        "updated_at": checked_at,
        "source_meta": {
            "folder_id": "folder-root",
            "folder_path": "",
            "recursive_scan": False,
            "registration_mode": "manifest_v2_migration",
        },
    }


def test_manifest_registration_v2_document_already_registered_ignores_checked_at_only_change() -> None:
    manifest = make_manifest_v2_default(updated_at="2026-05-01T00:00:00+00:00")
    manifest["documents"]["doc-v2"] = make_registered_v2_document(checked_at="2026-05-01T00:00:00+00:00")
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-v2", "name": "Doc V2", "mimeType": DOC_MIME, "webViewLink": "https://docs.google.com/document/d/doc-v2/edit"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document(title="Doc V2")
    HELPERS["load_manifest_read_only"] = lambda: manifest

    report = register_existing_google_docs_in_manifest("folder-root", dry_run=True)

    assert [item["doc_id"] for item in report["already_registered"]] == ["doc-v2"]
    assert report["would_update"] == []
    assert "entries" not in manifest


def test_manifest_registration_v2_document_changed_doc_name_or_path_reports_would_update() -> None:
    manifest = make_manifest_v2_default(updated_at="2026-05-01T00:00:00+00:00")
    manifest["documents"]["doc-v2"] = make_registered_v2_document(doc_name="Old Name", doc_path="Old Name")
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-v2", "name": "Doc V2", "mimeType": DOC_MIME, "webViewLink": "https://docs.google.com/document/d/doc-v2/edit"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document(title="Doc V2")
    HELPERS["load_manifest_read_only"] = lambda: manifest

    report = register_existing_google_docs_in_manifest("folder-root", dry_run=True)

    assert [item["doc_id"] for item in report["would_update"]] == ["doc-v2"]
    assert report["already_registered"] == []


def test_manifest_registration_v2_document_changed_standard_status_reports_would_update() -> None:
    manifest = make_manifest_v2_default(updated_at="2026-05-01T00:00:00+00:00")
    manifest["documents"]["doc-v2"] = make_registered_v2_document(status="unstructured")
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-v2", "name": "Doc V2", "mimeType": DOC_MIME, "webViewLink": "https://docs.google.com/document/d/doc-v2/edit"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document(title="Doc V2")
    HELPERS["load_manifest_read_only"] = lambda: manifest

    report = register_existing_google_docs_in_manifest("folder-root", dry_run=True)

    assert [item["doc_id"] for item in report["would_update"]] == ["doc-v2"]
    assert report["already_registered"] == []


def test_manifest_registration_v2_apply_updates_documents_without_recreating_entries() -> None:
    calls = []
    manifest = make_manifest_v2_default(updated_at="2026-05-01T00:00:00+00:00")
    manifest["documents"]["doc-v2"] = make_registered_v2_document(doc_name="Old Name", doc_path="Old Name")
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-v2", "name": "Doc V2", "mimeType": DOC_MIME, "webViewLink": "https://docs.google.com/document/d/doc-v2/edit"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document(title="Doc V2")
    HELPERS["load_manifest"] = lambda: manifest
    HELPERS["save_manifest"] = lambda incoming: calls.append(json.loads(json.dumps(incoming)))

    report = register_existing_google_docs_in_manifest("folder-root", dry_run=False)

    assert [item["doc_id"] for item in report["updated"]] == ["doc-v2"]
    assert manifest["documents"]["doc-v2"]["doc_name"] == "Doc V2"
    assert manifest["documents"]["doc-v2"]["standard_check"]["status"] == "current"
    assert "entries" not in manifest
    assert calls and "entries" not in calls[0]


def test_manifest_registration_v2_document_already_registered_same_identity_and_status() -> None:
    manifest = make_manifest_v2_default(updated_at="2026-06-01T00:00:00+00:00")
    manifest["documents"]["doc-v2"] = make_registered_v2_document(checked_at="2026-06-01T00:00:00+00:00")
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-v2", "name": "Doc V2", "mimeType": DOC_MIME, "webViewLink": "https://docs.google.com/document/d/doc-v2/edit"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document(title="Doc V2")
    HELPERS["load_manifest_read_only"] = lambda: manifest

    report = register_existing_google_docs_in_manifest("folder-root", dry_run=True)

    assert [item["doc_id"] for item in report["already_registered"]] == ["doc-v2"]
    assert report["would_update"] == []


def test_manifest_report_separates_selected_scan_from_global_totals() -> None:
    manifest = make_manifest_v2_default(updated_at="2026-05-01T00:00:00+00:00")
    for index in range(81):
        doc_id = f"existing-{index}"
        manifest["documents"][doc_id] = make_registered_v2_document(
            doc_id=doc_id,
            doc_name=f"Existing {index}",
            status="unstructured",
        )
    HELPERS["refresh_manifest_v2_summary"](manifest)
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": f"selected-{index}", "name": f"Selected {index}", "mimeType": DOC_MIME, "webViewLink": f"https://docs.google.com/document/d/selected-{index}/edit"}
        for index in range(5)
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document(title=document_id)
    HELPERS["load_manifest_read_only"] = lambda: manifest

    report = standardize_manifest_to_v2_for_existing_google_docs("folder-root", dry_run=True)
    text = build_standardize_manifest_v2_report_text(report)

    assert report["selected_google_docs_scanned"] == 5
    assert report["manifest_before"]["documents_total"] == 81
    assert report["manifest_after"]["documents_total"] == 86
    assert report["selected_would_add_documents"] == 5
    assert "МАНИФЕСТ — ВЫБРАННАЯ ПАПКА" in text
    assert "ГЛОБАЛЬНЫЙ MANIFEST — СПРАВОЧНО" in text
    assert "Проверка стандарта по глобальному каталогу" in text
    assert "Манифест после применения" not in text
    assert "entire Drive" not in text
    assert "Google Docs в выбранной папке: 5" in text
    assert "Будет добавлено документов: 5" in text
    assert "Документов всего: 86" in text


def test_manifest_report_text_is_localized_to_russian() -> None:
    report = {
        "dry_run": False,
        "current_manifest_version": 2,
        "target_manifest_version": 2,
        "selected_google_docs_scanned": 1,
        "selected_folders_seen": 0,
        "selected_skipped_non_google_docs": 0,
        "manifest_before": {"version": 2},
        "manifest_after": {"version": 2},
        "standard_check": {"target_standard": "transcript_doc", "current": 1, "outdated": 0, "unstructured": 0, "unreadable": 0},
        "manifest_v2_up_to_date": True,
        "errors": [],
    }

    text = build_standardize_manifest_v2_report_text(report)

    for expected in (
        "МАНИФЕСТ — ВЫБРАННАЯ ПАПКА",
        "ГЛОБАЛЬНЫЙ MANIFEST — СПРАВОЧНО",
        "БЕЗОПАСНОСТЬ",
        "Скан выбранной папки",
        "Изменения по выбранной папке",
        "Проверка стандарта по глобальному каталогу",
    ):
        assert expected in text
    for old_label in (
        "Selected folder scan",
        "Manifest before",
        "Changes from selected folder",
        "Safety",
        "Манифест до изменений",
        "Манифест после применения",
        "Проверка стандарта после применения",
    ):
        assert old_label not in text


def test_docs_standardization_report_text_is_localized_to_russian() -> None:
    report = {
        "dry_run": True,
        "google_docs_scanned": 1,
        "folders_seen": 0,
        "skipped_non_google_docs": 0,
        "current_standard": 1,
        "outdated_standard": 0,
        "unstructured": 0,
        "unreadable": 0,
        "already_structured": [{"doc_name": "Doc", "structured_status": "current", "link": "https://docs.google.com/document/d/doc/edit"}],
        "would_standardize": [],
        "errors": [],
    }

    text = build_standardize_existing_docs_report_text(report)

    for expected in ("СТАНДАРТИЗАЦИЯ GOOGLE DOCS", "Скан выбранной папки", "Текущий статус стандарта", "Влияние apply", "Безопасность"):
        assert expected in text
    for old_label in ("Current standard status", "Apply impact", "First 20 documents"):
        assert old_label not in text


def test_manifest_report_v2_no_material_changes_says_up_to_date() -> None:
    manifest = make_manifest_v2_default(updated_at="2026-05-01T00:00:00+00:00")
    manifest["documents"]["doc-v2"] = make_registered_v2_document(checked_at="2026-05-01T00:00:00+00:00")
    HELPERS["refresh_manifest_v2_summary"](manifest)
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-v2", "name": "Doc V2", "mimeType": DOC_MIME, "webViewLink": "https://docs.google.com/document/d/doc-v2/edit"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document(title="Doc V2")
    HELPERS["load_manifest_read_only"] = lambda: manifest

    report = standardize_manifest_to_v2_for_existing_google_docs("folder-root", dry_run=True)
    text = build_standardize_manifest_v2_report_text(report)

    assert report["manifest_v2_up_to_date"] is True
    assert report["would_write_manifest_v2"] is False
    assert "выбранная папка уже актуальна" in text
    assert "Требуется запись: нет" in text
    assert "Manifest актуален: да" in text
    assert "Manifest уже актуален, запись не требуется" in text
    for forbidden in ("manifest v2", "Manifest v2", "v2 catalog", "будет мигрирован в v2", "уже v2"):
        assert forbidden not in text
    assert "would migrate" not in text.lower()


def test_manifest_report_v2_selected_adds_records_in_global_manifest() -> None:
    manifest = make_manifest_v2_default(updated_at="2026-05-01T00:00:00+00:00")
    HELPERS["refresh_manifest_v2_summary"](manifest)
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "new-doc", "name": "New Doc", "mimeType": DOC_MIME, "webViewLink": "https://docs.google.com/document/d/new-doc/edit"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_current_standard_document(title="New Doc")
    HELPERS["load_manifest_read_only"] = lambda: manifest

    report = standardize_manifest_to_v2_for_existing_google_docs("folder-root", dry_run=True)
    text = build_standardize_manifest_v2_report_text(report)

    assert report["would_refresh_manifest_v2"] is True
    assert report["would_write_manifest_v2"] is True
    assert report["would_backup_manifest"] is False
    assert "есть изменения" in text
    assert "Требуется запись: да" in text
    assert "Документов всего:" in text
    assert "Содержимое Google Docs изменено: нет" in text
    assert "STT/LLM/provider API вызваны: нет" in text


def test_manifest_report_v1_migration_mentions_backup_and_apply_creates_backup() -> None:
    backups = []
    writes = []
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "doc-a", "name": "Doc A", "mimeType": DOC_MIME, "webViewLink": "https://docs.google.com/document/d/doc-a/edit"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: "plain"
    HELPERS["load_manifest_read_only"] = lambda: {"version": 1, "entries": {}}

    dry = standardize_manifest_to_v2_for_existing_google_docs("folder-root", dry_run=True)
    dry_text = build_standardize_manifest_v2_report_text(dry)

    assert "Старый формат manifest будет обновлён до актуального" in dry_text
    assert "manifest v2" not in dry_text
    assert "уже v2" not in dry_text
    assert dry["would_backup_manifest"] is True

    HELPERS["load_manifest"] = lambda: {"version": 1, "entries": {}}
    HELPERS["create_manifest_backup"] = lambda manifest, timestamp: backups.append((manifest, timestamp)) or {"name": "backup.json"}
    HELPERS["write_active_manifest_v2"] = lambda manifest: writes.append(manifest)

    applied = standardize_manifest_to_v2_for_existing_google_docs("folder-root", dry_run=False)

    assert applied["backup_created"] is True
    assert backups
    assert writes and writes[0]["version"] == 2


def test_docs_standardization_report_groups_dry_run_sections_and_safety() -> None:
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "old", "name": "Old", "mimeType": DOC_MIME, "webViewLink": "https://docs.google.com/document/d/old/edit"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: build_legacy_standard_document(title="Old")
    HELPERS["write_title_and_text_to_doc"] = lambda **kwargs: (_ for _ in ()).throw(AssertionError("dry-run wrote a doc"))

    report = standardize_existing_google_docs_in_folder("folder-root", dry_run=True)
    text = build_standardize_existing_docs_report_text(report)

    assert "Скан выбранной папки" in text
    assert "Текущий статус стандарта" in text
    assert "Влияние apply" in text
    assert "Dry-run: документы не изменяются" in text
    assert "Будет вызвано STT/LLM/provider API: 0" in text
    assert "Будет создано новых Google Docs: 0" in text
    assert "Будет изменён manifest: 0" in text


def test_docs_standardization_apply_report_states_in_place_no_external_mutation() -> None:
    writes = []
    HELPERS["list_drive_folder_children"] = lambda folder_id: [
        {"id": "plain", "name": "Plain", "mimeType": DOC_MIME, "webViewLink": "https://docs.google.com/document/d/plain/edit"},
    ]
    HELPERS["extract_google_doc_plain_text"] = lambda document_id: "Plain\n\nBody"
    HELPERS["write_title_and_text_to_doc"] = lambda **kwargs: writes.append(kwargs)

    report = standardize_existing_google_docs_in_folder("folder-root", dry_run=False)
    text = build_standardize_existing_docs_report_text(report)

    assert writes and writes[0]["document_id"] == "plain"
    assert "Apply: переписывает только выбранные Google Docs на месте" in text
    assert "Будет создано новых Google Docs: 0" in text
    assert "Будет вызвано STT/LLM/provider API: 0" in text
    assert "Будет изменён manifest: 0" in text


def test_docs_standardization_report_first_20_includes_status_labels() -> None:
    docs = [
        {"id": "current", "name": "Current", "mimeType": DOC_MIME, "webViewLink": "https://docs.google.com/document/d/current/edit"},
        {"id": "outdated", "name": "Outdated", "mimeType": DOC_MIME, "webViewLink": "https://docs.google.com/document/d/outdated/edit"},
        {"id": "unstructured", "name": "Unstructured", "mimeType": DOC_MIME, "webViewLink": "https://docs.google.com/document/d/unstructured/edit"},
        {"id": "unreadable", "name": "Unreadable", "mimeType": DOC_MIME, "webViewLink": "https://docs.google.com/document/d/unreadable/edit"},
    ]
    HELPERS["list_drive_folder_children"] = lambda folder_id: docs

    def extract(document_id: str) -> str:
        if document_id == "current":
            return build_current_standard_document(title="Current")
        if document_id == "outdated":
            return build_legacy_standard_document(title="Outdated")
        if document_id == "unreadable":
            raise RuntimeError("cannot read")
        return "Unstructured\n\nBody"

    HELPERS["extract_google_doc_plain_text"] = extract
    report = standardize_existing_google_docs_in_folder("folder-root", dry_run=True)
    text = build_standardize_existing_docs_report_text(report)

    assert "[current]" in text
    assert "[outdated]" in text
    assert "[unstructured]" in text
    assert "[unreadable/error]" in text


def test_ui_help_text_distinguishes_manifest_and_docs_standardization() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")

    assert source.count("Проверить / обновить manifest") == 1
    assert source.count("Проверить / стандартизировать существующие Google Docs") == 1
    assert "Manifest — глобальный каталог. Если выбрать другую папку" in source
    assert "Старые записи из других папок не удаляются" in source
    assert "Стандартизация Google Docs в apply-режиме переписывает выбранные документы на месте" in source
    assert "Сначала запускайте dry-run на маленькой подпапке" in source
    assert "Manifest — глобальный каталог" in source
    assert "переписывает выбранные документы на месте" in source


def test_speaker_project_create_rename_archive_and_normalize_omits_text() -> None:
    roster = create_speaker_project({}, "  Интервью  ", project_id="project-a", updated_at="2026-06-01T00:00:00+00:00")
    assert roster["projects"]["project-a"]["name"] == "Интервью"
    assert roster["projects"]["project-a"]["archived"] is False

    roster = rename_speaker_project(roster, "project-a", "Интервью 2", updated_at="2026-06-01T00:01:00+00:00")
    assert roster["projects"]["project-a"]["name"] == "Интервью 2"

    roster = archive_speaker_project(roster, "project-a", True, updated_at="2026-06-01T00:02:00+00:00")
    assert roster["projects"]["project-a"]["archived"] is True

    noisy = {"version": 1, "projects": {"project-a": {**roster["projects"]["project-a"], "transcript_text": "do not keep"}}}
    normalized = normalize_speaker_project_data(noisy)
    assert "transcript_text" not in normalized["projects"]["project-a"]


def test_project_speaker_add_rename_deactivate() -> None:
    roster = create_speaker_project({}, "Project", project_id="project-a")
    roster = add_project_speaker(roster, "project-a", " Андрей ", speaker_id="speaker-a")
    assert roster["projects"]["project-a"]["speakers"]["speaker-a"]["display_name"] == "Андрей"
    assert roster["projects"]["project-a"]["speakers"]["speaker-a"]["active"] is True

    roster = rename_project_speaker(roster, "project-a", "speaker-a", "Андрей Иванов")
    assert roster["projects"]["project-a"]["speakers"]["speaker-a"]["display_name"] == "Андрей Иванов"

    roster = deactivate_project_speaker(roster, "project-a", "speaker-a")
    assert roster["projects"]["project-a"]["speakers"]["speaker-a"]["active"] is False


def test_speaker_metadata_gating_yes_no_unknown() -> None:
    yes_doc = build_structured_transcript_document_text("Doc", "Speaker 1: hello", build_transcript_metadata_lines("a.mp3", "drive", "elevenlabs", "scribe_v2", "auto", True, "2026-06-01 00:00 UTC"))
    no_doc = build_structured_transcript_document_text("Doc", "Speaker 1: hello", build_transcript_metadata_lines("a.mp3", "drive", "elevenlabs", "scribe_v2", "auto", False, "2026-06-01 00:00 UTC"))
    unknown_doc = "Doc\n\nSpeaker 1: hello"

    assert detect_speakers_metadata_value(yes_doc) == "yes"
    assert detect_speakers_metadata_value(no_doc) == "no"
    assert detect_speakers_metadata_value(unknown_doc) == "unknown"


def test_detects_speaker_n_labels_only_at_turn_boundaries() -> None:
    text = "Speaker 1: first\nкак сказал Speaker 2 вчера\nSpeaker 10: tenth\n  Speaker 3: indented should not count"
    turns = detect_speaker_turns(text)
    assert [turn["label"] for turn in turns] == ["Speaker 1", "Speaker 10"]
    assert all("как сказал" not in turn["label"] for turn in turns)


def test_speaker_sample_extraction_skips_short_and_truncates() -> None:
    long_text = "x" * 350
    turns = detect_speaker_turns(f"Speaker 1: ok\nSpeaker 1: meaningful phrase here\nSpeaker 1: {long_text}\nSpeaker 2: also meaningful")
    samples = extract_meaningful_speaker_samples(turns, max_samples=3, max_chars=300, min_chars=12)

    assert samples["Speaker 1"][0] == "meaningful phrase here"
    assert len(samples["Speaker 1"][1]) == 300
    assert samples["Speaker 1"][1].endswith("…")
    assert samples["Speaker 2"] == ["also meaningful"]


def test_mapping_validation_and_plan_unmapped_speakers_remain_unchanged() -> None:
    project = {
        "id": "project-a",
        "name": "Project",
        "speakers": {
            "speaker-a": {"id": "speaker-a", "display_name": "Андрей", "active": True},
            "speaker-b": {"id": "speaker-b", "display_name": "Мария", "active": False},
        },
    }
    text = "Speaker 1: hello there\nSpeaker 2: stays unchanged"
    parsed = parse_speaker_mapping("Speaker 1=Андрей\nSpeaker 2=Мария\nbad", ["Андрей"])
    assert parsed["mapping"] == {"Speaker 1": "Андрей"}
    assert len(parsed["errors"]) == 2

    plan = build_speaker_rename_plan(text, project, "Speaker 1=Андрей")
    assert plan["replacements"] == {"Speaker 1": {"target": "Андрей", "count": 1}}
    assert plan["unmapped"] == ["Speaker 2"]


def test_apply_renames_only_turn_boundaries_and_preserves_body_text() -> None:
    original = "Speaker 1: hello Speaker 1 inside body\nкак сказал Speaker 1 yesterday\nSpeaker 2: body remains"
    renamed, result = apply_speaker_label_renames_to_plain_text(original, {"Speaker 1": "Андрей"})

    assert result["counts"] == {"Speaker 1": 1}
    assert renamed.startswith("Андрей: hello Speaker 1 inside body")
    assert "как сказал Speaker 1 yesterday" in renamed
    assert "Speaker 2: body remains" in renamed
    assert renamed.replace("Андрей:", "Speaker 1:") == original


def test_parse_google_doc_url_or_id_supports_url_and_raw_id() -> None:
    assert parse_google_doc_url_or_id("https://docs.google.com/document/d/abc_123-XYZ45678901234567890/edit") == "abc_123-XYZ45678901234567890"
    assert parse_google_doc_url_or_id("abc_123-XYZ45678901234567890") == "abc_123-XYZ45678901234567890"
    assert parse_google_doc_url_or_id("not a doc") == ""


def test_speaker_rename_plan_fingerprints_mapping_and_active_roster() -> None:
    project = {
        "id": "project-a",
        "name": "Project",
        "speakers": {
            "speaker-a": {"id": "speaker-a", "display_name": "Андрей", "active": True},
            "speaker-b": {"id": "speaker-b", "display_name": "Мария", "active": True},
            "speaker-c": {"id": "speaker-c", "display_name": "Hidden", "active": False},
        },
    }
    text = "Speaker 1: hello there\nSpeaker 2: second line"
    plan = build_speaker_rename_plan(text, project, "Speaker 1=Андрей")

    assert plan["project_id"] == "project-a"
    assert plan["mapping_text_hash"] == speaker_mapping_text_fingerprint("Speaker 1=Андрей")
    assert plan["mapping_text_hash"] != speaker_mapping_text_fingerprint("Speaker 1=Мария")
    assert plan["active_speaker_roster_hash"] == active_project_speaker_roster_fingerprint(project)
    assert plan["active_speaker_roster"] == [
        {"id": "speaker-a", "display_name": "Андрей"},
        {"id": "speaker-b", "display_name": "Мария"},
    ]

    changed_project = json.loads(json.dumps(project))
    changed_project["speakers"]["speaker-a"]["display_name"] = "Андрей Иванов"
    assert plan["active_speaker_roster_hash"] != active_project_speaker_roster_fingerprint(changed_project)


def test_speaker_rename_apply_refuses_stale_preview_plan_context() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")
    apply_block = source.split("def on_apply_speaker_rename_clicked", 1)[1].split(
        "def on_start_clicked" if "def on_start_clicked" in source.split("def on_apply_speaker_rename_clicked", 1)[1] else "speaker_project_dropdown.observe",
        1,
    )[0]

    assert "SPEAKER_RENAME_STALE_PLAN_MESSAGE" in source
    assert "Отказ: проект, список спикеров или mapping изменились после предпросмотра" in source
    assert 'plan.get("doc_id") != speaker_project_state.get("doc_id")' in apply_block
    assert 'plan.get("doc_hash") != speaker_project_state.get("doc_hash")' in apply_block
    assert 'plan.get("project_id") != speaker_project_dropdown.value' in apply_block
    assert 'plan.get("project_id") != current_project.get("id")' in apply_block
    assert 'plan.get("mapping_text_hash") != speaker_mapping_text_fingerprint(speaker_mapping_text.value)' in apply_block
    assert 'plan.get("active_speaker_roster_hash") != active_project_speaker_roster_fingerprint(current_project)' in apply_block
    assert "print(SPEAKER_RENAME_STALE_PLAN_MESSAGE)" in apply_block


def test_speaker_rename_plan_is_cleared_when_relevant_ui_state_changes() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")

    assert "def clear_speaker_rename_plan():" in source
    assert 'speaker_project_state["plan"] = None' in source
    assert "speaker_mapping_text.observe" in source
    assert "clear_speaker_rename_plan() if change.get(\"name\") == \"value\"" in source

    project_changed_block = source.split("def on_speaker_project_changed", 1)[1].split("def on_create_speaker_project", 1)[0]
    assert "clear_speaker_rename_plan()" in project_changed_block

    for start, end in [
        ("def on_rename_speaker_project", "def on_archive_speaker_project"),
        ("def on_archive_speaker_project", "def on_add_project_speaker"),
        ("def on_add_project_speaker", "def on_rename_project_speaker"),
        ("def on_rename_project_speaker", "def on_deactivate_project_speaker"),
        ("def on_deactivate_project_speaker", "def on_find_speakers_clicked"),
    ]:
        block = source.split(start, 1)[1].split(end, 1)[0]
        assert "clear_speaker_rename_plan()" in block

    find_block = source.split("def on_find_speakers_clicked", 1)[1].split("def on_preview_speaker_rename_clicked", 1)[0]
    assert '"plan": None' in find_block


def test_openai_models_and_request_payload_contract_remain_unchanged() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")
    assert 'OPENAI_DEFAULT_MODEL = "gpt-4o-transcribe"' in source
    assert 'OPENAI_DIARIZE_MODEL = "gpt-4o-transcribe-diarize"' in source
    openai_form = source.split("def build_openai_transcription_form_data", 1)[1].split("def transcribe_openai_fileobj", 1)[0]
    assert '("response_format", "text")' in openai_form
    assert '("response_format", "diarized_json")' in openai_form
    assert '("chunking_strategy", "auto")' in openai_form
    assert '("prompt", prompt)' in openai_form


def test_elevenlabs_batch_request_payload_contract_remains_unchanged() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")
    eleven_form = source.split("def build_transcription_form_data", 1)[1].split("def log_safe_http_error", 1)[0]
    assert 'MODEL_ID = "scribe_v2"' in source
    assert '("model_id", MODEL_ID)' in eleven_form
    assert '("timestamps_granularity", "none")' in eleven_form
    assert '("diarize", str(options.separate_speakers).lower())' in eleven_form
    assert '("no_verbatim", str(USE_NO_VERBATIM).lower())' in eleven_form
    assert '("temperature", str(TEMPERATURE))' in eleven_form
    assert '("tag_audio_events", str(TAG_AUDIO_EVENTS).lower())' in eleven_form
    assert '("keyterms", term)' in eleven_form


def test_openai_split_message_uses_safe_reason_without_paths_or_payloads() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")
    block = source.split("if len(parts) > 1:", 1)[1].split("transcripts = []", 1)[0]
    assert 'OpenAI smart split: {len(parts)} частей (reason: {split_reason})' in block
    assert "resp.text" not in block
    assert "OPENAI_API_KEY" not in block
    assert "prepared_path" not in block


def test_provider_authority_docs_do_not_include_fake_secret_values_or_raw_bodies() -> None:
    docs = [
        ROOT / "README.md",
        ROOT / "docs" / "project-spec.md",
        ROOT / "docs" / "architecture.md",
        ROOT / "docs" / "delivery-plan.md",
    ]
    forbidden = ["sk-", "Bearer ", "raw request", "raw response body"]
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        for needle in forbidden:
            assert needle not in text


OPENAI_SPLITTER_HELPERS = {
    "find_nearby_silence_split_point",
    "choose_openai_split_duration",
    "split_openai_audio_if_needed",
    "create_openai_audio_chunk",
}


def test_openai_splitter_configuration_globals_are_defined_in_production_config() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")
    python_source = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("!")
    )
    module = ast.parse(python_source, filename=str(CANONICAL_SOURCE))

    assigned_openai_names = set()
    referenced_openai_names = set()
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.startswith("OPENAI_"):
                    assigned_openai_names.add(target.id)
        elif isinstance(node, ast.FunctionDef) and node.name in OPENAI_SPLITTER_HELPERS:
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and child.id.startswith("OPENAI_"):
                    referenced_openai_names.add(child.id)

    assert referenced_openai_names
    assert referenced_openai_names <= assigned_openai_names
    assert HELPERS["OPENAI_MIN_SPLIT_DURATION_SECONDS"] == 30


def test_openai_split_reason_allows_small_short_file_without_split() -> None:
    assert get_openai_split_reason(24 * 1024 * 1024, 1320) is None


def test_openai_split_reason_flags_duration_only_for_long_small_file() -> None:
    assert get_openai_split_reason(24 * 1024 * 1024, 1320.01) == "duration"




def test_openai_aggregate_timing_labels_are_in_stable_summary_order() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")
    summary_section = source.split("def print_timing_summary", 1)[1].split("def format_timing_line", 1)[0]
    ordered = [
        "provider_transcription",
        "openai_split",
        "openai_chunk_prepare",
        "openai_provider_request",
        "openai_merge",
        "postprocess_merge",
    ]
    positions = [summary_section.index(f'"{label}"') for label in ordered]
    assert positions == sorted(positions)


def test_openai_multi_part_timing_diagnostics_are_safe_and_complete() -> None:
    records = [
        {"index": 1, "total": 2, "duration_seconds": 1318.8, "size_bytes": 21_000_000, "prepare_seconds": 1.234, "provider_request_seconds": 5.678},
        {"index": 2, "total": 2, "duration_seconds": 600.0, "size_bytes": 10_000_000, "prepare_seconds": 2.0, "provider_request_seconds": 6.0},
    ]
    diagnostics = build_openai_chunk_timing_diagnostics(records, split_seconds=3.5, merge_seconds=0.25)

    assert "=== OpenAI chunk timing (local) ===" in diagnostics
    assert "Part 1/2" in diagnostics
    assert "duration=1318.80s" in diagnostics
    assert "size=20.03 MB" in diagnostics
    assert "prepare=1.23s" in diagnostics
    assert "provider request (upload + provider wait)=5.68s" in diagnostics
    assert "totals: split=3.50s, chunk prepare=3.23s, provider request (upload + provider wait)=11.68s, merge=0.25s" in diagnostics

    unsafe_values = [
        "/tmp/private/source.m4a",
        "private-recording.m4a",
        "docs.google.com/document/d/fake",
        "fake transcript body",
        "sk-fake-key",
        "Bearer fake",
        "raw provider body",
        "response payload",
    ]
    for unsafe in unsafe_values:
        assert unsafe not in diagnostics


def test_openai_duration_only_split_records_per_part_preparation_timing(tmp_path) -> None:
    prepared_path = tmp_path / "prepared.m4a"
    prepared_path.write_bytes(b"x" * 100)
    records = []
    globals_dict = split_openai_audio_if_needed.__globals__
    original_get_duration = globals_dict["get_media_duration_seconds"]
    original_create_chunk = globals_dict["create_openai_audio_chunk"]
    original_choose_duration = globals_dict["choose_openai_split_duration"]

    def fake_create_chunk(**_kwargs):
        output_path = tmp_path / f"chunk-{len(records)}.m4a"
        output_path.write_bytes(b"chunk")
        return str(output_path)

    globals_dict["get_media_duration_seconds"] = lambda _path: 1320.01
    globals_dict["create_openai_audio_chunk"] = fake_create_chunk
    globals_dict["choose_openai_split_duration"] = lambda **kwargs: min(kwargs["target_duration"], kwargs["total_duration"] - kwargs["start_seconds"])
    try:
        parts, cleanup_paths, split_reason = split_openai_audio_if_needed(str(prepared_path), "prepared.m4a", chunk_timing_records=records)
    finally:
        globals_dict["get_media_duration_seconds"] = original_get_duration
        globals_dict["create_openai_audio_chunk"] = original_create_chunk
        globals_dict["choose_openai_split_duration"] = original_choose_duration

    assert split_reason == "duration"
    assert parts
    assert cleanup_paths
    assert records
    assert records[0]["prepare_seconds"] >= 0
    assert records[0]["duration_seconds"] > 0
    assert records[0]["size_bytes"] == len(b"chunk")


def test_openai_request_payload_and_batch_paths_do_not_introduce_parallelism() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")
    openai_path = source.split("def transcribe_media_path_openai", 1)[1].split("def transcribe_media_path", 1)[0]
    assert "transcribe_openai_fileobj(part_name" in openai_path
    assert "for idx, (part_path, part_name) in enumerate(parts, start=1):" in openai_path
    forbidden = ["ThreadPoolExecutor", "ProcessPoolExecutor", "asyncio", "gather(", "create_task", "threading.Thread", "multiprocessing"]
    for token in forbidden:
        assert token not in openai_path

    elevenlabs_path = source.split("def transcribe_media_path_elevenlabs", 1)[1].split("def transcribe_media_path_openai", 1)[0]
    assert elevenlabs_path.count("transcribe_fileobj(send_name, f, mime_type, options)") == 1


def test_openai_failed_second_chunk_diagnostics_remain_safe() -> None:
    records = [
        {"index": 1, "total": 2, "duration_seconds": 100.0, "size_bytes": 1234, "prepare_seconds": 0.5, "provider_request_seconds": 4.0},
        {"index": 2, "total": 2, "duration_seconds": 90.0, "size_bytes": 2345, "prepare_seconds": 0.6, "provider_request_seconds": 1.0},
    ]
    diagnostics = build_openai_chunk_timing_diagnostics(records, split_seconds=1.2, merge_seconds=None, failed=True)
    assert "Part 1/2" in diagnostics
    assert "Part 2/2" in diagnostics
    assert "failed before all OpenAI parts completed" in diagnostics
    for unsafe in ["/content/drive/private.m4a", "secret-file.m4a", "transcript words", "sk-test", "Bearer"]:
        assert unsafe not in diagnostics


def test_openai_split_reason_flags_size_only_for_large_short_file() -> None:
    assert get_openai_split_reason(26 * 1024 * 1024, 1320) == "size"


def test_openai_split_reason_flags_size_and_duration() -> None:
    assert get_openai_split_reason(26 * 1024 * 1024, 1321) == "size_and_duration"


def test_openai_duration_only_split_path_reaches_duration_selection_without_name_error(tmp_path) -> None:
    prepared_path = tmp_path / "prepared.m4a"
    prepared_path.write_bytes(b"x")
    created_chunks = []
    choose_calls = []

    globals_dict = split_openai_audio_if_needed.__globals__
    original_get_duration = globals_dict["get_media_duration_seconds"]
    original_create_chunk = globals_dict["create_openai_audio_chunk"]
    original_choose_duration = globals_dict["choose_openai_split_duration"]

    def fake_create_chunk(**_kwargs):
        output_path = tmp_path / f"chunk-{len(created_chunks)}.m4a"
        output_path.write_bytes(b"chunk")
        created_chunks.append(str(output_path))
        return str(output_path)

    def recording_choose_duration(**kwargs):
        choose_calls.append(kwargs)
        return original_choose_duration(**kwargs)

    globals_dict["get_media_duration_seconds"] = lambda _path: 1320.01
    globals_dict["create_openai_audio_chunk"] = fake_create_chunk
    globals_dict["choose_openai_split_duration"] = recording_choose_duration
    original_find_silence = original_choose_duration.__globals__["find_nearby_silence_split_point"]
    original_choose_duration.__globals__["find_nearby_silence_split_point"] = lambda **_kwargs: None
    try:
        parts, cleanup_paths, split_reason = split_openai_audio_if_needed(
            str(prepared_path),
            "prepared.m4a",
        )
    finally:
        globals_dict["get_media_duration_seconds"] = original_get_duration
        globals_dict["create_openai_audio_chunk"] = original_create_chunk
        globals_dict["choose_openai_split_duration"] = original_choose_duration
        original_choose_duration.__globals__["find_nearby_silence_split_point"] = original_find_silence

    assert split_reason == "duration"
    assert choose_calls
    assert parts
    assert cleanup_paths == created_chunks


def test_openai_split_duration_never_uses_pause_after_target() -> None:
    calls = []

    def after_target_pause(**kwargs):
        calls.append(kwargs)
        return kwargs["target_end_seconds"] + 5

    original = choose_openai_split_duration.__globals__["find_nearby_silence_split_point"]
    choose_openai_split_duration.__globals__["find_nearby_silence_split_point"] = after_target_pause
    try:
        duration = choose_openai_split_duration("prepared.m4a", 0, 1320, 2000)
    finally:
        choose_openai_split_duration.__globals__["find_nearby_silence_split_point"] = original

    assert duration == 1320
    assert calls[0]["target_end_seconds"] == 1320


def test_openai_split_duration_fallback_stays_at_or_below_target() -> None:
    original = choose_openai_split_duration.__globals__["find_nearby_silence_split_point"]
    choose_openai_split_duration.__globals__["find_nearby_silence_split_point"] = lambda **_kwargs: None
    try:
        duration = choose_openai_split_duration("prepared.m4a", 10, 1320, 4000)
    finally:
        choose_openai_split_duration.__globals__["find_nearby_silence_split_point"] = original

    assert duration == 1320


parse_user_segment_plan = HELPERS["parse_user_segment_plan"]
get_initial_user_segment_builder_rows = HELPERS["get_initial_user_segment_builder_rows"]
add_user_segment_builder_row = HELPERS["add_user_segment_builder_row"]
remove_last_user_segment_builder_row = HELPERS["remove_last_user_segment_builder_row"]
normalize_user_segment_builder_rows = HELPERS["normalize_user_segment_builder_rows"]
get_user_segment_builder_start_labels = HELPERS["get_user_segment_builder_start_labels"]
validate_user_segment_builder_add_result = HELPERS["validate_user_segment_builder_add_result"]
validate_user_segment_builder_add_end = HELPERS["validate_user_segment_builder_add_end"]
try_add_user_segment_builder_row = HELPERS["try_add_user_segment_builder_row"]
build_user_segments_from_builder = HELPERS["build_user_segments_from_builder"]
build_user_segment_requested_document_titles = HELPERS["build_user_segment_requested_document_titles"]
reject_duplicate_user_segment_requested_titles = HELPERS["reject_duplicate_user_segment_requested_titles"]
allocate_user_segment_document_titles = HELPERS["allocate_user_segment_document_titles"]
apply_user_segment_document_titles = HELPERS["apply_user_segment_document_titles"]
get_existing_document_names_from_index = HELPERS["get_existing_document_names_from_index"]
build_user_segment_source_signature = HELPERS["build_user_segment_source_signature"]
build_user_segment_preview_text = HELPERS["build_user_segment_preview_text"]
user_segment_mode_unavailable_message = HELPERS["user_segment_mode_unavailable_message"]
build_safe_user_segment_source_check_text = HELPERS["build_safe_user_segment_source_check_text"]
create_user_segment_media_file = HELPERS["create_user_segment_media_file"]
process_user_segments_for_source = HELPERS["process_user_segments_for_source"]


def test_user_segment_parser_parses_mmss_and_end_and_hhmmss() -> None:
    segments = parse_user_segment_plan("Project A | 00:00-23:40\nProject B | 23:40-end", 1800)
    assert segments[0]["label"] == "Project A"
    assert segments[0]["start_seconds"] == 0
    assert segments[0]["end_seconds"] == 1420
    assert segments[1]["end_label"] == "end"
    hh = parse_user_segment_plan("Project Gamma | 00:00-01:05:20\nTail | 01:05:20-end", 4000)
    assert hh[0]["end_seconds"] == 3920


def test_user_segment_visual_builder_defaults_and_card_state_static() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")
    assert 'description="Разделить запись на несколько документов"' in source
    assert "user_segment_builder_widget.layout.display = \"\" if user_segment_enable_widget.value" in source
    assert "widgets.Textarea(" not in source.split("user_segment_enable_widget = widgets.Checkbox", 1)[1].split("check_source_button", 1)[0]
    render_block = source.split("def render_user_segment_builder_cards", 1)[1].split("def on_user_segment_add_part_clicked", 1)[0]
    assert "Конец: <b>До конца записи</b>" in render_block
    assert "widgets.Checkbox(" not in render_block
    rows = get_initial_user_segment_builder_rows()
    assert rows == [{"title": "", "end": "", "to_end": True}]
    assert get_user_segment_builder_start_labels(rows) == ["00:00"]


def test_user_segment_visual_builder_add_remove_and_inherited_start() -> None:
    rows = get_initial_user_segment_builder_rows()
    rows[0]["end"] = "10:10"
    rows = add_user_segment_builder_row(rows)
    assert len(rows) == 2
    assert rows[0]["to_end"] is False
    assert rows[1]["to_end"] is True
    assert get_user_segment_builder_start_labels(rows, 1200) == ["00:00", "10:10"]
    rows = remove_last_user_segment_builder_row(rows)
    assert len(rows) == 1
    assert rows[0]["to_end"] is True


def test_user_segment_visual_builder_add_requires_valid_final_end() -> None:
    rows = get_initial_user_segment_builder_rows()
    updated, error = try_add_user_segment_builder_row(rows)
    assert updated == rows
    assert "Часть 1" in error
    assert "после 00:00" in error
    assert get_user_segment_builder_start_labels(updated) == ["00:00"]

    rows[0]["end"] = "bad"
    updated, error = try_add_user_segment_builder_row(rows)
    assert len(updated) == 1
    assert "Часть 1" in error
    assert "после 00:00" in error
    assert "—" not in get_user_segment_builder_start_labels(updated)

    rows[0]["end"] = "00:00"
    updated, error = try_add_user_segment_builder_row(rows)
    assert len(updated) == 1
    assert "Часть 1" in error
    assert "после 00:00" in error


def test_user_segment_visual_builder_valid_add_and_final_state_normalization() -> None:
    rows = [{"title": "Keep me", "end": "10:10", "to_end": False}]
    updated, error = try_add_user_segment_builder_row(rows, duration_seconds=1200)
    assert error is None
    assert updated == [
        {"title": "Keep me", "end": "10:10", "to_end": False},
        {"title": "", "end": "", "to_end": True},
    ]
    assert get_user_segment_builder_start_labels(updated, 1200) == ["00:00", "10:10"]
    assert normalize_user_segment_builder_rows([
        {"title": "", "end": "10:10", "to_end": True},
        {"title": "", "end": "", "to_end": False},
    ]) == [
        {"title": "", "end": "10:10", "to_end": False},
        {"title": "", "end": "", "to_end": True},
    ]


def test_user_segment_visual_builder_add_rejects_end_beyond_known_duration() -> None:
    rows = [{"title": "", "end": "02:00", "to_end": True}]
    updated, error = try_add_user_segment_builder_row(rows, duration_seconds=60)
    assert len(updated) == 1
    assert "Часть 1" in error
    assert "длительность" in error



def test_user_segment_visual_builder_earlier_malformed_boundary_blocks_add() -> None:
    rows = [
        {"title": "", "end": "bad", "to_end": False},
        {"title": "", "end": "00:20", "to_end": True},
    ]
    updated, error = try_add_user_segment_builder_row(rows, duration_seconds=60)
    result = validate_user_segment_builder_add_result(rows, duration_seconds=60)
    assert len(updated) == 2
    assert updated == normalize_user_segment_builder_rows(rows)
    assert result["row_index"] == 0
    assert error == result["error"]
    assert "Часть 1" in error
    assert "после 00:00" in error


def test_user_segment_visual_builder_earlier_non_monotonic_boundary_blocks_add() -> None:
    rows = [
        {"title": "", "end": "00:00", "to_end": False},
        {"title": "", "end": "00:20", "to_end": True},
    ]
    updated, error = try_add_user_segment_builder_row(rows, duration_seconds=60)
    assert len(updated) == 2
    assert "Часть 1" in error
    assert "после 00:00" in error
    assert validate_user_segment_builder_add_result(rows, duration_seconds=60)["row_index"] == 0


def test_user_segment_visual_builder_known_duration_rejects_prior_and_final_boundaries() -> None:
    prior_rows = [
        {"title": "", "end": "01:10", "to_end": False},
        {"title": "", "end": "01:20", "to_end": True},
    ]
    prior_updated, prior_error = try_add_user_segment_builder_row(prior_rows, duration_seconds=60)
    assert len(prior_updated) == 2
    assert "Часть 1" in prior_error
    assert "длительность" in prior_error
    assert validate_user_segment_builder_add_result(prior_rows, duration_seconds=60)["row_index"] == 0

    final_rows = [
        {"title": "", "end": "00:20", "to_end": False},
        {"title": "", "end": "01:10", "to_end": True},
    ]
    final_updated, final_error = try_add_user_segment_builder_row(final_rows, duration_seconds=60)
    assert len(final_updated) == 2
    assert "Часть 2" in final_error
    assert "длительность" in final_error
    assert validate_user_segment_builder_add_result(final_rows, duration_seconds=60)["row_index"] == 1


def test_user_segment_visual_builder_valid_multi_card_add_preserves_starts() -> None:
    rows = [
        {"title": "A", "end": "00:20", "to_end": False},
        {"title": "B", "end": "00:40", "to_end": True},
    ]
    updated, error = try_add_user_segment_builder_row(rows, duration_seconds=90)
    assert error is None
    assert updated == [
        {"title": "A", "end": "00:20", "to_end": False},
        {"title": "B", "end": "00:40", "to_end": False},
        {"title": "", "end": "", "to_end": True},
    ]
    assert get_user_segment_builder_start_labels(updated, 90) == ["00:00", "00:20", "00:40"]


def test_user_segment_visual_builder_canonical_build_rejects_invalid_multi_card_state() -> None:
    for rows, expected in [
        ([{"title": "", "end": "bad", "to_end": False}, {"title": "", "end": "", "to_end": True}], "Часть 1"),
        ([{"title": "", "end": "00:20", "to_end": False}, {"title": "", "end": "00:20", "to_end": False}, {"title": "", "end": "", "to_end": True}], "Часть 2"),
    ]:
        with pytest.raises(ValueError, match=expected):
            build_user_segments_from_builder(rows, 60)

def test_user_segment_visual_builder_builds_canonical_segments_and_titles() -> None:
    rows = [
        {"title": "", "end": "10:10", "to_end": False},
        {"title": "  Manual   Title  ", "end": "", "to_end": True},
    ]
    segments = build_user_segments_from_builder(rows, 1200)
    assert segments[0]["display_label"] == "Часть 1"
    assert segments[0]["start_label"] == "00:00"
    assert segments[0]["end_label"] == "10:10"
    assert segments[0]["duration_seconds"] == 610
    assert segments[1]["display_label"] == "Часть 2"
    assert segments[1]["start_label"] == "10:10"
    assert segments[1]["end_label"] == "end"
    assert segments[1]["requested_document_title"] == "Manual Title"
    assert build_user_segment_requested_document_titles("Source File.m4a", segments) == [
        "Source File — Часть 1",
        "Manual Title",
    ]


def test_user_segment_visual_builder_accepts_hhmmss_and_rejects_card_errors() -> None:
    segments = build_user_segments_from_builder([
        {"title": "", "end": "01:05:20", "to_end": False},
        {"title": "", "end": "", "to_end": True},
    ], 4000)
    assert segments[0]["end_seconds"] == 3920
    cases = [
        ([{"title": "", "end": "bad", "to_end": False}, {"title": "", "end": "", "to_end": True}], "Часть 1"),
        ([{"title": "", "end": "00:00", "to_end": False}, {"title": "", "end": "", "to_end": True}], "после 00:00"),
        ([{"title": "", "end": "00:10", "to_end": True}, {"title": "", "end": "", "to_end": True}], "только для последней"),
        ([{"title": "", "end": "00:10", "to_end": False}, {"title": "", "end": "", "to_end": False}], "финальная часть"),
        ([{"title": "Bad | Title", "end": "", "to_end": True}], "Название Google Doc"),
    ]
    for rows, expected in cases:
        try:
            build_user_segments_from_builder(rows, 60)
        except ValueError as exc:
            assert expected in str(exc)
            assert "формат" not in str(exc)
        else:
            raise AssertionError("expected builder validation error")


def test_user_segment_visual_builder_runtime_rejects_malformed_final_to_end_false() -> None:
    try:
        build_user_segments_from_builder([{"title": "", "end": "", "to_end": False}], 60)
    except ValueError as exc:
        assert "Часть 1" in str(exc)
        assert "До конца записи" in str(exc)
    else:
        raise AssertionError("expected final to_end defensive validation")


def test_user_segment_parser_rejects_invalid_inputs() -> None:
    cases = [
        (" | 00:00-end", 100),
        ("A | nope-end", 100),
        ("A | 00:00-00:50\nB | 00:40-end", 100),
        ("A | 00:30-00:50\nB | 00:50-end", 100),
        ("A | 00:00-00:40\nB | 00:50-end", 100),
        ("A | 00:00-00:50\nB | 00:50-01:30", 100),
        ("A | 00:00-00:00\nB | 00:00-end", 100),
        ("Bad/Label | 00:00-end", 100),
        ("Bad\\Label | 00:00-end", 100),
        ("Bad\x01Label | 00:00-end", 100),
        ("A | 00:00-02:00\nB | 02:00-end", 100),
    ]
    for raw, duration in cases:
        try:
            parse_user_segment_plan(raw, duration)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected rejection for {raw!r}")


def test_user_segmentation_ui_mode_availability_static() -> None:
    assert user_segment_mode_unavailable_message("local_file") == ""
    assert user_segment_mode_unavailable_message("drive_file") == ""
    for mode in ["local_multi", "drive_multi", "drive_folder"]:
        assert "доступна только" in user_segment_mode_unavailable_message(mode)


def test_user_segment_source_identity_is_distinct_and_stable() -> None:
    a1 = build_user_segment_source_signature("orig", "Weekly call.mp4", "Project A", "00:00", "23:40", "drive_file", "file-id")
    a2 = build_user_segment_source_signature("orig", "Weekly call.mp4", "Project A", "00:00", "23:40", "drive_file", "file-id")
    b = build_user_segment_source_signature("orig", "Weekly call.mp4", "Project B", "23:40", "end", "drive_file", "file-id")
    assert a1 == a2
    assert a1 != b


def test_user_segment_preview_is_safe() -> None:
    segments = parse_user_segment_plan("Project A | 00:00-00:30\nProject B | 00:30-end", 60)
    text = build_user_segment_preview_text(segments)
    assert "Project A" in text and "00:30-end" in text
    forbidden = ["/tmp/private/source.m4a", "sk-fake", "raw provider body", "transcript text", "docs.google.com/document/d/fake"]
    for token in forbidden:
        assert token not in text



def test_user_segment_parser_rejects_duplicate_labels_case_insensitive() -> None:
    raw = "Project A | 00:00-00:10\nProject B | 00:10-00:20\nproject a | 00:20-end"
    try:
        parse_user_segment_plan(raw, 30)
    except ValueError as exc:
        assert "Строка 3" in str(exc)
        assert "дублируется метка" in str(exc)
        assert "project a" in str(exc)
    else:
        raise AssertionError("expected duplicate label rejection")


def test_user_segment_parser_rejects_duplicate_labels_after_whitespace_normalization() -> None:
    raw = "Project   A | 00:00-00:10\nOther | 00:10-00:20\nproject a | 00:20-end"
    try:
        parse_user_segment_plan(raw, 30)
    except ValueError as exc:
        assert "Строка 3" in str(exc)
        assert "уникальны" in str(exc)
    else:
        raise AssertionError("expected duplicate label rejection")


def test_user_segment_parser_valid_unique_labels_keep_structure() -> None:
    segments = parse_user_segment_plan("Project A | 00:00-00:10\nProject B | 00:10-end", 20)
    assert [segment["label"] for segment in segments] == ["Project A", "Project B"]
    assert segments[0]["range_label"] == "00:00-00:10"
    assert segments[1]["range_label"] == "00:10-end"


def test_user_segment_safe_source_check_text_contains_only_safe_preview() -> None:
    segments = parse_user_segment_plan("Project A | 00:00-00:30\nProject B | 00:30-end", 60)
    text = build_safe_user_segment_source_check_text(
        source_type_label="файл Google Drive",
        filename="Weekly call.mp4",
        is_video=True,
        segments=segments,
        conflict_count=1,
        manifest_enabled=True,
    )
    assert "Weekly call.mp4" in text
    assert "Сегментация: 2" in text
    assert "1. Project A" in text
    assert "Время: 00:00-00:30" in text
    assert "2. Project B" in text
    assert "Время: 00:30-end" in text
    assert "Совпадений имён документов по сегментам: 1" in text
    forbidden = [
        "/content/drive/MyDrive/private.mp4",
        "/tmp/elevenlabs_api_secret.m4a",
        "drive-file-id-123",
        "https://drive.google.com/file/d/drive-file-id-123/view",
        "source_reference",
        "transcript text",
        "sk-fake",
        "Bearer fake",
        "raw payload",
        "raw response",
    ]
    for token in forbidden:
        assert token not in text



def test_user_segment_media_file_uses_accurate_audio_only_m4a_command(tmp_path) -> None:
    calls = []
    output_path = tmp_path / "segment.m4a"
    globals_dict = create_user_segment_media_file.__globals__
    original_create_temp = globals_dict.get("create_project_temp_file")
    original_ensure = globals_dict.get("ensure_ffmpeg_available")
    original_run = globals_dict["subprocess"].run
    globals_dict["create_project_temp_file"] = lambda suffix="": str(output_path)
    globals_dict["ensure_ffmpeg_available"] = lambda: None

    def fake_run(cmd, check, stdout, stderr):
        calls.append(cmd)
        output_path.write_bytes(b"m4a")

    globals_dict["subprocess"].run = fake_run
    try:
        result = create_user_segment_media_file(
            "/content/drive/MyDrive/source.mp4",
            {"start_seconds": 1420.0, "duration_seconds": 120.5},
        )
    finally:
        globals_dict["subprocess"].run = original_run
        if original_create_temp is None:
            globals_dict.pop("create_project_temp_file", None)
        else:
            globals_dict["create_project_temp_file"] = original_create_temp
        if original_ensure is None:
            globals_dict.pop("ensure_ffmpeg_available", None)
        else:
            globals_dict["ensure_ffmpeg_available"] = original_ensure

    assert result == str(output_path)
    cmd = calls[0]
    assert cmd[-1].endswith(".m4a")
    assert not cmd[-1].endswith(".mp4")
    assert cmd.index("-i") < cmd.index("-ss")
    assert cmd[cmd.index("-ss") + 1] == "1420.000"
    assert cmd[cmd.index("-t") + 1] == "120.500"
    assert "-vn" in cmd
    assert cmd[cmd.index("-ac") + 1] == "1"
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert "-b:a" in cmd
    assert "copy" not in cmd
    assert [cmd[i:i + 2] for i in range(len(cmd) - 1)].count(["-c", "copy"]) == 0


def test_user_segment_media_file_cleans_m4a_on_ffmpeg_failure(tmp_path) -> None:
    output_path = tmp_path / "failed.m4a"
    output_path.write_bytes(b"partial")
    globals_dict = create_user_segment_media_file.__globals__
    original_create_temp = globals_dict.get("create_project_temp_file")
    original_ensure = globals_dict.get("ensure_ffmpeg_available")
    original_run = globals_dict["subprocess"].run
    globals_dict["create_project_temp_file"] = lambda suffix="": str(output_path)
    globals_dict["ensure_ffmpeg_available"] = lambda: None

    def failing_run(*_args, **_kwargs):
        raise globals_dict["subprocess"].CalledProcessError(1, ["ffmpeg"], stderr=b"bad")

    globals_dict["subprocess"].run = failing_run
    try:
        try:
            create_user_segment_media_file("source.mov", {"start_seconds": 1.0, "duration_seconds": 2.0})
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected ffmpeg failure")
    finally:
        globals_dict["subprocess"].run = original_run
        if original_create_temp is None:
            globals_dict.pop("create_project_temp_file", None)
        else:
            globals_dict["create_project_temp_file"] = original_create_temp
        if original_ensure is None:
            globals_dict.pop("ensure_ffmpeg_available", None)
        else:
            globals_dict["ensure_ffmpeg_available"] = original_ensure

    assert not output_path.exists()


def test_user_segment_processing_passes_m4a_name_and_cleans_on_success(tmp_path) -> None:
    segment_path = tmp_path / "segment.m4a"
    segment_path.write_bytes(b"audio")
    calls = []
    upsert_calls = []
    globals_dict = process_user_segments_for_source.__globals__
    originals = {name: globals_dict.get(name) for name in [
        "get_media_duration_seconds", "create_user_segment_media_file", "transcribe_guarded_colab_source",
        "upsert_transcript_document", "mark_manifest_in_progress", "complete_guarded_colab_source",
        "mark_manifest_failed", "should_skip_by_manifest", "get_single_existing_doc_match", "append_success",
        "conflict_mode_needs_existing_match_before_transcription", "report_progress_for_file", "PROGRESS_STAGES_PER_FILE",
    ]}
    globals_dict["get_media_duration_seconds"] = lambda _path: 60.0
    globals_dict["create_user_segment_media_file"] = lambda _path, _segment: str(segment_path)
    def transcribe(_ctx, _signature, *, input_path, original_filename, timer=None):
        calls.append((input_path, original_filename))
        return "transcript", ("guard", "key", "token")
    globals_dict["transcribe_guarded_colab_source"] = transcribe
    globals_dict["upsert_transcript_document"] = lambda **kwargs: upsert_calls.append(kwargs) or {"status": "success", "action": "created", "doc_name": "Doc", "link": "link"}
    globals_dict["mark_manifest_in_progress"] = lambda *_args, **_kwargs: None
    globals_dict["complete_guarded_colab_source"] = lambda *_args, **_kwargs: None
    globals_dict["mark_manifest_failed"] = lambda *_args, **_kwargs: None
    globals_dict["should_skip_by_manifest"] = lambda *_args, **_kwargs: (False, "")
    globals_dict["get_single_existing_doc_match"] = lambda *_args, **_kwargs: None
    globals_dict["conflict_mode_needs_existing_match_before_transcription"] = lambda _mode: False
    globals_dict["report_progress_for_file"] = lambda *_args, **_kwargs: None
    globals_dict["PROGRESS_STAGES_PER_FILE"] = 4
    globals_dict["append_success"] = lambda successes, source_name, result: successes.append({"source": source_name, **result})

    class RunCtx:
        output_folder_id = "folder"
        conflict_mode = "update"
        ignore_manifest = True
        docs_index = {"синк t-сustom": [{"name": "Синк T-Custom"}]}
        user_segment_suffix_allocation_enabled = True
        manifest = {}
        settings_signature = "settings"
        options = object()

    try:
        successes, errors, skipped = process_user_segments_for_source(
            input_path="source.mp4",
            original_filename="Weekly call.mp4",
            original_source_signature="orig",
            original_source_meta={},
            source_mode="drive_file",
            source_reference="drive-ref",
            segment_plan_text="Project A | 00:00-end | Синк T-Custom",
            run_ctx=RunCtx(),
        )
    finally:
        for name, original in originals.items():
            if original is None:
                globals_dict.pop(name, None)
            else:
                globals_dict[name] = original

    assert not errors and not skipped and successes
    assert calls == [(str(segment_path), "Weekly call — Project A.m4a")]
    assert upsert_calls[0]["base_name"] == "Синк T-Custom (1)"
    assert upsert_calls[0]["segment_metadata"]["label"] == "Project A"
    assert upsert_calls[0]["segment_metadata"]["range_label"] == "00:00-end"
    assert upsert_calls[0]["segment_metadata"]["original_source_name"] == "Weekly call.mp4"
    assert not segment_path.exists()


def test_user_segment_processing_cleans_m4a_on_provider_failure(tmp_path) -> None:
    segment_path = tmp_path / "segment.m4a"
    segment_path.write_bytes(b"audio")
    globals_dict = process_user_segments_for_source.__globals__
    originals = {name: globals_dict.get(name) for name in [
        "get_media_duration_seconds", "create_user_segment_media_file", "transcribe_guarded_colab_source",
        "mark_manifest_in_progress", "mark_manifest_failed", "should_skip_by_manifest", "get_single_existing_doc_match",
        "conflict_mode_needs_existing_match_before_transcription", "report_progress_for_file", "PROGRESS_STAGES_PER_FILE",
    ]}
    globals_dict["get_media_duration_seconds"] = lambda _path: 60.0
    globals_dict["create_user_segment_media_file"] = lambda _path, _segment: str(segment_path)
    globals_dict["transcribe_guarded_colab_source"] = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("provider failed"))
    globals_dict["mark_manifest_in_progress"] = lambda *_args, **_kwargs: None
    globals_dict["mark_manifest_failed"] = lambda *_args, **_kwargs: None
    globals_dict["should_skip_by_manifest"] = lambda *_args, **_kwargs: (False, "")
    globals_dict["get_single_existing_doc_match"] = lambda *_args, **_kwargs: None
    globals_dict["conflict_mode_needs_existing_match_before_transcription"] = lambda _mode: False
    globals_dict["report_progress_for_file"] = lambda *_args, **_kwargs: None
    globals_dict["PROGRESS_STAGES_PER_FILE"] = 4

    class RunCtx:
        output_folder_id = "folder"
        conflict_mode = "update"
        ignore_manifest = True
        docs_index = {}
        manifest = {}
        settings_signature = "settings"
        options = object()

    try:
        successes, errors, skipped = process_user_segments_for_source(
            input_path="source.wav",
            original_filename="Weekly call.wav",
            original_source_signature="orig",
            original_source_meta={},
            source_mode="drive_file",
            source_reference="drive-ref",
            segment_plan_text="Project A | 00:00-end",
            run_ctx=RunCtx(),
        )
    finally:
        for name, original in originals.items():
            if original is None:
                globals_dict.pop(name, None)
            else:
                globals_dict[name] = original

    assert not successes and not skipped
    assert errors and errors[0]["source"] == "Weekly call — Project A"
    assert not segment_path.exists()


def test_user_segment_runtime_static_contracts() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")
    assert "Разделить запись по проектам перед транскрибацией" in source
    assert "create_user_segment_media_file" in source
    assert '"-ss", f"{segment[\'start_seconds\']:.3f}"' in source
    assert '"-t", f"{segment[\'duration_seconds\']:.3f}"' in source
    assert "process_user_segments_for_source" in source
    assert "transcribe_media_path(" in source
    assert "cleanup_user_segment_paths(segment_paths)" in source
    assert "ThreadPoolExecutor" not in source.split("def process_user_segments_for_source", 1)[1].split("def process_local_uploaded", 1)[0]


def test_user_segmented_and_non_segmented_paths_are_separate_static() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")
    local_block = source.split("def process_local_uploaded", 1)[1].split("def process_drive_file_input", 1)[0]
    drive_block = source.split("def process_drive_file_input", 1)[1].split("def process_drive_multi_input", 1)[0]
    drive_local_block = drive_block.split('if resolved["source_type"] == "local_path":', 1)[1].split('if resolved["mimeType"] == FOLDER_MIME:', 1)[0]
    drive_download_block = drive_block.split('if resolved["mimeType"] == FOLDER_MIME:', 1)[1].split("def process_drive_multi_input", 1)[0] if "def process_drive_multi_input" in drive_block else drive_block.split('if resolved["mimeType"] == FOLDER_MIME:', 1)[1]

    assert "if user_segment_plan_text is not None or user_segment_builder_rows is not None:" in local_block
    assert "if user_segment_plan_text is not None or user_segment_builder_rows is not None:" in drive_local_block
    assert "if user_segment_plan_text is not None or user_segment_builder_rows is not None:" in drive_download_block

    for block in [local_block, drive_local_block, drive_download_block]:
        segment_index = block.index("if user_segment_plan_text is not None or user_segment_builder_rows is not None:")
        assert segment_index < block.index("conflict_mode_needs_existing_match_before_transcription")
        assert segment_index < block.index("should_skip_by_manifest")

    runtime_block = source.split("def process_user_segments_for_source", 1)[1].split("# =========================\n# 5) OUTPUT FOLDER PICKER", 1)[0]
    assert "mark_manifest_in_progress(" not in runtime_block
    assert "mark_manifest_failed(" not in runtime_block
    assert runtime_block.count("transcribe_guarded_colab_source(") == 7
    assert runtime_block.count("complete_guarded_colab_source(") == 7
    assert "transcribe_media_path(" not in runtime_block




def test_user_segment_failures_do_not_persist_source_before_google_docs_output_static() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")
    segment_block = source.split("def process_user_segments_for_source", 1)[1].split("def process_local_uploaded", 1)[0]
    assert "segment_signature = build_user_segment_source_signature" in segment_block
    assert "mark_manifest_in_progress(" not in segment_block
    assert "mark_manifest_failed(" not in segment_block
    assert segment_block.index("upsert_transcript_document(") < segment_block.index("complete_guarded_colab_source(")


def test_user_segment_source_check_uses_safe_branch_before_detailed_identifiers() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")
    check_block = source.split("def on_check_source_clicked", 1)[1].split("# Legacy/import helper", 1)[0]
    safe_branch = check_block.split('if mode == "drive_file" and user_segment_enable_widget.value:', 1)[1].split('if resolved["source_type"] == "drive_link":', 1)[0]
    assert "build_safe_user_segment_source_check_text" in safe_branch
    assert "return" in safe_branch
    detailed_block = check_block.split('if resolved["source_type"] == "drive_link":', 1)[1]
    assert 'print(f"ID: {resolved[\'id\']}")' in detailed_block
    assert 'print(f"Путь: {resolved[\'path\']}")' in detailed_block


def test_user_segment_docs_and_help_state_unique_label_rule() -> None:
    source = CANONICAL_SOURCE.read_text(encoding="utf-8")
    spec = (ROOT / "docs" / "project-spec.md").read_text(encoding="utf-8")
    assert "метки проектов должны быть уникальны" in source
    assert "case-insensitively" in spec


def test_user_segment_two_field_syntax_keeps_automatic_title_behavior() -> None:
    segments = parse_user_segment_plan("Tivali | 00:00-end", 60)
    assert segments[0]["requested_document_title"] is None
    assert build_user_segment_requested_document_titles("Синк Tivali 21.06.2026 (2).mp4", segments) == ["Синк Tivali 21.06.2026 (2) — Tivali"]


def test_user_segment_three_field_syntax_parses_custom_title_and_normalizes_spaces() -> None:
    segments = parse_user_segment_plan("Tivali | 00:00-end |  Синк   Tivali — задачи  ", 60)
    assert segments[0]["requested_document_title"] == "Синк Tivali — задачи"
    assert build_user_segment_requested_document_titles("source.mp4", segments) == ["Синк Tivali — задачи"]


def test_user_segment_empty_extra_field_too_many_fields_and_unsafe_titles_are_rejected() -> None:
    for text in [
        "Tivali | 00:00-end |   ",
        "Tivali | 00:00-end | Title | Extra",
        "Tivali | 00:00-end | Bad/Title",
        "Tivali | 00:00-end | Bad\\Title",
    ]:
        with pytest.raises(ValueError):
            parse_user_segment_plan(text, 60)


def test_user_segment_duplicate_labels_still_rejected_case_insensitively() -> None:
    with pytest.raises(ValueError, match="дублируется метка"):
        parse_user_segment_plan("Tivali | 00:00-00:30\ntivali | 00:30-end", 60)


def test_user_segment_duplicate_requested_titles_rejected_without_suffixes_and_allowed_with_suffixes() -> None:
    titles = ["Status meeting", "status MEETING"]
    with pytest.raises(ValueError, match="Используйте уникальные названия"):
        allocate_user_segment_document_titles(titles, [], False)
    assert allocate_user_segment_document_titles(titles, [], True) == ["Status meeting", "status MEETING (1)"]


def test_user_segment_title_allocator_handles_free_and_existing_collisions_deterministically() -> None:
    assert allocate_user_segment_document_titles(["Auto — A"], [], True) == ["Auto — A"]
    assert allocate_user_segment_document_titles(["Custom"], [], True) == ["Custom"]
    assert allocate_user_segment_document_titles(["Title"], ["Title"], True) == ["Title (1)"]
    assert allocate_user_segment_document_titles(["Title"], ["Title", "Title (1)"], True) == ["Title (2)"]
    assert allocate_user_segment_document_titles(["Title"], ["title"], True) == ["Title (1)"]
    assert allocate_user_segment_document_titles(["Status meeting", "Status meeting"], [], True) == ["Status meeting", "Status meeting (1)"]
    assert allocate_user_segment_document_titles(["Source — A", "Source — A"], [], True) == ["Source — A", "Source — A (1)"]


def test_user_segment_title_allocator_never_emits_copy_paths_timestamps_or_uuid_suffixes() -> None:
    allocated = allocate_user_segment_document_titles(["Status meeting"], ["Status meeting"], True)[0]
    assert allocated == "Status meeting (1)"
    forbidden = ["copy", "копия", "/", "\\", "2026-06-25", "00000000-0000-0000-0000-000000000000"]
    assert all(token not in allocated.casefold() for token in forbidden)


def test_user_segment_preview_shows_requested_final_or_conflict_mode_without_sensitive_values() -> None:
    segments = parse_user_segment_plan("Tivali | 00:00-end | Синк Tivali — задачи", 60)
    requested = build_user_segment_requested_document_titles("source.mp4", segments)
    titled = apply_user_segment_document_titles(segments, requested, ["Синк Tivali — задачи (1)"])
    enabled = build_user_segment_preview_text(titled, suffix_allocation_enabled=True, conflict_mode="skip")
    assert "Название документа: Синк Tivali — задачи" in enabled
    assert "Итоговое название документа: Синк Tivali — задачи (1)" in enabled
    disabled = build_user_segment_preview_text(titled, suffix_allocation_enabled=False, conflict_mode="skip")
    assert "Конфликт имён: используется общий режим «skip»" in disabled
    for unsafe in ["/tmp/", "https://", "drive.google.com", "Bearer", "api_key", "raw response"]:
        assert unsafe not in enabled


def test_user_segment_manifest_identity_ignores_requested_title_and_suffix_policy() -> None:
    base_kwargs = dict(
        original_source_signature="source-sig",
        original_source_name="source.mp4",
        segment_label="Tivali",
        start_label="00:00",
        end_label="end",
        source_mode="drive_file",
        source_reference="drive-id",
    )
    assert build_user_segment_source_signature(**base_kwargs) == build_user_segment_source_signature(**base_kwargs)


def test_existing_segment_doc_standardization_preserves_actual_drive_title_and_metadata() -> None:
    writes = []
    doc = {"id": "doc-1", "name": "Синк Tivali — задачи (1)", "display_name": "Синк Tivali — задачи (1)", "webViewLink": "link", "createdTime": "2026-06-01T00:00:00Z"}
    original_collect = standardize_existing_google_docs_in_folder.__globals__["collect_existing_google_docs_for_standardization"]
    original_extract = standardize_existing_google_docs_in_folder.__globals__["extract_google_doc_plain_text"]
    original_write = standardize_existing_google_docs_in_folder.__globals__["write_title_and_text_to_doc"]
    standardize_existing_google_docs_in_folder.__globals__["collect_existing_google_docs_for_standardization"] = lambda *_args, **_kwargs: ([doc], {"folders_seen": 0, "skipped_non_google_docs": 0, "errors": []})
    standardize_existing_google_docs_in_folder.__globals__["extract_google_doc_plain_text"] = lambda _doc_id: (
        "Old heading\n\nTranscript metadata\n"
        "Source file: Синк Tivali 21.06.2026 (2) — Tivali\n"
        "Source mode: Google Drive: 1 файл\nProvider: ElevenLabs\nModel: scribe_v2\nLanguage: Русский\nSpeakers: no\nCreated at: unknown\n"
        "Segment project: Tivali\nSegment time range: 00:00-end\nOriginal source: Синк Tivali 21.06.2026 (2).mp4\n\nTranscript\n\nBody"
    )
    standardize_existing_google_docs_in_folder.__globals__["write_title_and_text_to_doc"] = lambda **kwargs: writes.append(kwargs)
    try:
        report = standardize_existing_google_docs_in_folder("root", dry_run=False)
    finally:
        standardize_existing_google_docs_in_folder.__globals__["collect_existing_google_docs_for_standardization"] = original_collect
        standardize_existing_google_docs_in_folder.__globals__["extract_google_doc_plain_text"] = original_extract
        standardize_existing_google_docs_in_folder.__globals__["write_title_and_text_to_doc"] = original_write
    assert report["standardized"][0]["doc_name"] == "Синк Tivali — задачи (1)"
    assert len(writes) == 1
    assert writes[0]["title"] == "Синк Tivali — задачи (1)"
    text = writes[0]["transcript_text"]
    assert text.startswith("Синк Tivali — задачи (1)\n\nМетаданные транскрипта")
    assert "Segment project: Tivali" in text
    assert "Segment time range: 00:00-end" in text
    assert "Original source: Синк Tivali 21.06.2026 (2).mp4" in text
    assert "Created at:" not in text
