#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
android_usb.models
Data structures for Android USB Host communication and EDL device representation.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any


class DeviceMode(Enum):
    DISCONNECTED = "DISCONNECTED"
    EDL_DETECTED = "EDL_DETECTED"
    SAHARA = "SAHARA"
    FIREHOSE = "FIREHOSE"
    ERROR = "ERROR"


@dataclass
class UsbEndpointInfo:
    address: int
    direction: int  # 0=OUT, 128=IN
    attributes: int  # 2=BULK
    max_packet_size: int
    interval: int = 0


@dataclass
class UsbInterfaceInfo:
    id: int
    alternate_setting: int = 0
    interface_class: int = 255  # 0xFF Vendor Specific
    interface_subclass: int = 255
    interface_protocol: int = 255
    endpoints: List[UsbEndpointInfo] = field(default_factory=list)


@dataclass
class UsbDeviceInfo:
    device_name: str
    vendor_id: int
    product_id: int
    device_class: int = 0
    device_subclass: int = 0
    device_protocol: int = 0
    serial_number: Optional[str] = None
    manufacturer: Optional[str] = None
    product_name: Optional[str] = None
    interfaces: List[UsbInterfaceInfo] = field(default_factory=list)
    has_permission: bool = False
    raw_device: Any = None  # Reference to Android UsbDevice or mock

    @property
    def is_qualcomm_edl(self) -> bool:
        """VID 0x05C6 and PID 0x9008 is Qualcomm Emergency Download Mode."""
        return self.vendor_id == 0x05C6 and self.product_id == 0x9008

    @property
    def id_str(self) -> str:
        return f"{self.vendor_id:04x}:{self.product_id:04x}"


@dataclass
class DeviceChipsetInfo:
    msm_id: Optional[int] = None
    msm_name: Optional[str] = None
    hw_id: Optional[str] = None
    oem_id: Optional[int] = None
    model_id: Optional[int] = None
    pk_hash: Optional[str] = None
    serial: Optional[int] = None
    sahara_version: Optional[float] = None
    mode: Optional[str] = None


@dataclass
class StorageInfo:
    storage_type: str = "Unknown"  # UFS or eMMC
    sector_size: int = 512
    block_size: int = 512
    total_sectors: int = 0
    total_size_bytes: int = 0
    num_luns: int = 1
    lun_sizes: Dict[int, int] = field(default_factory=dict)
    manufacturer: Optional[str] = None
    product_name: Optional[str] = None
    serial: Optional[str] = None
    firmware_version: Optional[str] = None


@dataclass
class PartitionEntry:
    lun: int
    name: str
    start_sector: int
    end_sector: int
    sector_count: int
    sector_size: int = 512
    type_guid: str = ""
    unique_guid: str = ""
    flags: int = 0

    @property
    def size_bytes(self) -> int:
        return self.sector_count * self.sector_size

    @property
    def size_formatted(self) -> str:
        size = self.size_bytes
        if size >= 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024 * 1024):.2f} GB"
        if size >= 1024 * 1024:
            return f"{size / (1024 * 1024):.2f} MB"
        if size >= 1024:
            return f"{size / 1024:.2f} KB"
        return f"{size} B"
