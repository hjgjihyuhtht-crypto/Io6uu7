#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests.test_usb_check
Unit tests for USB device enumeration, EDL VID/PID matching, and permission flows.
"""

from tests.fake_backend import FakeAndroidUsbBackend
from core.usb_test import run_usb_diagnostics
from android_usb.models import UsbDeviceInfo


def test_edl_detection_success():
    backend = FakeAndroidUsbBackend(permission_granted=True, device_connected=True)
    edl_devs = backend.find_edl_devices()
    assert len(edl_devs) == 1
    assert edl_devs[0].vendor_id == 0x05C6
    assert edl_devs[0].product_id == 0x9008
    assert edl_devs[0].is_qualcomm_edl is True


def test_edl_detection_disconnected():
    backend = FakeAndroidUsbBackend(permission_granted=True, device_connected=False)
    edl_devs = backend.find_edl_devices()
    assert len(edl_devs) == 0


def test_permission_request():
    backend = FakeAndroidUsbBackend(permission_granted=False, device_connected=True)
    dev = backend.find_edl_devices()[0]
    assert backend.has_permission(dev) is False

    cb_called = []
    backend.request_permission(dev, callback=lambda granted: cb_called.append(granted))
    assert len(cb_called) == 1
    assert cb_called[0] is True
    assert backend.has_permission(dev) is True


def test_diagnostics_runner():
    backend = FakeAndroidUsbBackend(permission_granted=True, device_connected=True)
    ok, msg, devs = run_usb_diagnostics(backend)
    assert ok is True
    assert len(devs) == 1
    assert "05c6:9008" in msg.lower()
