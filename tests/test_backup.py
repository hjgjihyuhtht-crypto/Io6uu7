#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests.test_backup
Unit tests for PartitionBackup streaming engine, chunk calculation, and cancellation.
"""

import os
import tempfile
from unittest.mock import MagicMock
from android_usb.models import PartitionEntry
from core.backup import PartitionBackup, BackupProgress
from core.session import EDLSession
from tests.fake_backend import FakeAndroidUsbBackend


def test_backup_progress_structure():
    prog = BackupProgress(
        current_partition="boot",
        bytes_done=1048576,
        bytes_total=4194304,
        percentage=25.0,
        speed_bytes_sec=1048576.0,
        speed_formatted="1.0 MB/s",
        eta_seconds=3.0,
        eta_formatted="3s",
        is_complete=False,
    )
    assert prog.percentage == 25.0
    assert prog.speed_formatted == "1.0 MB/s"
    assert prog.eta_formatted == "3s"


def test_backup_chunk_streaming(tmp_path):
    backend = FakeAndroidUsbBackend(permission_granted=True, device_connected=True)
    session = EDLSession(backend=backend)

    # Mock Firehose client & firehose
    mock_fh_client = MagicMock()
    mock_fh = MagicMock()
    mock_fh.cfg.SECTOR_SIZE_IN_BYTES = 512
    mock_fh_client.firehose = mock_fh
    session.firehose_client_instance = mock_fh_client
    session.transport = MagicMock()

    # Setup dummy read buffer responses
    fake_chunk_data = b"DUMMY_PARTITION_DATA_512_BYTES_" + b"0" * 480
    mock_resp = MagicMock()
    mock_resp.resp = True
    mock_resp.data = fake_chunk_data
    mock_fh.cmd_read_buffer.return_value = mock_resp

    backup_engine = PartitionBackup(session=session, chunk_size_bytes=512)

    partition = PartitionEntry(
        lun=0,
        name="test_part",
        start_sector=10,
        end_sector=13,  # 4 sectors = 2048 bytes
        sector_count=4,
        sector_size=512,
    )

    out_file = str(tmp_path / "test_part.img")
    progress_updates = []

    success = backup_engine.backup_partition(
        partition=partition,
        output_file_path=out_file,
        progress_callback=lambda p: progress_updates.append(p),
    )

    assert success is True
    assert os.path.exists(out_file)
    assert os.path.getsize(out_file) == 4 * len(fake_chunk_data)
    assert len(progress_updates) > 0
    assert progress_updates[-1].is_complete is True


def test_backup_cooperative_cancel():
    backend = FakeAndroidUsbBackend(permission_granted=True, device_connected=True)
    session = EDLSession(backend=backend)
    backup_engine = PartitionBackup(session=session)

    assert backup_engine._abort_requested is False
    backup_engine.request_cancel()
    assert backup_engine._abort_requested is True


def test_backup_metadata_saving(tmp_path):
    backend = FakeAndroidUsbBackend(permission_granted=True, device_connected=True)
    session = EDLSession(backend=backend)
    session.detect_device()
    session.chipset_info.msm_name = "SM8250"
    session.storage_info.storage_type = "UFS"

    backup_engine = PartitionBackup(session=session)
    meta_dir = str(tmp_path / "meta_output")

    ok = backup_engine.save_device_metadata(meta_dir)
    assert ok is True
    assert os.path.exists(os.path.join(meta_dir, "device-info.txt"))
    assert os.path.exists(os.path.join(meta_dir, "logs.txt"))

