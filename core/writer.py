#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.writer
Partition Writer engine for Qualcomm EDL over Firehose.
Enforces multi-layer safety confirmations, image size validation,
chunked streaming write, response validation, and optional reboot.
"""

import os
import sys
import time
import threading
from dataclasses import dataclass
from typing import Optional, Callable, Dict, Any

from android_usb.models import PartitionEntry
from core.session import EDLSession
from core.logbus import logbus

# Partitions that can permanently brick or wipe user data if written incorrectly
CRITICAL_PARTITIONS = {
    "gpt", "primarygpt", "backupgpt", "partition_table",
    "xbl", "xbl_a", "xbl_b", "xbl_config", "xbl_config_a", "xbl_config_b",
    "abl", "abl_a", "abl_b",
    "tz", "tz_a", "tz_b", "hyp", "hyp_a", "hyp_b",
    "rpm", "rpm_a", "rpm_b", "pmic", "pmic_a", "pmic_b",
    "sbl1", "sbl2", "sbl3", "bootloader",
    "userdata", "metadata",
    "modemst1", "modemst2", "fsg", "fsc", "sec",
    "keymaster", "keymaster_a", "keymaster_b", "devinfo",
}


@dataclass
class WriteValidation:
    is_valid: bool
    is_critical: bool
    image_size_bytes: int
    partition_size_bytes: int
    sectors_needed: int
    partition_sectors_available: int
    error: Optional[str] = None
    warning: Optional[str] = None


@dataclass
class WriteProgress:
    current_partition: str
    bytes_written: int
    bytes_total: int
    percentage: float
    speed_bytes_sec: float
    speed_formatted: str
    eta_seconds: float
    eta_formatted: str
    is_cancelled: bool = False
    is_complete: bool = False
    error: Optional[str] = None


class PartitionWriter:
    """Safely writes disk images to Qualcomm device partitions."""

    def __init__(self, session: EDLSession):
        self.session = session
        self._abort_requested = False
        self._is_running = False
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._is_running

    def request_cancel(self):
        """Signal cooperative abort."""
        with self._lock:
            self._abort_requested = True
            logbus.write("Cancelamento solicitado. Interrompendo após o lote atual...")

    def validate_image(self, image_path: str, partition: PartitionEntry) -> WriteValidation:
        """
        Validates file existence, partition bounds, and critical partition status.
        """
        if not os.path.exists(image_path):
            return WriteValidation(
                is_valid=False,
                is_critical=False,
                image_size_bytes=0,
                partition_size_bytes=partition.size_bytes,
                sectors_needed=0,
                partition_sectors_available=partition.sector_count,
                error=f"Arquivo '{image_path}' não foi encontrado.",
            )

        file_size = os.path.getsize(image_path)
        if file_size == 0:
            return WriteValidation(
                is_valid=False,
                is_critical=False,
                image_size_bytes=0,
                partition_size_bytes=partition.size_bytes,
                sectors_needed=0,
                partition_sectors_available=partition.sector_count,
                error="O arquivo de imagem selecionado está vazio (0 bytes).",
            )

        sector_size = partition.sector_size or 512
        sectors_needed = file_size // sector_size
        if file_size % sector_size != 0:
            sectors_needed += 1

        is_critical = partition.name.lower() in CRITICAL_PARTITIONS or "gpt" in partition.name.lower()

        if sectors_needed > partition.sector_count:
            return WriteValidation(
                is_valid=False,
                is_critical=is_critical,
                image_size_bytes=file_size,
                partition_size_bytes=partition.size_bytes,
                sectors_needed=sectors_needed,
                partition_sectors_available=partition.sector_count,
                error=(
                    f"A imagem ({file_size / (1024*1024):.2f} MB) excede a capacidade da partição "
                    f"'{partition.name}' ({partition.size_formatted})."
                ),
            )

        warning = None
        if is_critical:
            warning = (
                f"ATENÇÃO: '{partition.name}' é uma partição CRÍTICA do sistema. "
                "Gravar dados incorretos pode inutilizar o aparelho permanentemente."
            )

        return WriteValidation(
            is_valid=True,
            is_critical=is_critical,
            image_size_bytes=file_size,
            partition_size_bytes=partition.size_bytes,
            sectors_needed=sectors_needed,
            partition_sectors_available=partition.sector_count,
            warning=warning,
        )

    def write_partition(
        self,
        image_path: str,
        partition: PartitionEntry,
        user_confirmed: bool,
        extra_critical_confirmed: bool = False,
        reset_on_finish: bool = False,
        progress_callback: Optional[Callable[[WriteProgress], None]] = None,
    ) -> bool:
        """
        Executes real Firehose program command.
        Requires explicit confirmation and optional critical confirmation.
        """
        if not user_confirmed:
            raise PermissionError("Gravação cancelada: confirmação do usuário obrigatória.")

        validation = self.validate_image(image_path, partition)
        if not validation.is_valid:
            logbus.error(f"Validação da imagem falhou: {validation.error}")
            return False

        if validation.is_critical and not extra_critical_confirmed:
            raise PermissionError(
                f"Confirmação extra obrigatória para gravação na partição crítica '{partition.name}'."
            )

        if not self.session or not self.session.firehose_client_instance:
            raise ConnectionError("Sessão Firehose não está ativa.")

        fh = self.session.firehose_client_instance.firehose
        chip = self.session.chipset_info
        dev_name = chip.msm_name or (self.session.current_device.device_name if self.session.current_device else "Qualcomm EDL")

        logbus.write(f"Iniciando gravação na partição '{partition.name}' (LUN {partition.lun})")
        logbus.write(f"Dispositivo: {dev_name} | Imagem: {os.path.basename(image_path)} ({validation.image_size_bytes} bytes)")

        with self._lock:
            self._abort_requested = False
            self._is_running = True

        try:
            sector_size = partition.sector_size or fh.cfg.SECTOR_SIZE_IN_BYTES
            total_bytes = validation.image_size_bytes
            max_payload = fh.cfg.MaxPayloadSizeToTargetInBytes or (1024 * 1024)
            # Align payload size to sector size
            payload_sectors = max_payload // sector_size
            if payload_sectors <= 0:
                payload_sectors = 1
            chunk_size = payload_sectors * sector_size

            start_time = time.time()
            last_progress_time = start_time
            bytes_written = 0
            current_sector = partition.start_sector

            with open(image_path, "rb") as f_in:
                while bytes_written < total_bytes:
                    with self._lock:
                        if self._abort_requested:
                            logbus.write("Gravação abortada pelo usuário com segurança.")
                            if progress_callback:
                                progress_callback(
                                    WriteProgress(
                                        current_partition=partition.name,
                                        bytes_written=bytes_written,
                                        bytes_total=total_bytes,
                                        percentage=(bytes_written / total_bytes * 100),
                                        speed_bytes_sec=0.0,
                                        speed_formatted="0 MB/s",
                                        eta_seconds=0.0,
                                        eta_formatted="0s",
                                        is_cancelled=True,
                                    )
                                )
                            return False

                    raw_chunk = f_in.read(chunk_size)
                    if not raw_chunk:
                        break

                    chunk_len = len(raw_chunk)
                    sectors_in_chunk = chunk_len // sector_size
                    if chunk_len % sector_size != 0:
                        # Pad up to full sector
                        padding = sector_size - (chunk_len % sector_size)
                        raw_chunk += b"\x00" * padding
                        sectors_in_chunk += 1

                    # Send Firehose program command for this chunk
                    ok = fh.cmd_program_buffer(
                        physical_partition_number=partition.lun,
                        start_sector=current_sector,
                        wfdata=raw_chunk,
                        display=False,
                    )

                    if not ok:
                        err_msg = f"Erro no Firehose ao gravar setor {current_sector} na partição {partition.name}."
                        logbus.error(err_msg)
                        if progress_callback:
                            progress_callback(
                                WriteProgress(
                                    current_partition=partition.name,
                                    bytes_written=bytes_written,
                                    bytes_total=total_bytes,
                                    percentage=(bytes_written / total_bytes * 100),
                                    speed_bytes_sec=0.0,
                                    speed_formatted="0 MB/s",
                                    eta_seconds=0.0,
                                    eta_formatted="0s",
                                    error=err_msg,
                                )
                            )
                        return False

                    bytes_written += chunk_len
                    current_sector += sectors_in_chunk

                    now = time.time()
                    elapsed = max(0.001, now - start_time)
                    speed = bytes_written / elapsed
                    speed_str = f"{speed / (1024*1024):.1f} MB/s"
                    rem = max(0, total_bytes - bytes_written)
                    eta = rem / speed if speed > 0 else 0
                    eta_str = f"{int(eta // 60)}m{int(eta % 60):02d}s" if eta >= 60 else f"{int(eta)}s"
                    pct = min(100.0, (bytes_written / total_bytes * 100))

                    if progress_callback and (now - last_progress_time >= 0.1 or bytes_written >= total_bytes):
                        progress_callback(
                            WriteProgress(
                                current_partition=partition.name,
                                bytes_written=bytes_written,
                                bytes_total=total_bytes,
                                percentage=pct,
                                speed_bytes_sec=speed,
                                speed_formatted=speed_str,
                                eta_seconds=eta,
                                eta_formatted=eta_str,
                                is_complete=(bytes_written >= total_bytes),
                            )
                        )
                        last_progress_time = now

            logbus.write(f"Gravação concluída com sucesso na partição '{partition.name}' ({bytes_written} bytes)!")

            if reset_on_finish:
                logbus.session("Reiniciando dispositivo conforme solicitado...")
                try:
                    fh.cmd_reset()
                except Exception as e:
                    logbus.session(f"Comando de reinicialização enviado: {e}")

            return True

        except Exception as e:
            logbus.error(f"Erro fatal durante a gravação da partição {partition.name}: {e}")
            return False

        finally:
            with self._lock:
                self._is_running = False
