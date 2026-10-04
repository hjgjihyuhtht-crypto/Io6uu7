#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests.test_session
Unit tests for EDLSession master controller state machine and lifecycle.
"""

from tests.fake_backend import FakeAndroidUsbBackend, make_fake_sahara_hello_pkt
from core.session import EDLSession
from android_usb.models import DeviceMode


def test_session_lifecycle_detect():
    backend = FakeAndroidUsbBackend(permission_granted=True, device_connected=True)
    session = EDLSession(backend=backend)

    # Initial state
    assert session.mode == DeviceMode.DISCONNECTED

    # Detect
    dev = session.detect_device()
    assert dev is not None
    assert session.mode == DeviceMode.EDL_DETECTED
    assert session.current_device is not None


def test_session_open_usb():
    backend = FakeAndroidUsbBackend(permission_granted=True, device_connected=True)
    session = EDLSession(backend=backend)
    session.detect_device()

    transport = session.open_usb()
    assert transport is not None
    assert transport.connected is True
    assert backend.active_connection is not None
    assert len(backend.active_connection.claimed_interfaces) > 0


def test_session_sahara_handshake():
    backend = FakeAndroidUsbBackend(permission_granted=True, device_connected=True)
    session = EDLSession(backend=backend)
    session.detect_device()
    session.open_usb()

    # Preload fake Sahara hello packet into mock connection
    hello_pkt = make_fake_sahara_hello_pkt(version=2)
    backend.active_connection.queue_incoming_data(hello_pkt)

    ok = session.run_sahara_handshake()
    assert ok is True
    assert session.chipset_info.sahara_version == 2


def test_session_disconnect():
    backend = FakeAndroidUsbBackend(permission_granted=True, device_connected=True)
    session = EDLSession(backend=backend)
    session.detect_device()
    session.open_usb()

    session.disconnect()
    assert session.mode == DeviceMode.DISCONNECTED
    assert session.transport is None
    assert session.is_connected is False


def test_session_detect_not_found():
    backend = FakeAndroidUsbBackend(permission_granted=True, device_connected=False)
    session = EDLSession(backend=backend)
    dev = session.detect_device()
    assert dev is None
    assert session.mode == DeviceMode.DISCONNECTED


def test_session_open_without_permission():
    import pytest
    backend = FakeAndroidUsbBackend(permission_granted=False, device_connected=True)
    session = EDLSession(backend=backend)
    session.detect_device()
    with pytest.raises(PermissionError):
        session.open_usb()

