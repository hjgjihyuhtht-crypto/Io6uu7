#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
android_usb.backend
Abstract base backend for Android USB Host operations.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Callable, Any
from .models import UsbDeviceInfo


class UsbBackendInterface(ABC):
    """Abstract interface defining the USB Host lifecycle."""

    @abstractmethod
    def list_devices(self) -> List[UsbDeviceInfo]:
        """List all connected USB devices."""
        pass

    @abstractmethod
    def find_edl_devices(self) -> List[UsbDeviceInfo]:
        """Find Qualcomm EDL 9008 devices (VID 0x05C6, PID 0x9008)."""
        pass

    @abstractmethod
    def has_permission(self, device: UsbDeviceInfo) -> bool:
        """Check if USB Host permission is granted for device."""
        pass

    @abstractmethod
    def request_permission(
        self,
        device: UsbDeviceInfo,
        callback: Optional[Callable[[bool], None]] = None,
    ) -> bool:
        """
        Request USB Host permission from Android system.
        If callback is provided, it is invoked when the user accepts or declines.
        """
        pass

    @abstractmethod
    def open_device(self, device: UsbDeviceInfo) -> Any:
        """
        Open USB device connection and return a handle.
        Raises RuntimeError on failure.
        """
        pass

    @abstractmethod
    def close_device(self, connection: Any) -> None:
        """Close open USB device connection."""
        pass
