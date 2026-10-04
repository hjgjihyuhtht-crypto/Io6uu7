#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
android_usb.backend_android
Android USB Host implementation using PyJNIus.
Guaranteed lazy-loading of Java classes to ensure seamless desktop testing.
Compatible with Android 10, 11, 12, 13, 14, 15, and 16+.
"""

import sys
import time
import logging
from typing import List, Optional, Callable, Dict, Any

from .backend import UsbBackendInterface
from .models import UsbDeviceInfo, UsbInterfaceInfo, UsbEndpointInfo

logger = logging.getLogger("android_usb")

# Flag indicating whether PyJNIus / Android runtime is available
_ANDROID_AVAILABLE: Optional[bool] = None

# JNI classes cache
_Context = None
_UsbManager = None
_UsbConstants = None
_Intent = None
_PendingIntent = None
_IntentFilter = None
_BroadcastReceiver = None
_PythonActivity = None


def is_android_environment() -> bool:
    """Check if running inside Android JVM environment."""
    global _ANDROID_AVAILABLE
    if _ANDROID_AVAILABLE is not None:
        return _ANDROID_AVAILABLE
    try:
        from jnius import autoclass
        # Test loading a fundamental Android class
        _ = autoclass('android.content.Context')
        _ANDROID_AVAILABLE = True
    except Exception:
        _ANDROID_AVAILABLE = False
    return _ANDROID_AVAILABLE


def _ensure_jnius():
    """Lazily load Android classes via PyJNIus."""
    global _Context, _UsbManager, _UsbConstants, _Intent, _PendingIntent
    global _IntentFilter, _BroadcastReceiver, _PythonActivity, _ANDROID_AVAILABLE

    if not is_android_environment():
        raise RuntimeError("Android USB backend can only run on Android devices with PyJNIus.")

    if _Context is None:
        from jnius import autoclass
        _Context = autoclass('android.content.Context')
        _UsbManager = autoclass('android.hardware.usb.UsbManager')
        _UsbConstants = autoclass('android.hardware.usb.UsbConstants')
        _Intent = autoclass('android.content.Intent')
        _PendingIntent = autoclass('android.app.PendingIntent')
        _IntentFilter = autoclass('android.content.IntentFilter')
        try:
            # Common Python on Android activity holders (Flet/Kivy/Chaquopy)
            _PythonActivity = autoclass('org.kivy.android.PythonActivity')
        except Exception:
            try:
                _PythonActivity = autoclass('org.flet.android.MainActivity')
            except Exception:
                try:
                    _PythonActivity = autoclass('android.app.ActivityThread').currentActivity()
                except Exception:
                    _PythonActivity = None


class AndroidUsbBackend(UsbBackendInterface):
    """
    Android USB Host Backend implementation interacting directly with
    Android's UsbManager through PyJNIus.
    """

    ACTION_USB_PERMISSION = "com.qualcomm.edl.USB_PERMISSION"

    def __init__(self, context=None):
        self._context = context
        self._usb_manager = None
        self._permission_callbacks: Dict[str, Callable[[bool], None]] = {}

    def _get_context(self):
        """Retrieve the active Android Application Context."""
        if self._context:
            return self._context
        _ensure_jnius()
        if _PythonActivity and hasattr(_PythonActivity, 'mActivity') and _PythonActivity.mActivity:
            self._context = _PythonActivity.mActivity
        elif _PythonActivity and hasattr(_PythonActivity, 'getApplicationContext'):
            self._context = _PythonActivity.getApplicationContext()
        else:
            try:
                activity_thread = _Context = autoclass('android.app.ActivityThread')
                app = activity_thread.currentApplication()
                if app:
                    self._context = app.getApplicationContext()
            except Exception as e:
                logger.error("Could not obtain Android Context: %s", e)
        if not self._context:
            raise RuntimeError("Android Context is not available. Ensure app is running inside Android UI thread.")
        return self._context

    def _get_manager(self):
        """Retrieve UsbManager system service."""
        if self._usb_manager is None:
            ctx = self._get_context()
            _ensure_jnius()
            self._usb_manager = ctx.getSystemService(_Context.USB_SERVICE)
        return self._usb_manager

    def list_devices(self) -> List[UsbDeviceInfo]:
        """Enumerate all connected USB devices using UsbManager.getDeviceList()."""
        if not is_android_environment():
            logger.warning("list_devices called outside Android environment.")
            return []

        manager = self._get_manager()
        device_map = manager.getDeviceList()  # java.util.HashMap<String, UsbDevice>
        devices: List[UsbDeviceInfo] = []

        if device_map is None:
            return devices

        iterator = device_map.values().iterator()
        while iterator.hasNext():
            dev = iterator.next()
            device_info = self._parse_usb_device(dev)
            devices.append(device_info)

        return devices

    def find_edl_devices(self) -> List[UsbDeviceInfo]:
        """Find Qualcomm EDL devices matching VID 0x05C6, PID 0x9008."""
        all_devs = self.list_devices()
        edl_devs = [d for d in all_devs if d.is_qualcomm_edl]
        return edl_devs

    def has_permission(self, device: UsbDeviceInfo) -> bool:
        """Check if permission is granted for the specific UsbDevice."""
        if not is_android_environment():
            return False
        if not device.raw_device:
            return False
        manager = self._get_manager()
        has_perm = manager.hasPermission(device.raw_device)
        device.has_permission = bool(has_perm)
        return device.has_permission

    def request_permission(
        self,
        device: UsbDeviceInfo,
        callback: Optional[Callable[[bool], None]] = None,
    ) -> bool:
        """
        Request USB Host permission via UsbManager.requestPermission().
        Uses PendingIntent with Android 12+ (SDK 31+) FLAG_MUTABLE compatibility.
        """
        if not is_android_environment():
            logger.warning("request_permission called outside Android.")
            if callback:
                callback(False)
            return False

        if not device.raw_device:
            logger.error("Cannot request permission: missing raw_device.")
            if callback:
                callback(False)
            return False

        if self.has_permission(device):
            if callback:
                callback(True)
            return True

        manager = self._get_manager()
        ctx = self._get_context()
        _ensure_jnius()

        intent = _Intent(self.ACTION_USB_PERMISSION)
        intent.setPackage(ctx.getPackageName())

        # Android 12+ (API 31+) requires FLAG_MUTABLE for USB permission result intent
        flags = 0
        try:
            flag_mutable = getattr(_PendingIntent, 'FLAG_MUTABLE', 0x02000000)
            flags |= flag_mutable
        except Exception:
            flags = 0

        pending_intent = _PendingIntent.getBroadcast(ctx, 0, intent, flags)

        if callback:
            self._permission_callbacks[device.device_name] = callback

        logger.info("Requesting USB permission for %s (%s)", device.device_name, device.id_str)
        manager.requestPermission(device.raw_device, pending_intent)

        # Wait briefly for permission prompt or response
        # A caller can also poll has_permission() or supply a callback
        return False

    def open_device(self, device: UsbDeviceInfo) -> Any:
        """
        Open USB device connection using UsbManager.openDevice(device).
        Returns UsbDeviceConnection.
        """
        if not is_android_environment():
            raise RuntimeError("Cannot open device outside Android environment.")

        if not device.raw_device:
            raise RuntimeError("Invalid USB device handle.")

        manager = self._get_manager()
        if not manager.hasPermission(device.raw_device):
            raise PermissionError(f"Permission not granted for USB device {device.id_str}")

        connection = manager.openDevice(device.raw_device)
        if connection is None:
            raise RuntimeError(f"UsbManager.openDevice() returned null for {device.id_str}")

        logger.info("Successfully opened UsbDeviceConnection for %s", device.id_str)
        return connection

    def close_device(self, connection: Any) -> None:
        """Close UsbDeviceConnection."""
        if connection is not None:
            try:
                connection.close()
                logger.info("UsbDeviceConnection closed.")
            except Exception as e:
                logger.warning("Error closing UsbDeviceConnection: %s", e)

    def _parse_usb_device(self, dev: Any) -> UsbDeviceInfo:
        """Convert native Android UsbDevice into UsbDeviceInfo model."""
        device_name = str(dev.getDeviceName())
        vid = int(dev.getVendorId())
        pid = int(dev.getProductId())
        dev_class = int(dev.getDeviceClass())
        dev_subclass = int(dev.getDeviceSubclass())
        dev_protocol = int(dev.getDeviceProtocol())

        interfaces: List[UsbInterfaceInfo] = []
        interface_count = int(dev.getInterfaceCount())

        for i in range(interface_count):
            iface = dev.getInterface(i)
            endpoints: List[UsbEndpointInfo] = []
            ep_count = int(iface.getEndpointCount())

            for ep_idx in range(ep_count):
                ep = iface.getEndpoint(ep_idx)
                ep_info = UsbEndpointInfo(
                    address=int(ep.getAddress()),
                    direction=int(ep.getDirection()),
                    attributes=int(ep.getAttributes()),
                    max_packet_size=int(ep.getMaxPacketSize()),
                    interval=int(ep.getInterval()),
                )
                endpoints.append(ep_info)

            iface_info = UsbInterfaceInfo(
                id=int(iface.getId()),
                alternate_setting=int(iface.getAlternateSetting()),
                interface_class=int(iface.getInterfaceClass()),
                interface_subclass=int(iface.getInterfaceSubclass()),
                interface_protocol=int(iface.getInterfaceProtocol()),
                endpoints=endpoints,
            )
            interfaces.append(iface_info)

        has_perm = False
        try:
            if self._usb_manager:
                has_perm = bool(self._usb_manager.hasPermission(dev))
        except Exception:
            pass

        return UsbDeviceInfo(
            device_name=device_name,
            vendor_id=vid,
            product_id=pid,
            device_class=dev_class,
            device_subclass=dev_subclass,
            device_protocol=dev_protocol,
            interfaces=interfaces,
            has_permission=has_perm,
            raw_device=dev,
        )
