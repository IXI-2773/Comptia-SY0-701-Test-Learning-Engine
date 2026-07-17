import queue
import threading
from collections.abc import Callable
from typing import Any, TypedDict


class SmartPracticeSignalSnapshot(TypedDict):
    generation: int
    key: object
    revision: object
    payload: dict[str, Any]


class SmartPracticePrewarmService:
    def __init__(self, root, publish: Callable[[SmartPracticeSignalSnapshot], None], debounce_ms: int = 140) -> None:
        self.root = root
        self.publish = publish
        self.debounce_ms = debounce_ms
        self.generation = 0
        self._scheduled_id = None
        self._active = False
        self._pending: tuple[int, tuple[object, object | None], Callable[[], dict[str, Any]]] | None = None
        self._results: queue.Queue[tuple[int, object, object | None, dict[str, Any] | None, Exception | None]] = (
            queue.Queue()
        )
        self._closed = False
        self._poll_id = self.root.after(50, self._poll_results)

    def schedule(
        self,
        key: object,
        build: Callable[[], dict[str, Any]],
        *,
        revision: object | None = None,
        delay_ms: int | None = None,
    ) -> int:
        self.generation += 1
        generation = self.generation
        self._pending = (generation, (key, revision), build)
        if self._scheduled_id is not None:
            try:
                self.root.after_cancel(self._scheduled_id)
            except Exception:
                pass
        delay = self.debounce_ms if delay_ms is None else max(0, int(delay_ms))
        self._scheduled_id = self.root.after(delay, self._launch_pending)
        return generation

    def invalidate(self) -> None:
        self.generation += 1
        self._pending = None
        if self._scheduled_id is not None:
            try:
                self.root.after_cancel(self._scheduled_id)
            except Exception:
                pass
            self._scheduled_id = None

    def close(self) -> None:
        self._closed = True
        self.invalidate()
        if self._poll_id is not None:
            try:
                self.root.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None

    def _launch_pending(self) -> None:
        self._scheduled_id = None
        if self._closed or self._pending is None:
            return
        if self._active:
            return
        generation, payload_meta, build = self._pending
        self._pending = None
        self._active = True
        key, revision = payload_meta

        def worker() -> None:
            try:
                self._results.put((generation, key, revision, build(), None))
            except Exception as exc:
                self._results.put((generation, key, revision, None, exc))

        threading.Thread(target=worker, daemon=True, name="smart-practice-prewarm").start()

    def _poll_results(self) -> None:
        while True:
            try:
                generation, key, revision, payload, error = self._results.get_nowait()
            except queue.Empty:
                break
            self._active = False
            if error is None and payload is not None and generation == self.generation:
                self.publish({"generation": generation, "key": key, "revision": revision, "payload": payload})
            if self._pending is not None and self._scheduled_id is None:
                self._scheduled_id = self.root.after(0, self._launch_pending)
        if not self._closed:
            self._poll_id = self.root.after(50, self._poll_results)
