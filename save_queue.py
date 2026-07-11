from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class DeferredTask:
    callback: Callable[[], Any]
    after_id: str | None


class DeferredSaveQueue:
    def __init__(self, root):
        self.root = root
        self._tasks: dict[str, DeferredTask] = {}

    def pending(self, key: str) -> bool:
        return key in self._tasks

    def cancel(self, key: str) -> bool:
        task = self._tasks.pop(key, None)
        if task is None:
            return False
        if task.after_id:
            try:
                self.root.after_cancel(task.after_id)
            except Exception:
                pass
        return True

    def schedule(self, key: str, callback: Callable[[], Any], delay_ms: int = 250) -> None:
        self.cancel(key)
        after_id = self.root.after(delay_ms, lambda queue_key=key: self._run(queue_key))
        self._tasks[key] = DeferredTask(callback=callback, after_id=after_id)

    def _run(self, key: str) -> bool:
        task = self._tasks.pop(key, None)
        if task is None:
            return False
        task.callback()
        return True

    def flush(self, key: str) -> bool:
        task = self._tasks.get(key)
        if task is None:
            return False
        self.cancel(key)
        task.callback()
        return True

    def flush_all(self) -> None:
        for key in list(self._tasks):
            self.flush(key)
