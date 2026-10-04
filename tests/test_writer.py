#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests.test_writer
Unit tests for PartitionWriter validation, critical safety gates, and chunked write.
"""

import os
import pytest
from unittest.mock import MagicMock
from android_usb.models import PartitionEntry
from core.writer import PartitionWriter, CRITICAL_PARTITIONS
from core.session import EDLSession
from tests.fake_backend import FakeAndroidUsbBackend


def test_writer_image_validation_missing_file():
    session = EDLSession()
    writer = PartitionWriter(session)
    part = PartitionEntry(lun=0, name="boot", start_sector=0, end_sector=100, sector_count=101)

    val = writer.validate_image("/nonexistent/image.img", part)
    assert val.is_valid is False
    assert "não foi encontrado" in val.error


def test_writer_image_validation_exceeding_capacity(tmp_path):
    session = EDLSession()
    writer = PartitionWriter(session)

    # 1 MB test image
    img_file = str(tmp_path / "oversized.img")
    with open(img_file, "wb") as f:
        f.write(b"\x00" * (1024 * 1024))

    # Partition with only 10 sectors (5120 bytes)
    part = PartitionEntry(lun=0, name="splash", start_sector=0, end_sector=9, sector_count=10, sector_size=512)

    val = writer.validate_image(img_file, part)
    assert val.is_valid is False
    assert "excede a capacidade" in val.error


def test_writer_critical_partition_safety_gates(tmp_path):
    session = EDLSession()
    writer = PartitionWriter(session)

    img_file = str(tmp_path / "xbl.img")
    with open(img_file, "wb") as f:
        f.write(b"\x00" * 4096)

    crit_part = PartitionEntry(lun=1, name="xbl_a", start_sector=0, end_sector=100, sector_count=101, sector_size=512)

    val = writer.validate_image(img_file, crit_part)
    assert val.is_valid is True
    assert val.is_critical is True

    # Without confirmation -> raises PermissionError
    with pytest.raises(PermissionError):
        writer.write_partition(img_file, crit_part, user_confirmed=False)

    # Without extra critical confirmation -> raises PermissionError
    with pytest.raises(PermissionError) as exc_info:
        writer.write_partition(img_file, crit_part, user_confirmed=True, extra_critical_confirmed=False)
    assert "crítica" in str(exc_info.value).lower()


def test_writer_chunked_program_success(tmp_path):
    backend = FakeAndroidUsbBackend(permission_granted=True, device_connected=True)
    session = EDLSession(backend=backend)

    mock_fh_client = MagicMock()
    mock_fh = MagicMock()
    mock_fh.cfg.SECTOR_SIZE_IN_BYTES = 512
    mock_fh.cfg.MaxPayloadSizeToTargetInBytes = 1024
    mock_fh.cmd_program_buffer.return_value = True
    mock_fh_client.firehose = mock_fh
    session.firehose_client_instance = mock_fh_client

    img_file = str(tmp_path / "recovery.img")
    with open(img_file, "wb") as f:
        f.write(b"R" * 2048)  # 4 sectors

    part = PartitionEntry(lun=0, name="recovery", start_sector=50, end_sector=100, sector_count=51, sector_size=512)

    writer = PartitionWriter(session)
    updates = []

    ok = writer.write_partition(
        image_path=img_file,
        partition=part,
        user_confirmed=True,
        extra_critical_confirmed=False,
        progress_callback=lambda p: updates.append(p),
    )

    assert ok is True
    assert mock_fh.cmd_program_buffer.call_count > 0
    assert len(updates) > 0
    assert updates[-1].is_complete is True


def test_writer_reset_on_finish(tmp_path):
    backend = FakeAndroidUsbBackend(permission_granted=True, device_connected=True)
    session = EDLSession(backend=backend)

    mock_fh_client = MagicMock()
    mock_fh = MagicMock()
    mock_fh.cfg.SECTOR_SIZE_IN_BYTES = 512
    mock_fh.cfg.MaxPayloadSizeToTargetInBytes = 1024
    mock_fh.cmd_program_buffer.return_value = True
    mock_fh_client.firehose = mock_fh
    session.firehose_client_instance = mock_fh_client

    img_file = str(tmp_path / "boot.img")
    with open(img_file, "wb") as f:
        f.write(b"B" * 512)

    part = PartitionEntry(lun=0, name="boot", start_sector=0, end_sector=10, sector_count=11, sector_size=512)
    writer = PartitionWriter(session)

    ok = writer.write_partition(
        image_path=img_file,
        partition=part,
        user_confirmed=True,
        reset_on_finish=True,
    )
    assert ok is True
    assert mock_fh.cmd_reset.call_count == 1

