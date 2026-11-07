"""Public Hugging Face ASR catalog, with an explicit Studio support boundary."""
from functools import lru_cache
import json
import re
from time import monotonic
from urllib.parse import parse_qs, urlsplit

import httpx

from .local_model_identity import MODEL_REVISIONS, NEMOTRON_MODEL, PARAKEET_MAX_DURATION_SECONDS, PARAKEET_MODEL

HUB_MODELS = "https://huggingface.co/api/models"
TASK = "automatic-speech-recognition"
PAGE_SIZE = 24
MAX_BODY = 1024 * 1024
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}(?:/[A-Za-z0-9][A-Za-z0-9_.-]{0,95})?")
CURSOR = re.compile(r"[A-Za-z0-9_+/=-]{1,1024}")
LANGUAGE = re.compile(r"[a-z]{2,3}")
STUDIO_PROFILES = {
    "nvidia/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B": {
        "profile": "nemotron-transcribe-iq4-nl", "revision": MODEL_REVISIONS[NEMOTRON_MODEL],
        "model": NEMOTRON_MODEL,
        "name": "Nemotron 3.5 Transcribe IQ4_NL", "languages": ["ru", "en"], "diarization": True,
        "word_timestamps": True, "download_bytes": 21349066752,
        "weights_repository": "AtomicChat/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B-GGUF",
        "max_audio_seconds": None,
    },
    "nvidia/parakeet-tdt-0.6b-v3": {
        "profile": "parakeet-tdt-v3-q8", "revision": MODEL_REVISIONS[PARAKEET_MODEL],
        "model": PARAKEET_MODEL,
        "name": "Parakeet TDT 0.6B v3 Q8", "languages": ["ru", "en"], "diarization": False,
        "word_timestamps": True, "download_bytes": 713975456,
        "weights_repository": "nvidia/parakeet-tdt-0.6b-v3",
        "max_audio_seconds": PARAKEET_MAX_DURATION_SECONDS,
    },
}


class CatalogUnavailable(Exception):
    pass


def _next_cursor(header):
    match = re.search(r'<([^>]+)>;\s*rel="next"', header[:8192])
    if match is None:
        return None
    try:
        link = urlsplit(match.group(1))
        values = parse_qs(link.query, max_num_fields=30).get("cursor", [])
    except ValueError:
        return None
    if (link.scheme, link.netloc, link.path) == ("https", "huggingface.co", "/api/models"):
        if len(values) == 1 and CURSOR.fullmatch(values[0]):
            return values[0]
    return None


def _model(row):
    if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not MODEL_ID.fullmatch(row["id"]):
        return None
    model_id = row["id"]
    tags = {tag for tag in row.get("tags", []) if isinstance(tag, str)} if isinstance(row.get("tags"), list) else set()
    pipeline = row.get("pipeline_tag")
    if row.get("private") is True or (pipeline != TASK and (pipeline is not None or TASK not in tags)):
        return None
    revision = row.get("sha")
    gated = row.get("gated")
    profile = STUDIO_PROFILES.get(model_id) or next(
        (item for item in STUDIO_PROFILES.values() if item["weights_repository"] == model_id), None,
    )
    license_id = next((tag.removeprefix("license:") for tag in sorted(tags)
                       if re.fullmatch(r"license:[a-z0-9][a-z0-9.-]{0,63}", tag)), None)
    return {
        "id": model_id,
        "source_url": "https://huggingface.co/" + model_id,
        "hub_revision": revision if isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{40}", revision) else None,
        "license": license_id if license_id != "other" else None,
        "access": "public" if gated is False else "gated" if gated is True or gated in ("auto", "manual") else "unknown",
        "languages": sorted(tag for tag in tags if LANGUAGE.fullmatch(tag))[:80],
        "downloads": row.get("downloads") if type(row.get("downloads")) is int else None,
        "likes": row.get("likes") if type(row.get("likes")) is int else None,
        "studio": {
            **profile,
            "weights_url": f"https://huggingface.co/{profile['weights_repository']}/tree/{profile['revision']}",
            "platform": "Windows x64",
            "execution": "CPU",
            "min_ram_bytes": None,
        } if profile else None,
    }


HUB_METADATA_FIELDS = ("tags", "sha", "downloads", "likes", "pipeline_tag", "gated", "private")


def _hub_json(url, params):
    deadline = monotonic() + 10
    try:
        with httpx.stream("GET", url, params=params, timeout=5, follow_redirects=False) as response:
            response.raise_for_status()
            raw = bytearray()
            for part in response.iter_bytes(chunk_size=16384):
                raw.extend(part)
                if len(raw) > MAX_BODY or monotonic() > deadline:
                    raise CatalogUnavailable()
            return json.loads(raw), response.headers.get("link", "")
    except (httpx.HTTPError, ValueError) as exc:
        raise CatalogUnavailable() from exc


@lru_cache(maxsize=128)
def _page(search, language, sort, cursor, cache_window):
    params = [("pipeline_tag", TASK), ("sort", sort), ("direction", "-1"), ("limit", str(PAGE_SIZE))]
    params.extend(("expand", field) for field in HUB_METADATA_FIELDS)
    params.extend((key, value) for key, value in (("search", search), ("filter", language), ("cursor", cursor)) if value)
    rows, links = _hub_json(HUB_MODELS, params)
    if not isinstance(rows, list) or len(rows) > PAGE_SIZE:
        raise CatalogUnavailable()
    return {"items": [item for row in rows if (item := _model(row)) is not None],
            "next_cursor": _next_cursor(links)}


@lru_cache(maxsize=32)
def _studio_profile_item(model_id, cache_window):
    profile = STUDIO_PROFILES[model_id]
    try:
        row, _ = _hub_json(f"{HUB_MODELS}/{profile['weights_repository']}",
                           [("expand", field) for field in HUB_METADATA_FIELDS])
        if isinstance(row, dict) and row.get("id") == profile["weights_repository"]:
            if row["id"] != model_id:
                row = {**row, "sha": None}
            item = _model({**row, "id": model_id})
            if item is not None:
                return item
    except CatalogUnavailable:
        pass  # The shipped profile remains usable; volatile Hub metadata is unknown.
    tags = ["license:cc-by-4.0"] if profile["model"] == PARAKEET_MODEL else []
    return _model({"id": model_id, "pipeline_tag": TASK, "tags": tags})


def catalog_page(*, search, language, sort, cursor, supported=False):
    if supported:
        keyword = search.casefold().strip()
        items = []
        for model_id, profile in STUDIO_PROFILES.items():
            if (not language or language in profile["languages"]) and keyword in (model_id + " " + profile["name"]).casefold():
                items.append(_studio_profile_item(model_id, int(monotonic() // 60)))
        items.sort(key=lambda item: (item[sort] is None, -(item[sort] or 0), item["id"].casefold()))
        return {"items": items, "next_cursor": None}
    return _page(search.strip(), language, sort, cursor, int(monotonic() // 60))
