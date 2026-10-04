"""
android_usb package
USB Host drivers and transport for Qualcomm EDL under Android.
"""

from .models import (
    UsbDeviceInfo,
    UsbInterfaceInfo,
    UsbEndpointInfo,
    DeviceMode,
    DeviceChipsetInfo,
    StorageInfo,
    PartitionEntry,
)
from .backend import UsbBackendInterface
from .backend_android import AndroidUsbBackend, is_android_environment
from .transport import AndroidUsbTransport

__all__ = [
    "UsbDeviceInfo",
    "UsbInterfaceInfo",
    "UsbEndpointInfo",
    "DeviceMode",
    "DeviceChipsetInfo",
    "StorageInfo",
    "PartitionEntry",
    "UsbBackendInterface",
    "AndroidUsbBackend",
    "AndroidUsbTransport",
    "is_android_environment",
]
