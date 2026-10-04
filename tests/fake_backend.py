#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests.fake_backend
Mock Android USB Host environment for comprehensive unit testing without hardware.
Simulates UsbManager, UsbDeviceConnection, Sahara hello, and Firehose XML exchanges.
"""

from typing import List, Optional, Callable, Dict, Any
from struct import pack
from android_usb.models import UsbDeviceInfo, UsbInterfaceInfo, UsbEndpointInfo
from android_usb.backend import UsbBackendInterface


class FakeUsbEndpoint:
    def __init__(self, address: int, direction: int, max_packet_size: int = 1024):
        self.address = address
        self.direction = direction
        self.max_packet_size = max_packet_size


class FakeUsbDeviceConnection:
    """Simulates Android's UsbDeviceConnection."""

    def __init__(self):
        self.claimed_interfaces = []
        self.is_closed = False
        self.written_buffers: List[bytes] = []
        self.in_queue: bytearray = bytearray()
        self.fail_on_write = False
        self.fail_on_read = False

    def claimInterface(self, interface: Any, force: bool = True) -> bool:
        self.claimed_interfaces.append(interface)
        return True

    def releaseInterface(self, interface: Any) -> bool:
        if interface in self.claimed_interfaces:
            self.claimed_interfaces.remove(interface)
        return True

    def close(self):
        self.is_closed = True

    def queue_incoming_data(self, data: bytes):
        self.in_queue.extend(data)

    def bulkTransfer(self, endpoint: Any, buffer: Any, length: int, timeout: int) -> int:
        if self.is_closed:
            return -1

        addr = getattr(endpoint, "address", 0)
        direction = getattr(endpoint, "direction", 0)
        is_in = (addr & 0x80) != 0 or direction == 128

        if is_in:
            if self.fail_on_read:
                return -1
            if not self.in_queue:
                return 0
            take = min(length, len(self.in_queue))
            for i in range(take):
                buffer[i] = self.in_queue[i]
            self.in_queue = self.in_queue[take:]
            return take
        else:
            if self.fail_on_write:
                return -1
            data = bytes(buffer[:length]) if isinstance(buffer, (bytearray, list)) else bytes(buffer)
            self.written_buffers.append(data)
            return len(data)


class FakeAndroidUsbBackend(UsbBackendInterface):
    """Mock backend implementing UsbBackendInterface for tests."""

    def __init__(self, permission_granted: bool = True, device_connected: bool = True):
        self.permission_granted = permission_granted
        self.device_connected = device_connected
        self.active_connection: Optional[FakeUsbDeviceConnection] = None

    def create_fake_edl_device(self) -> UsbDeviceInfo:
        ep_in = UsbEndpointInfo(address=0x81, direction=128, attributes=2, max_packet_size=1024)
        ep_out = UsbEndpointInfo(address=0x01, direction=0, attributes=2, max_packet_size=1024)
        iface = UsbInterfaceInfo(id=0, endpoints=[ep_in, ep_out])
        dev = UsbDeviceInfo(
            device_name="/dev/bus/usb/001/002",
            vendor_id=0x05C6,
            product_id=0x9008,
            device_class=0,
            interfaces=[iface],
            has_permission=self.permission_granted,
        )
        return dev

    def list_devices(self) -> List[UsbDeviceInfo]:
        if not self.device_connected:
            return []
        return [self.create_fake_edl_device()]

    def find_edl_devices(self) -> List[UsbDeviceInfo]:
        if not self.device_connected:
            return []
        return [self.create_fake_edl_device()]

    def has_permission(self, device: UsbDeviceInfo) -> bool:
        return self.permission_granted

    def request_permission(
        self,
        device: UsbDeviceInfo,
        callback: Optional[Callable[[bool], None]] = None,
    ) -> bool:
        self.permission_granted = True
        device.has_permission = True
        if callback:
            callback(True)
        return True

    def open_device(self, device: UsbDeviceInfo) -> FakeUsbDeviceConnection:
        if not self.permission_granted:
            raise PermissionError("Permission not granted.")
        self.active_connection = FakeUsbDeviceConnection()
        return self.active_connection

    def close_device(self, connection: Any) -> None:
        if connection:
            connection.close()


def make_fake_sahara_hello_pkt(version: int = 2) -> bytes:
    """Build a standard Sahara hello request packet (cmd=1)."""
    # Sahara hello packet structure: cmd=0x01, len=0x30, version=2, comp_version=1, max_pkt=1024, mode=0
    return pack("<IIIIIIIIIIII", 1, 0x30, version, 1, 1024, 0, 0, 0, 0, 0, 0, 0)
