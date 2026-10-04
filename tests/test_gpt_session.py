#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests.test_gpt_session
Unit tests for GPT partition manager, sector arithmetic, and entry structures.
"""

from android_usb.models import PartitionEntry
from core.session import PartitionManager


def test_partition_entry_calculations():
    # 512-byte sector test
    p_boot = PartitionEntry(
        lun=0,
        name="boot",
        start_sector=2048,
        end_sector=133119,  # 131072 sectors = 64 MB
        sector_count=131072,
        sector_size=512,
    )
    assert p_boot.size_bytes == 64 * 1024 * 1024
    assert p_boot.size_formatted == "64.00 MB"

    # 4096-byte UFS sector test
    p_super = PartitionEntry(
        lun=0,
        name="super",
        start_sector=1000,
        end_sector=1049575,  # 1048576 sectors = 4 GB
        sector_count=1048576,
        sector_size=4096,
    )
    assert p_super.size_bytes == 4 * 1024 * 1024 * 1024
    assert p_super.size_formatted == "4.00 GB"


def test_partition_manager_operations():
    pm = PartitionManager()
    p1 = PartitionEntry(lun=0, name="boot", start_sector=100, end_sector=200, sector_count=101)
    p2 = PartitionEntry(lun=0, name="system", start_sector=201, end_sector=1000, sector_count=800)
    p3 = PartitionEntry(lun=1, name="xbl", start_sector=0, end_sector=100, sector_count=101)

    pm.set_partitions([p1, p2, p3])

    assert len(pm.all()) == 3
    assert pm.get_by_name("BOOT") == p1
    assert pm.get_by_name("system") == p2
    assert pm.get_by_name("nonexistent") is None

    lun0_parts = pm.get_by_lun(0)
    assert len(lun0_parts) == 2
    assert p3 not in lun0_parts

    pm.clear()
    assert len(pm.all()) == 0
