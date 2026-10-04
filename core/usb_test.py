#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.usb_test
Diagnostic and validation routines for Android USB Host and Qualcomm EDL devices.
"""

from typing import Tuple, List, Optional
from android_usb.models import UsbDeviceInfo
from android_usb.backend import UsbBackendInterface
from android_usb.backend_android import AndroidUsbBackend, is_android_environment
from core.logbus import logbus


def run_usb_diagnostics(backend: Optional[UsbBackendInterface] = None) -> Tuple[bool, str, List[UsbDeviceInfo]]:
    """
    Run diagnostic checks on USB Host subsystem.
    Returns (success, summary_message, edl_devices_found).
    """
    if backend is None:
        if is_android_environment():
            backend = AndroidUsbBackend()
        else:
            logbus.usb("Diagnostic running in non-Android environment.")
            return False, "Non-Android environment. PyJNIus/Android UsbManager not active.", []

    try:
        logbus.usb("Scanning connected USB devices...")
        devices = backend.list_devices()
        logbus.usb(f"Found {len(devices)} total USB device(s).")

        edl_devices = backend.find_edl_devices()
        if not edl_devices:
            msg = "No Qualcomm EDL 9008 (05C6:9008) device detected. Ensure device is in EDL mode and OTG cable is connected."
            logbus.usb(msg)
            return False, msg, []

        target = edl_devices[0]
        has_perm = backend.has_permission(target)
        status_msg = f"Found EDL device {target.id_str} ({target.device_name}). Permission: {'Granted' if has_perm else 'Required'}."
        logbus.usb(status_msg)

        return True, status_msg, edl_devices

    except Exception as e:
        err = f"USB diagnostic check failed: {e}"
        logbus.error(err)
        return False, err, []
