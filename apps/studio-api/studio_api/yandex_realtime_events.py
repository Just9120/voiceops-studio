"""Browser-safe indexed realtime events; never guess missing provider timing."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass


@dataclass
class FinalState:
    start: float | None = None
    end: float | None = None
    refined: bool = False


class YandexRealtimeEvents:
    def __init__(self):
        self.finals: OrderedDict[int, FinalState] = OrderedDict()

    def event(self, response) -> dict | None:
        kind = response.WhichOneof("Event")
        if kind not in {"partial", "final", "final_refinement"}:
            return None
        update = (response.final_refinement.normalized_text
                  if kind == "final_refinement" else getattr(response, kind))
        if not update.alternatives:
            return None
        alternative = update.alternatives[0]
        text = alternative.text.strip()
        if not text:
            return None
        words = self._words(alternative)
        word_payload = {"words": words} if words else {}
        if kind == "partial":
            return {"message_type": "partial_transcript", "text": text, **word_payload}
        # An absent message decodes to final_index=0 in proto3. Do not invent
        # an identity that would replace unrelated finals in the browser.
        if kind == "final" and not response.HasField("audio_cursors"):
            payload = {"message_type": "committed_transcript", "text": text, **word_payload}
            start, end = alternative.start_time_ms, alternative.end_time_ms
            if 0 <= start < end <= 604800000:
                payload.update(start_seconds=start / 1000, end_seconds=end / 1000)
            return payload
        # A refinement refers to the provider's final_index, not the most recent
        # final or partial. Delayed corrections may arrive in a different order.
        index = (response.final_refinement.final_index if kind == "final_refinement"
                 else response.audio_cursors.final_index)
        if not 0 <= index <= 2_147_483_647:
            return None
        state = self.finals.get(index, FinalState())
        if kind == "final" and state.refined:
            return None
        start, end = alternative.start_time_ms, alternative.end_time_ms
        if 0 <= start < end <= 604800000:
            state.start, state.end = start / 1000, end / 1000
        if kind == "final_refinement":
            state.refined = True
        self.finals[index] = state
        self.finals.move_to_end(index)
        if len(self.finals) > 5000:
            self.finals.popitem(last=False)
        payload = {"message_type": "committed_transcript", "text": text, "final_index": index, **word_payload}
        if state.start is not None and state.end is not None:
            payload.update(start_seconds=state.start, end_seconds=state.end)
        return payload

    @staticmethod
    def _words(alternative):
        if not alternative.words or len(alternative.words) > 20000:
            return None
        result, total = [], 0
        for word in alternative.words:
            start, end, text = word.start_time_ms, word.end_time_ms, word.text
            if (not text or len(text) > 20000 or not 0 <= start <= end <= 604800000
                or result and start / 1000 < result[-1]["start"]):
                return None
            total += len(text)
            if total > 500000:
                return None
            result.append({"text": text, "start": start / 1000, "end": end / 1000, "type": "word"})
        return result
