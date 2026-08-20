"""백그라운드 작업 실행기.

변환 작업은 오래 걸리므로 별도 스레드에서 돌리고,
진행 상황은 큐를 통해 UI 스레드로 전달해 화면이 멈추지 않도록 한다.
"""

from __future__ import annotations

import queue
import threading
import traceback


class Emitter:
    """작업 스레드가 UI 로 진행 상황을 보낼 때 사용하는 통로."""

    def __init__(self, event_queue: "queue.Queue", cancel_event: threading.Event):
        self._q = event_queue
        self._cancel = cancel_event

    # -- 진행 상황 전달 ---------------------------------------------
    def log(self, message, level="info"):
        self._q.put({"type": "log", "message": str(message), "level": level})

    def status(self, message):
        self._q.put({"type": "status", "message": str(message)})

    def progress(self, value, maximum=1.0):
        maximum = maximum or 1.0
        self._q.put({"type": "progress", "fraction": max(0.0, min(1.0, value / maximum))})

    def pulse(self, active=True):
        self._q.put({"type": "pulse", "active": bool(active)})

    # -- 취소 --------------------------------------------------------
    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def raise_if_cancelled(self):
        if self.cancelled:
            raise JobCancelled()


class JobCancelled(Exception):
    """사용자가 중지를 눌렀을 때 발생."""


class JobRunner:
    """위젯에 붙어서 스레드 실행 + 이벤트 폴링을 담당한다."""

    POLL_MS = 80

    def __init__(self, widget):
        self.widget = widget
        self.queue: "queue.Queue" = queue.Queue()
        self.thread: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self._on_event = None
        self._on_finish = None
        self._poll_id = None

    @property
    def is_running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, target, params, on_event, on_finish):
        """target(params, emitter) 를 스레드로 실행한다. 반환값은 on_finish 로 전달."""
        if self.is_running:
            return False
        self.cancel_event.clear()
        self._on_event = on_event
        self._on_finish = on_finish
        emitter = Emitter(self.queue, self.cancel_event)

        def wrapper():
            try:
                summary = target(params, emitter)
                self.queue.put({"type": "finish", "summary": summary or {}})
            except JobCancelled:
                self.queue.put({"type": "finish", "summary": {"cancelled": True}})
            except Exception as exc:  # noqa: BLE001 - 작업 실패는 UI 로 보고
                self.queue.put({
                    "type": "finish",
                    "summary": {"error": str(exc), "traceback": traceback.format_exc()},
                })

        self.thread = threading.Thread(target=wrapper, daemon=True)
        self.thread.start()
        self._poll()
        return True

    def cancel(self):
        self.cancel_event.set()

    def _poll(self):
        finished_summary = None
        try:
            while True:
                event = self.queue.get_nowait()
                if event.get("type") == "finish":
                    finished_summary = event.get("summary", {})
                elif self._on_event:
                    self._on_event(event)
        except queue.Empty:
            pass

        if finished_summary is not None:
            callback = self._on_finish
            self._on_finish = None
            self._poll_id = None
            if callback:
                callback(finished_summary)
            return

        self._poll_id = self.widget.after(self.POLL_MS, self._poll)
