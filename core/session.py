#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.session
EDLSession - Master coordinator for Qualcomm EDL operations on Android.
Orchestrates:
AndroidUsbTransport -> Sahara REAL -> Programmer Upload -> Firehose REAL -> GPT REAL -> Partition Manager
"""

import os
import sys
import time
import logging
from typing import Optional, List, Dict, Any, Callable

# Ensure edlclient path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from android_usb.models import (
    UsbDeviceInfo,
    DeviceMode,
    DeviceChipsetInfo,
    StorageInfo,
    PartitionEntry,
)
from android_usb.backend import UsbBackendInterface
from android_usb.backend_android import AndroidUsbBackend, is_android_environment
from android_usb.transport import AndroidUsbTransport
from core.logbus import logbus

from edlclient.Library.sahara import sahara
from edlclient.Library.sahara_defs import sahara_mode_t, cmd_t
from edlclient.Library.firehose_client import firehose_client
from edlclient.Config.qualcomm_config import msmids


class PartitionManager:
    """Manages loaded partition entries and queries."""

    def __init__(self):
        self.partitions: List[PartitionEntry] = []

    def set_partitions(self, parts: List[PartitionEntry]):
        self.partitions = list(parts)

    def get_by_name(self, name: str) -> Optional[PartitionEntry]:
        for p in self.partitions:
            if p.name.lower() == name.lower():
                return p
        return None

    def get_by_lun(self, lun: int) -> List[PartitionEntry]:
        return [p for p in self.partitions if p.lun == lun]

    def all(self) -> List[PartitionEntry]:
        return list(self.partitions)

    def clear(self):
        self.partitions.clear()


class EDLSession:
    """
    Main EDL Controller.
    Preserves exact bkerler/edl semantics while driving execution over
    AndroidUsbTransport and native Android USB Host APIs.
    """

    def __init__(
        self,
        backend: Optional[UsbBackendInterface] = None,
        programmer_path: Optional[str] = None,
        memory_type: str = "ufs",
        sector_size: Optional[int] = None,
    ):
        self.backend = backend if backend is not None else (
            AndroidUsbBackend() if is_android_environment() else None
        )
        self.programmer_path = programmer_path
        self.memory_type = memory_type.lower()
        self.sector_size = sector_size

        self.current_device: Optional[UsbDeviceInfo] = None
        self.transport: Optional[AndroidUsbTransport] = None
        self.sahara_instance: Optional[sahara] = None
        self.firehose_client_instance: Optional[firehose_client] = None

        self.chipset_info = DeviceChipsetInfo()
        self.storage_info = StorageInfo()
        self.partition_manager = PartitionManager()

        self.mode = DeviceMode.DISCONNECTED
        self.status = "🔴 Desconectado"
        self.is_connected = False
        self._on_status_change: Optional[Callable[[str], None]] = None

    def set_status_callback(self, cb: Callable[[str], None]):
        self._on_status_change = cb

    def _update_status(self, mode: DeviceMode, status_text: str):
        self.mode = mode
        self.status = status_text
        if self._on_status_change:
            try:
                self._on_status_change(status_text)
            except Exception:
                pass

    def detect_device(self) -> Optional[UsbDeviceInfo]:
        """Detect Qualcomm EDL 9008 device."""
        if not self.backend:
            logbus.error("Nenhum backend USB disponível.")
            return None

        edl_devices = self.backend.find_edl_devices()
        if edl_devices:
            self.current_device = edl_devices[0]
            logbus.usb(f"05C6:9008 detectado ({self.current_device.device_name})")
            has_perm = self.backend.has_permission(self.current_device)
            perm_str = "com permissão" if has_perm else "sem permissão"
            self._update_status(DeviceMode.EDL_DETECTED, f"🟡 Qualcomm EDL 9008 ({perm_str})")
            return self.current_device
        else:
            self.current_device = None
            self._update_status(DeviceMode.DISCONNECTED, "🔴 Desconectado")
            return None

    def request_permission(self, callback: Optional[Callable[[bool], None]] = None) -> bool:
        """Request USB Host permission for detected EDL device."""
        if not self.current_device:
            self.detect_device()
        if not self.current_device:
            logbus.error("Nenhum dispositivo EDL conectado para solicitar autorização.")
            return False

        logbus.usb(f"Solicitando autorização USB para {self.current_device.id_str}...")

        def _on_perm(granted: bool):
            if granted:
                logbus.usb("Autorização USB concedida pelo usuário.")
                if self.current_device:
                    self.current_device.has_permission = True
                self._update_status(DeviceMode.EDL_DETECTED, "🟢 Qualcomm EDL 9008 autorizado")
            else:
                logbus.error("Autorização USB negada.")
            if callback:
                callback(granted)

        res = self.backend.request_permission(self.current_device, _on_perm)
        if res:
            _on_perm(True)
        return res

    def open_usb(self) -> AndroidUsbTransport:
        """Open USB connection and configure endpoints."""
        if not self.current_device:
            raise ConnectionError("Nenhum dispositivo EDL detectado.")

        if not self.backend.has_permission(self.current_device):
            raise PermissionError("Permissão USB Host não concedida para o dispositivo EDL.")

        conn = self.backend.open_device(self.current_device)
        if conn is None:
            raise ConnectionError("Falha ao abrir UsbDeviceConnection.")

        # Find Qualcomm interface and endpoints
        target_iface = None
        ep_in = None
        ep_out = None

        if self.current_device.interfaces:
            # Look for bulk IN and bulk OUT endpoints
            for iface_info in self.current_device.interfaces:
                for ep in iface_info.endpoints:
                    if ep.direction == 128:  # IN
                        ep_in = ep
                    elif ep.direction == 0:  # OUT
                        ep_out = ep
                if ep_in and ep_out:
                    target_iface = iface_info
                    break

        # Fallback to direct Java object inspection if needed
        if not (ep_in and ep_out) and hasattr(self.current_device.raw_device, "getInterface"):
            raw_dev = self.current_device.raw_device
            count = raw_dev.getInterfaceCount()
            for i in range(count):
                itf = raw_dev.getInterface(i)
                for j in range(itf.getEndpointCount()):
                    ep = itf.getEndpoint(j)
                    if ep.getDirection() == 128:  # IN
                        ep_in = ep
                    elif ep.getDirection() == 0:  # OUT
                        ep_out = ep
                if ep_in and ep_out:
                    target_iface = itf
                    break

        if not (ep_in and ep_out):
            raise RuntimeError("Não foi possível encontrar endpoints Bulk IN e OUT para comunicação EDL.")

        # Claim interface if native method exists
        if hasattr(conn, "claimInterface") and target_iface:
            raw_itf = getattr(target_iface, "raw_interface", target_iface)
            conn.claimInterface(raw_itf, True)

        in_addr = getattr(ep_in, "address", 0x81)
        out_addr = getattr(ep_out, "address", 0x01)
        logbus.usb(f"Interface reivindicada. IN=0x{in_addr:02X} OUT=0x{out_addr:02X}")

        self.transport = AndroidUsbTransport(
            connection=conn,
            interface=target_iface,
            ep_in=ep_in,
            ep_out=ep_out,
        )
        self.transport.set_disconnect_callback(self._handle_transport_disconnect)
        return self.transport

    def _handle_transport_disconnect(self, reason: str):
        logbus.error(f"Dispositivo EDL desconectado: {reason}")
        self.disconnect()

    def run_sahara_handshake(self, programmer_path: Optional[str] = None) -> bool:
        """
        Execute REAL Sahara handshake protocol.
        Extracts MSM ID, OEM ID, HW ID, Serial, PK Hash.
        Uploads programmer when in command mode and loader is provided.
        """
        if not self.transport:
            raise ConnectionError("Transporte USB não inicializado.")

        loader = programmer_path or self.programmer_path
        logbus.sahara("Iniciando Sahara handshake...")
        self._update_status(DeviceMode.SAHARA, "🟡 Executando Sahara...")

        self.sahara_instance = sahara(cdc=self.transport, loglevel=logging.INFO)
        if loader:
            self.sahara_instance.programmer = loader

        # Sahara connect
        res = self.sahara_instance.connect()
        if not res:
            logbus.error("Sahara handshake falhou: sem resposta do dispositivo.")
            self._update_status(DeviceMode.ERROR, "🔴 Erro no Sahara handshake")
            return False

        mode = res.get("mode", "")
        logbus.sahara(f"Modo detectado: {mode}")

        if mode == "firehose":
            logbus.sahara("Dispositivo já está em modo Firehose.")
            self.chipset_info.mode = "firehose"
            self._update_status(DeviceMode.FIREHOSE, "🟢 Firehose ativo")
            return True

        if mode == "sahara":
            self.chipset_info.sahara_version = getattr(self.sahara_instance, "version", 2.1)
            logbus.sahara(f"Hello recebido. Versão Sahara: {self.sahara_instance.version}")

            # Send hello response and query device identification
            try:
                # Enter command mode to query hardware IDs
                if self.sahara_instance.cmd_hello(sahara_mode_t.SAHARA_MODE_COMMAND):
                    logbus.sahara("Entrou em modo comando. Lendo identificadores do hardware...")
                    self.sahara_instance.cmd_info()
            except Exception as e:
                logbus.sahara(f"Aviso ao consultar info do Sahara: {e}")

            # Extract hardware IDs
            msm_id = getattr(self.sahara_instance, "msm_id", None)
            hwid_str = getattr(self.sahara_instance, "hwidstr", None)
            pk_hash = getattr(self.sahara_instance, "pkhash", None)
            serial = getattr(self.sahara_instance, "serial", None)
            oem_id = getattr(self.sahara_instance, "oem_id", None)

            msm_name = None
            if msm_id and msm_id in msmids:
                msm_name = msmids[msm_id]

            self.chipset_info.msm_id = msm_id
            self.chipset_info.msm_name = msm_name
            self.chipset_info.hw_id = hwid_str
            self.chipset_info.pk_hash = pk_hash
            self.chipset_info.serial = serial
            self.chipset_info.oem_id = oem_id
            self.chipset_info.mode = "sahara"

            logbus.sahara(f"MSM ID: {hex(msm_id) if msm_id else 'N/A'} ({msm_name or 'Desconhecido'})")
            if hwid_str:
                logbus.sahara(f"HW ID: {hwid_str}")
            if pk_hash:
                logbus.sahara(f"PK Hash: {pk_hash}")
            if serial:
                logbus.sahara(f"Serial: {hex(serial)}")

            # If loader is available, upload it
            if loader and os.path.exists(loader):
                logbus.sahara(f"Carregando programmer: {loader}")
                upload_ok = self.sahara_instance.upload_loader(loader)
                if not upload_ok:
                    logbus.error(f"Falha ao enviar programmer {loader} via Sahara.")
                    self._update_status(DeviceMode.ERROR, "🔴 Erro no upload do programmer")
                    return False
                logbus.sahara("Programmer enviado com sucesso. Aguardando transição para Firehose...")
                time.sleep(0.5)
                self._update_status(DeviceMode.FIREHOSE, "🟢 Transição para Firehose concluída")
                return True
            else:
                logbus.sahara("Nenhum programmer especificado. Pronto para seleção de loader.")
                self._update_status(DeviceMode.SAHARA, "🟡 Sahara conectado (Aguardando Programmer)")
                return True

        return False

    def configure_firehose(self, memory_type: Optional[str] = None) -> bool:
        """
        Configure REAL Firehose communication and query storage information.
        """
        if not self.transport:
            raise ConnectionError("Transporte USB não conectado.")

        if memory_type:
            self.memory_type = memory_type.lower()

        logbus.firehose(f"Configurando Firehose (Memória: {self.memory_type.upper()})...")
        self._update_status(DeviceMode.FIREHOSE, "🟡 Configurando Firehose...")

        sec_size = self.sector_size or (4096 if self.memory_type == "ufs" else 512)

        args = {
            "--memory": self.memory_type,
            "--skipstorageinit": False,
            "--skipwrite": False,
            "--maxpayload": "1048576",
            "--sectorsize": str(sec_size),
            "--pagesperblock": "128",
            "--skipresponse": False,
            "--devicemodel": None,
            "--lun": None,
        }

        # Initialize firehose_client using bkerler/edl original implementation
        self.firehose_client_instance = firehose_client(
            arguments=args,
            cdc=self.transport,
            sahara=self.sahara_instance if self.sahara_instance else sahara(self.transport, logging.INFO),
            loglevel=logging.INFO,
            printer=logbus.firehose,
        )

        try:
            self.firehose_client_instance.connect(self.sahara_instance)
            logbus.firehose("Firehose configurado com sucesso.")
        except Exception as e:
            logbus.error(f"Erro ao conectar ao Firehose: {e}")
            return False

        # Query storage information
        try:
            info = self.firehose_client_instance.get_storage_info()
            if info:
                self.storage_info.storage_type = info.get("storage_type", self.memory_type.upper())
                self.storage_info.block_size = int(info.get("block_size", sec_size))
                self.storage_info.sector_size = int(info.get("sector_size", sec_size))
                self.storage_info.total_sectors = int(info.get("num_physical_partitions", 0))
                self.storage_info.manufacturer = info.get("manufacturer_id")
                self.storage_info.product_name = info.get("product_name")

                logbus.firehose(f"Armazenamento: {self.storage_info.storage_type}")
                logbus.firehose(f"Tamanho do Setor: {self.storage_info.sector_size} bytes")
                logbus.firehose(f"Tamanho do Bloco: {self.storage_info.block_size} bytes")
            else:
                self.storage_info.storage_type = self.memory_type.upper()
                self.storage_info.sector_size = sec_size
                logbus.firehose(f"Storage configurado: {self.storage_info.storage_type} (Setor: {sec_size})")
        except Exception as e:
            logbus.firehose(f"Informações de armazenamento não retornadas: {e}")

        self.is_connected = True
        self._update_status(DeviceMode.FIREHOSE, "🟢 Firehose Conectado")
        return True

    def read_gpt(self) -> List[PartitionEntry]:
        """
        Read real GPT partition tables across all storage LUNs using edlclient.Library.gpt.
        """
        if not self.firehose_client_instance:
            raise ConnectionError("Firehose não está configurado.")

        logbus.gpt("Lendo tabela de partições GPT real...")
        self.partition_manager.clear()
        partitions_found: List[PartitionEntry] = []

        fh = self.firehose_client_instance.firehose
        luns_to_scan = [0, 1, 2, 3, 4, 5] if self.memory_type == "ufs" else [0]
        gpt_num_part_entries = 128
        gpt_part_entry_size = 128
        gpt_part_entry_start_lba = 2

        for lun in luns_to_scan:
            try:
                data, guid_gpt = fh.get_gpt(
                    lun=lun,
                    gpt_num_part_entries=gpt_num_part_entries,
                    gpt_part_entry_size=gpt_part_entry_size,
                    gpt_part_entry_start_lba=gpt_part_entry_start_lba,
                )
                if guid_gpt and hasattr(guid_gpt, "partentries"):
                    sector_size = fh.cfg.SECTOR_SIZE_IN_BYTES
                    for p in guid_gpt.partentries:
                        name = p.name.strip() if isinstance(p.name, str) else p.name.decode("utf-8", "ignore").strip("\x00")
                        if not name:
                            continue
                        count = (p.last_lba - p.first_lba + 1)
                        if count <= 0:
                            continue
                        entry = PartitionEntry(
                            lun=lun,
                            name=name,
                            start_sector=int(p.first_lba),
                            end_sector=int(p.last_lba),
                            sector_count=int(count),
                            sector_size=sector_size,
                            flags=int(p.flags),
                        )
                        partitions_found.append(entry)
            except Exception as e:
                # Lun might not exist
                logbus.gpt(f"Aviso ao consultar LUN {lun}: {e}")

        self.partition_manager.set_partitions(partitions_found)
        logbus.gpt(f"{len(partitions_found)} partições encontradas na GPT.")
        return partitions_found

    def connect_full(self, programmer_path: Optional[str] = None, memory_type: str = "ufs") -> bool:
        """
        Executes full connection sequence:
        detect -> open USB -> Sahara handshake -> (optional loader) -> Firehose -> GPT.
        """
        try:
            if not self.detect_device():
                return False

            if not self.backend.has_permission(self.current_device):
                logbus.usb("Aguardando permissão USB do usuário...")
                return False

            self.open_usb()
            if not self.run_sahara_handshake(programmer_path):
                return False

            if not self.configure_firehose(memory_type):
                return False

            self.read_gpt()
            return True
        except Exception as e:
            logbus.error(f"Erro na conexão EDL: {e}")
            self._update_status(DeviceMode.ERROR, f"🔴 Erro: {str(e)[:40]}")
            return False

    def disconnect(self):
        """Disconnect and clean up resources."""
        if self.transport:
            try:
                self.transport.close()
            except Exception:
                pass
            self.transport = None

        self.sahara_instance = None
        self.firehose_client_instance = None
        self.is_connected = False
        self.current_device = None
        self.partition_manager.clear()
        self._update_status(DeviceMode.DISCONNECTED, "🔴 Desconectado")
        logbus.session("Sessão EDL encerrada.")
