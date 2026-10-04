#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.backup
Streamed partition backup engine for Qualcomm EDL over Firehose.
Guarantees memory-safe chunked streaming (no multi-GB RAM allocation),
real-time byte progress calculation, speed, ETA, and cooperative cancellation.
"""

import os
import sys
import time
import shutil
import threading
from dataclasses import dataclass
from typing import Optional, Callable, List

from android_usb.models import PartitionEntry
from core.session import EDLSession
from core.logbus import logbus

DEFAULT_CHUNK_SIZE_BYTES = 1048576  # 1 MB


@dataclass
class BackupProgress:
    current_partition: str
    bytes_done: int
    bytes_total: int
    percentage: float
    speed_bytes_sec: float
    speed_formatted: str
    eta_seconds: float
    eta_formatted: str
    is_cancelled: bool = False
    is_complete: bool = False
    error: Optional[str] = None


class PartitionBackup:
    """Manages partition backup via streaming Firehose read."""

    def __init__(self, session: EDLSession, chunk_size_bytes: int = DEFAULT_CHUNK_SIZE_BYTES):
        self.session = session
        self.chunk_size_bytes = max(512, chunk_size_bytes)
        self._abort_requested = False
        self._is_running = False
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._is_running

    def request_cancel(self):
        """Signal cooperative abort after current transfer completes."""
        with self._lock:
            self._abort_requested = True
            logbus.read("Cancelamento solicitado. Abortando com segurança após o chunk atual...")

    def check_available_space(self, target_dir: str, required_bytes: int) -> bool:
        """Check if destination folder has sufficient free storage space."""
        try:
            stat = shutil.disk_usage(target_dir)
            if stat.free < required_bytes:
                logbus.error(
                    f"Espaço insuficiente em disco: {stat.free / (1024*1024):.1f} MB livres, "
                    f"necessário {required_bytes / (1024*1024):.1f} MB."
                )
                return False
            return True
        except Exception:
            return True

    def backup_partition(
        self,
        partition: PartitionEntry,
        output_file_path: str,
        progress_callback: Optional[Callable[[BackupProgress], None]] = None,
    ) -> bool:
        """
        Backup a single partition by streaming chunks from Firehose directly to disk.
        """
        if not self.session or not self.session.firehose_client_instance:
            raise ConnectionError("Sessão Firehose não está ativa.")

        fh = self.session.firehose_client_instance.firehose
        cdc = self.session.transport
        sector_size = partition.sector_size or fh.cfg.SECTOR_SIZE_IN_BYTES
        total_sectors = partition.sector_count
        total_bytes = total_sectors * sector_size

        dest_dir = os.path.dirname(output_file_path)
        if dest_dir and not os.path.exists(dest_dir):
            os.makedirs(dest_dir, exist_ok=True)

        if dest_dir and not self.check_available_space(dest_dir, total_bytes):
            raise IOError("Espaço em disco insuficiente para o backup da partição.")

        logbus.read(
            f"Iniciando backup de '{partition.name}' (LUN {partition.lun}): "
            f"{partition.size_formatted} ({total_sectors} setores)"
        )

        with self._lock:
            self._abort_requested = False
            self._is_running = True

        bytes_done = 0
        start_time = time.time()
        last_progress_time = start_time

        sectors_per_chunk = self.chunk_size_bytes // sector_size
        if sectors_per_chunk <= 0:
            sectors_per_chunk = 1
        chunk_bytes = sectors_per_chunk * sector_size

        try:
            with open(output_file_path, "wb") as f_out:
                current_sector = partition.start_sector
                remaining_sectors = total_sectors

                while remaining_sectors > 0:
                    with self._lock:
                        if self._abort_requested:
                            logbus.read(f"Backup de '{partition.name}' abortado com segurança.")
                            if progress_callback:
                                progress_callback(
                                    BackupProgress(
                                        current_partition=partition.name,
                                        bytes_done=bytes_done,
                                        bytes_total=total_bytes,
                                        percentage=(bytes_done / total_bytes * 100) if total_bytes else 0,
                                        speed_bytes_sec=0.0,
                                        speed_formatted="0 MB/s",
                                        eta_seconds=0.0,
                                        eta_formatted="0s",
                                        is_cancelled=True,
                                    )
                                )
                            return False

                    batch_sectors = min(remaining_sectors, sectors_per_chunk)
                    batch_bytes = batch_sectors * sector_size

                    # Read raw sectors from Firehose
                    resp = fh.cmd_read_buffer(
                        physical_partition_number=partition.lun,
                        start_sector=current_sector,
                        num_partition_sectors=batch_sectors,
                        display=False,
                    )

                    if not resp or not resp.resp:
                        err_msg = f"Falha ao ler setor {current_sector} da partição {partition.name}"
                        logbus.error(err_msg)
                        if progress_callback:
                            progress_callback(
                                BackupProgress(
                                    current_partition=partition.name,
                                    bytes_done=bytes_done,
                                    bytes_total=total_bytes,
                                    percentage=(bytes_done / total_bytes * 100) if total_bytes else 0,
                                    speed_bytes_sec=0.0,
                                    speed_formatted="0 MB/s",
                                    eta_seconds=0.0,
                                    eta_formatted="0s",
                                    error=err_msg,
                                )
                            )
                        return False

                    chunk_data = resp.data
                    if len(chunk_data) == 0:
                        raise ConnectionError("Nenhum dado retornado pelo Firehose.")

                    # Write chunk directly to file (streaming, low RAM usage)
                    f_out.write(chunk_data)
                    bytes_done += len(chunk_data)
                    current_sector += batch_sectors
                    remaining_sectors -= batch_sectors

                    # Real progress calculation
                    now = time.time()
                    elapsed = max(0.001, now - start_time)
                    speed = bytes_done / elapsed
                    speed_mb_s = speed / (1024 * 1024)
                    speed_str = f"{speed_mb_s:.1f} MB/s"

                    remaining_bytes = max(0, total_bytes - bytes_done)
                    eta_sec = (remaining_bytes / speed) if speed > 0 else 0
                    eta_str = f"{int(eta_sec // 60)}m{int(eta_sec % 60):02d}s" if eta_sec >= 60 else f"{int(eta_sec)}s"
                    pct = (bytes_done / total_bytes * 100) if total_bytes > 0 else 100.0

                    if progress_callback and (now - last_progress_time >= 0.1 or remaining_sectors == 0):
                        prog = BackupProgress(
                            current_partition=partition.name,
                            bytes_done=bytes_done,
                            bytes_total=total_bytes,
                            percentage=pct,
                            speed_bytes_sec=speed,
                            speed_formatted=speed_str,
                            eta_seconds=eta_sec,
                            eta_formatted=eta_str,
                            is_complete=(remaining_sectors == 0),
                        )
                        progress_callback(prog)
                        last_progress_time = now

            logbus.read(f"Backup concluído: {output_file_path} ({partition.size_formatted})")
            return True

        except Exception as e:
            logbus.error(f"Erro no backup da partição {partition.name}: {e}")
            if os.path.exists(output_file_path) and bytes_done < total_bytes:
                # Incomplete file
                pass
            return False

        finally:
            with self._lock:
                self._is_running = False

    def save_device_metadata(self, output_dir: str) -> bool:
        """
        Save gpt_main.bin, gpt_backup.bin, device-info.txt, and logs.txt into output_dir.
        """
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        logbus.session(f"Salvando metadados do dispositivo em: {output_dir}")

        # 1. Device info
        try:
            info_path = os.path.join(output_dir, "device-info.txt")
            chip = self.session.chipset_info
            storage = self.session.storage_info
            dev = self.session.current_device

            with open(info_path, "w", encoding="utf-8") as f:
                f.write("=== QUALCOMM EDL DEVICE INFO ===\n")
                if dev:
                    f.write(f"USB Device: {dev.device_name} ({dev.id_str})\n")
                f.write(f"Sahara Version: {chip.sahara_version}\n")
                f.write(f"MSM ID: {hex(chip.msm_id) if chip.msm_id else 'N/A'} ({chip.msm_name or 'Unknown'})\n")
                f.write(f"HW ID: {chip.hw_id}\n")
                f.write(f"PK Hash: {chip.pk_hash}\n")
                f.write(f"Serial: {hex(chip.serial) if chip.serial else 'N/A'}\n")
                f.write(f"Storage: {storage.storage_type}\n")
                f.write(f"Sector Size: {storage.sector_size} bytes\n")
                f.write(f"Block Size: {storage.block_size} bytes\n")
                f.write(f"Total Partitions: {len(self.session.partition_manager.all())}\n")
                f.write("\n=== PARTITIONS ===\n")
                for p in self.session.partition_manager.all():
                    f.write(f"LUN {p.lun}: {p.name:<25} Start: {p.start_sector:<10} Count: {p.sector_count:<10} Size: {p.size_formatted}\n")
        except Exception as e:
            logbus.error(f"Erro ao salvar device-info.txt: {e}")

        # 2. Save GPT bins
        try:
            if self.session.firehose_client_instance:
                fh = self.session.firehose_client_instance.firehose
                luns = [0, 1, 2, 3, 4, 5] if self.session.memory_type == "ufs" else [0]
                for lun in luns:
                    gpt_main_path = os.path.join(output_dir, f"gpt_main{lun}.bin")
                    gpt_backup_path = os.path.join(output_dir, f"gpt_backup{lun}.bin")
                    try:
                        main_data, _ = fh.get_gpt(lun, 128, 128, 2)
                        if main_data:
                            with open(gpt_main_path, "wb") as f:
                                f.write(main_data)
                    except Exception:
                        pass
                    try:
                        backup_data = fh.get_backup_gpt(lun, 128, 128, 2)
                        if backup_data:
                            with open(gpt_backup_path, "wb") as f:
                                f.write(backup_data)
                    except Exception:
                        pass
        except Exception as e:
            logbus.error(f"Erro ao salvar tabelas GPT binárias: {e}")

        # 3. Save logs.txt
        logs_path = os.path.join(output_dir, "logs.txt")
        logbus.export_to_file(logs_path)
        logbus.session("Metadados salvos com sucesso.")
        return True
