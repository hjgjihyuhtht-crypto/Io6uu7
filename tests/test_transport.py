#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests.test_transport
Unit tests for AndroidUsbTransport CDC interface semantics and robustness.
"""

import pytest
from tests.fake_backend import FakeUsbDeviceConnection, FakeUsbEndpoint
from android_usb.transport import AndroidUsbTransport


def create_mock_transport():
    conn = FakeUsbDeviceConnection()
    ep_in = FakeUsbEndpoint(address=0x81, direction=128)
    ep_out = FakeUsbEndpoint(address=0x01, direction=0)
    transport = AndroidUsbTransport(
        connection=conn,
        interface=0,
        ep_in=ep_in,
        ep_out=ep_out,
        maxsize=1024,
    )
    return transport, conn


def test_transport_write_and_read():
    transport, conn = create_mock_transport()
    # Queue response in mock
    conn.queue_incoming_data(b"HELLO_EDL_DATA")

    # Test write
    written = transport.write(b"CMD_TEST")
    assert written == len(b"CMD_TEST")
    assert conn.written_buffers[-1] == b"CMD_TEST"

    # Test usbread
    data = transport.usbread(14)
    assert bytes(data) == b"HELLO_EDL_DATA"


def test_transport_usbreadwrite():
    transport, conn = create_mock_transport()
    conn.queue_incoming_data(b"RESPONSE_PAYLOAD")

    res = transport.usbreadwrite(b"PING", 16)
    assert bytes(res) == b"RESPONSE_PAYLOAD"
    assert conn.written_buffers[-1] == b"PING"


def test_transport_xmlread_mode():
    transport, conn = create_mock_transport()
    xml_data = b'<?xml version="1.0" ?><data><response value="ACK"/></data>'
    conn.queue_incoming_data(xml_data)

    transport.xmlread = True
    res = transport.usbread()
    assert b'<response value="ACK"/>' in res


def test_transport_disconnection_detection():
    transport, conn = create_mock_transport()
    disconnect_called = []
    transport.set_disconnect_callback(lambda reason: disconnect_called.append(reason))

    # Simulate connection error
    conn.fail_on_write = True
    with pytest.raises(ConnectionError):
        transport.write(b"FAIL_TEST")

    assert transport.connected is False
    assert len(disconnect_called) == 1
