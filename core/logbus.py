#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.logbus
Thread-safe centralized logging and event distribution bus for Qualcomm EDL Suite.
"""

import os
import sys
import time
import threading
from typing import List, Callable, Optional


class LogEntry:
    def __init__(self, category: str, message: str, level: str = "INFO"):
        self.timestamp = time.strftime("%H:%M:%S")
        self.category = category.upper()
        self.message = str(message)
        self.level = level.upper()

    def format(self) -> str:
        return f"[{self.timestamp}] [{self.category}] {self.message}"

    def __str__(self) -> str:
        return self.format()


class LogBus:
    """Singleton log bus for broadcasting operations to UI, files, and console."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(LogBus, cls).__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._listeners: List[Callable[[LogEntry], None]] = []
        self._history: List[LogEntry] = []
        self._max_history = 5000
        self._listener_lock = threading.Lock()

    def subscribe(self, callback: Callable[[LogEntry], None]):
        """Register a callback for new log events."""
        with self._listener_lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def unsubscribe(self, callback: Callable[[LogEntry], None]):
        """Remove a previously registered callback."""
        with self._listener_lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def log(self, category: str, message: str, level: str = "INFO"):
        """Emit a log message."""
        entry = LogEntry(category, message, level)
        with self._listener_lock:
            self._history.append(entry)
            if len(self._history) > self._max_history:
                self._history.pop(0)
            listeners_copy = list(self._listeners)

        # Print to stderr/stdout for development terminal
        prefix = f"[{entry.category}]"
        print(f"{prefix} {entry.message}", flush=True)

        for callback in listeners_copy:
            try:
                callback(entry)
            except Exception as e:
                print(f"[LOGBUS ERROR] listener error: {e}", file=sys.stderr)

    def usb(self, message: str):
        self.log("USB", message)

    def sahara(self, message: str):
        self.log("SAHARA", message)

    def firehose(self, message: str):
        self.log("FIREHOSE", message)

    def gpt(self, message: str):
        self.log("GPT", message)

    def read(self, message: str):
        self.log("READ", message)

    def write(self, message: str):
        self.log("WRITE", message)

    def error(self, message: str):
        self.log("ERROR", message, level="ERROR")

    def session(self, message: str):
        self.log("SESSION", message)

    def get_history(self) -> List[LogEntry]:
        """Return all stored log entries."""
        with self._listener_lock:
            return list(self._history)

    def clear(self):
        """Clear log history."""
        with self._listener_lock:
            self._history.clear()

    def export_to_file(self, filepath: str) -> bool:
        """Write entire log history to disk."""
        try:
            dirname = os.path.dirname(filepath)
            if dirname and not os.path.exists(dirname):
                os.makedirs(dirname, exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                with self._listener_lock:
                    for entry in self._history:
                        f.write(entry.format() + "\n")
            return True
        except Exception as e:
            self.error(f"Failed to export logs: {e}")
            return False


# Global logbus instance
logbus = LogBus()
