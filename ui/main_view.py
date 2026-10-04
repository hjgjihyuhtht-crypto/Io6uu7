#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui.main_view
Main Qualcomm EDL Suite interface for Flet.
Provides Dashboard, Device Details, Programmer Selection, Partition View, and Live Logs.
"""

import os
import threading
import flet as ft
from typing import Optional

from core.session import EDLSession
from core.logbus import logbus
from ui.log_view import LogView
from ui.partition_view import PartitionView


class MainView(ft.Container):
    """Primary application view hosting EDL controls and tabs."""

    def __init__(self, page: ft.Page, session: EDLSession, file_picker: ft.FilePicker):
        super().__init__()
        self.page = page
        self.session = session
        self.file_picker = file_picker
        self.expand = True

        # Status badge
        self.status_icon = ft.Icon(ft.Icons.CIRCLE, color=ft.Colors.RED_500, size=16)
        self.status_text = ft.Text(
            self.session.status,
            weight=ft.FontWeight.BOLD,
            size=14,
            color=ft.Colors.WHITE,
        )

        # Device info widgets
        self.info_vid_pid = ft.Text("05C6:9008 (Não detectado)", size=13, font_family="monospace")
        self.info_sahara = ft.Text("Inativo", size=13, font_family="monospace")
        self.info_msm_id = ft.Text("--", size=13, font_family="monospace")
        self.info_chipset = ft.Text("--", size=13, font_family="monospace")
        self.info_storage = ft.Text("--", size=13, font_family="monospace")
        self.info_sector_size = ft.Text("--", size=13, font_family="monospace")
        self.info_hw_id = ft.Text("--", size=11, font_family="monospace")
        self.info_pk_hash = ft.Text("--", size=11, font_family="monospace")
        self.info_serial = ft.Text("--", size=11, font_family="monospace")

        # Programmer widgets
        self.txt_programmer_path = ft.Text(
            "Nenhum programmer selecionado.",
            size=12,
            color=ft.Colors.GREY_400,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self.txt_programmer_size = ft.Text("Tamanho: 0 KB", size=12, color=ft.Colors.GREY_400)
        self.txt_programmer_status = ft.Text("Status: Não carregado", size=12, color=ft.Colors.AMBER_400)

        # Memory type selector
        self.radio_memory_type = ft.RadioGroup(
            content=ft.Row(
                controls=[
                    ft.Radio(value="ufs", label="UFS (Setor 4096)"),
                    ft.Radio(value="emmc", label="eMMC (Setor 512)"),
                ]
            ),
            value="ufs",
            on_change=self.on_memory_type_change,
        )

        # Action buttons
        self.btn_detect = ft.ElevatedButton(
            "Detectar 9008",
            icon=ft.Icons.USB,
            on_click=self.on_detect_click,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_GREY_800),
        )
        self.btn_auth = ft.ElevatedButton(
            "Autorizar USB",
            icon=ft.Icons.KEY,
            on_click=self.on_auth_click,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_800),
        )
        self.btn_connect = ft.ElevatedButton(
            "Conectar EDL",
            icon=ft.Icons.CABLE,
            on_click=self.on_connect_click,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE),
        )
        self.btn_pick_programmer = ft.ElevatedButton(
            "Selecionar Programmer",
            icon=ft.Icons.FILE_OPEN,
            on_click=self.on_pick_programmer_click,
        )
        self.btn_read_gpt = ft.ElevatedButton(
            "Ler GPT",
            icon=ft.Icons.LIST_ALT,
            on_click=self.on_read_gpt_click,
            style=ft.ButtonStyle(bgcolor=ft.Colors.PURPLE_800, color=ft.Colors.WHITE),
        )
        self.btn_backup_meta = ft.ElevatedButton(
            "Backup Metadados",
            icon=ft.Icons.SAVE,
            on_click=self.on_backup_meta_click,
        )
        self.btn_disconnect = ft.ElevatedButton(
            "Desconectar",
            icon=ft.Icons.POWER_SETTINGS_NEW,
            on_click=self.on_disconnect_click,
            style=ft.ButtonStyle(bgcolor=ft.Colors.RED_900, color=ft.Colors.WHITE),
        )

        # Subviews
        self.partition_view = PartitionView(self.page, self.session, self.file_picker)
        self.log_view = LogView(self.page)

        # Wire session status callback
        self.session.set_status_callback(self.on_session_status_change)

        # Build main layout with tabs
        self.tabs = ft.Tabs(
            selected_index=0,
            animation_duration=200,
            tabs=[
                ft.Tab(
                    text="Dashboard",
                    icon=ft.Icons.DASHBOARD,
                    content=self.build_dashboard_tab(),
                ),
                ft.Tab(
                    text="Programmer",
                    icon=ft.Icons.MEMORY,
                    content=self.build_programmer_tab(),
                ),
                ft.Tab(
                    text="Partições GPT",
                    icon=ft.Icons.STORAGE,
                    content=self.partition_view,
                ),
                ft.Tab(
                    text="Logs em Tempo Real",
                    icon=ft.Icons.RECEIPT_LONG,
                    content=self.log_view,
                ),
            ],
            expand=True,
        )

        self.content = ft.Column(
            expand=True,
            spacing=8,
            controls=[
                self.build_header(),
                self.tabs,
            ],
        )

    def build_header(self) -> ft.Container:
        """Top app banner with status pill."""
        return ft.Container(
            padding=ft.padding.symmetric(horizontal=16, vertical=10),
            bgcolor=ft.Colors.BLUE_GREY_950,
            border_radius=8,
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Row(
                        spacing=10,
                        controls=[
                            ft.Icon(ft.Icons.SECURITY, color=ft.Colors.CYAN_400, size=24),
                            ft.Text(
                                "QUALCOMM EDL TOOL",
                                weight=ft.FontWeight.BOLD,
                                size=18,
                                color=ft.Colors.WHITE,
                            ),
                            ft.Container(
                                content=ft.Text("EDL 9008", size=10, weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK),
                                bgcolor=ft.Colors.AMBER_400,
                                padding=ft.padding.symmetric(horizontal=6, vertical=2),
                                border_radius=4,
                            ),
                        ],
                    ),
                    ft.Container(
                        padding=ft.padding.symmetric(horizontal=12, vertical=6),
                        bgcolor=ft.Colors.BLACK54,
                        border_radius=20,
                        border=ft.border.all(1, ft.Colors.BLUE_GREY_800),
                        content=ft.Row(
                            spacing=8,
                            controls=[self.status_icon, self.status_text],
                        ),
                    ),
                ],
            ),
        )

    def build_dashboard_tab(self) -> ft.Container:
        """Build main dashboard with hardware info and control actions."""
        # Top toolbar
        toolbar = ft.Row(
            wrap=True,
            spacing=8,
            controls=[
                self.btn_detect,
                self.btn_auth,
                self.btn_connect,
                self.btn_read_gpt,
                self.btn_backup_meta,
                self.btn_disconnect,
            ],
        )

        # Hardware Info Grid
        info_card = ft.Container(
            bgcolor=ft.Colors.BLUE_GREY_900,
            padding=16,
            border_radius=8,
            border=ft.border.all(1, ft.Colors.BLUE_GREY_800),
            content=ft.Column(
                spacing=12,
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.INFO_OUTLINE, color=ft.Colors.CYAN_400),
                            ft.Text("Informações do Dispositivo Qualcomm", weight=ft.FontWeight.BOLD, size=15),
                        ]
                    ),
                    ft.Divider(height=1, color=ft.Colors.BLUE_GREY_700),
                    ft.ResponsiveRow(
                        columns=12,
                        controls=[
                            ft.Column(col={"sm": 6, "md": 4}, controls=[ft.Text("VID:PID", size=11, color=ft.Colors.GREY_400), self.info_vid_pid]),
                            ft.Column(col={"sm": 6, "md": 4}, controls=[ft.Text("Chipset / SoC", size=11, color=ft.Colors.GREY_400), self.info_chipset]),
                            ft.Column(col={"sm": 6, "md": 4}, controls=[ft.Text("MSM ID", size=11, color=ft.Colors.GREY_400), self.info_msm_id]),
                            ft.Column(col={"sm": 6, "md": 4}, controls=[ft.Text("Protocolo Sahara", size=11, color=ft.Colors.GREY_400), self.info_sahara]),
                            ft.Column(col={"sm": 6, "md": 4}, controls=[ft.Text("Armazenamento", size=11, color=ft.Colors.GREY_400), self.info_storage]),
                            ft.Column(col={"sm": 6, "md": 4}, controls=[ft.Text("Tamanho de Setor", size=11, color=ft.Colors.GREY_400), self.info_sector_size]),
                        ],
                    ),
                    ft.Divider(height=1, color=ft.Colors.BLUE_GREY_700),
                    ft.ResponsiveRow(
                        columns=12,
                        controls=[
                            ft.Column(col={"sm": 12, "md": 4}, controls=[ft.Text("HW ID", size=11, color=ft.Colors.GREY_400), self.info_hw_id]),
                            ft.Column(col={"sm": 12, "md": 4}, controls=[ft.Text("PK Hash", size=11, color=ft.Colors.GREY_400), self.info_pk_hash]),
                            ft.Column(col={"sm": 12, "md": 4}, controls=[ft.Text("Número Serial", size=11, color=ft.Colors.GREY_400), self.info_serial]),
                        ],
                    ),
                ],
            ),
        )

        return ft.Container(
            padding=12,
            expand=True,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.ADAPTIVE,
                spacing=14,
                controls=[
                    toolbar,
                    info_card,
                ],
            ),
        )

    def build_programmer_tab(self) -> ft.Container:
        """Build programmer selection and memory configuration view."""
        return ft.Container(
            padding=16,
            content=ft.Column(
                spacing=14,
                controls=[
                    ft.Text("Seleção de Programmer / Firehose Loader", weight=ft.FontWeight.BOLD, size=16),
                    ft.Text(
                        "O arquivo programmer (.elf ou .bin) inicializa o protocolo Firehose no aparelho em modo EDL.\n"
                        "Selecione o arquivo prog_emmc_firehose_xxx.elf ou prog_ufs_firehose_xxx.elf correspondente ao seu SoC.",
                        color=ft.Colors.GREY_400,
                        size=13,
                    ),
                    ft.Divider(height=1, color=ft.Colors.BLUE_GREY_800),
                    ft.Row(controls=[self.btn_pick_programmer]),
                    ft.Container(
                        bgcolor=ft.Colors.BLUE_GREY_900,
                        padding=12,
                        border_radius=6,
                        border=ft.border.all(1, ft.Colors.BLUE_GREY_800),
                        content=ft.Column(
                            spacing=6,
                            controls=[
                                self.txt_programmer_path,
                                self.txt_programmer_size,
                                self.txt_programmer_status,
                            ],
                        ),
                    ),
                    ft.Text("Tipo de Memória do Aparelho:", weight=ft.FontWeight.BOLD, size=14),
                    self.radio_memory_type,
                ],
            ),
        )

    def on_memory_type_change(self, e):
        self.session.memory_type = self.radio_memory_type.value
        logbus.session(f"Tipo de memória configurado para: {self.session.memory_type.upper()}")

    def on_session_status_change(self, status_text: str):
        self.status_text.value = status_text
        if "🟢" in status_text:
            self.status_icon.color = ft.Colors.GREEN_400
        elif "🟡" in status_text:
            self.status_icon.color = ft.Colors.AMBER_400
        else:
            self.status_icon.color = ft.Colors.RED_400
        try:
            self.page.update()
        except Exception:
            pass

    def update_hardware_info(self):
        dev = self.session.current_device
        chip = self.session.chipset_info
        storage = self.session.storage_info

        if dev:
            self.info_vid_pid.value = f"{dev.id_str} ({dev.device_name})"
        else:
            self.info_vid_pid.value = "Desconectado"

        if chip.sahara_version:
            self.info_sahara.value = f"Ativo (v{chip.sahara_version})"
        else:
            self.info_sahara.value = "Inativo"

        self.info_msm_id.value = hex(chip.msm_id) if chip.msm_id else "--"
        self.info_chipset.value = chip.msm_name or (f"0x{chip.msm_id:X}" if chip.msm_id else "--")
        self.info_storage.value = storage.storage_type
        self.info_sector_size.value = f"{storage.sector_size} bytes" if storage.sector_size else "--"
        self.info_hw_id.value = chip.hw_id or "--"
        self.info_pk_hash.value = chip.pk_hash or "--"
        self.info_serial.value = hex(chip.serial) if chip.serial else "--"

        try:
            self.page.update()
        except Exception:
            pass

    def on_detect_click(self, e):
        logbus.usb("Verificando dispositivos USB Host...")
        dev = self.session.detect_device()
        self.update_hardware_info()
        msg = f"Dispositivo {dev.id_str} detectado!" if dev else "Nenhum dispositivo 05C6:9008 encontrado."
        snack = ft.SnackBar(ft.Text(msg))
        self.page.overlay.append(snack)
        snack.open = True
        self.page.update()

    def on_auth_click(self, e):
        def cb(granted: bool):
            self.update_hardware_info()
            msg = "Permissão USB Concedida!" if granted else "Permissão USB Negada."
            snack = ft.SnackBar(ft.Text(msg))
            self.page.overlay.append(snack)
            snack.open = True
            self.page.update()

        self.session.request_permission(callback=cb)

    def on_pick_programmer_click(self, e):
        def on_prog_result(pe: ft.FilePickerResultEvent):
            if pe.files:
                path = pe.files[0].path
                self.session.programmer_path = path
                self.txt_programmer_path.value = f"Arquivo: {path}"
                size_kb = os.path.getsize(path) / 1024
                self.txt_programmer_size.value = f"Tamanho: {size_kb:.1f} KB"
                self.txt_programmer_status.value = "Status: Selecionado e pronto para upload"
                self.txt_programmer_status.color = ft.Colors.GREEN_400
                logbus.session(f"Programmer definido: {os.path.basename(path)}")
                self.page.update()

        self.file_picker.on_result = on_prog_result
        self.file_picker.pick_files(
            dialog_title="Selecionar Programmer Firehose (.elf, .mbn, .bin)",
            allowed_extensions=["elf", "mbn", "bin"],
        )

    def on_connect_click(self, e):
        """Worker thread to run full connect without blocking the UI."""
        self.btn_connect.disabled = True
        self.page.update()

        def worker():
            logbus.session("Executando sequência de conexão EDL...")
            try:
                ok = self.session.connect_full(
                    programmer_path=self.session.programmer_path,
                    memory_type=self.radio_memory_type.value,
                )
                self.update_hardware_info()
                if ok:
                    self.partition_view.render_table()
                    self.tabs.selected_index = 2  # Switch to partitions
            except Exception as ex:
                logbus.error(f"Erro na conexão EDL: {ex}")
            finally:
                self.btn_connect.disabled = False
                try:
                    self.page.update()
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def on_read_gpt_click(self, e):
        def worker():
            try:
                self.session.read_gpt()
                self.partition_view.render_table()
                self.tabs.selected_index = 2
            except Exception as ex:
                logbus.error(f"Falha ao ler GPT: {ex}")
            try:
                self.page.update()
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def on_backup_meta_click(self, e):
        def worker():
            dest = "/storage/emulated/0/Download/edl_device_meta"
            try:
                from core.backup import PartitionBackup
                b = PartitionBackup(self.session)
                b.save_device_metadata(dest)
                snack = ft.SnackBar(ft.Text(f"Metadados salvos em {dest}"))
                self.page.overlay.append(snack)
                snack.open = True
            except Exception as ex:
                logbus.error(f"Erro ao salvar metadados: {ex}")
            try:
                self.page.update()
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def on_disconnect_click(self, e):
        self.session.disconnect()
        self.update_hardware_info()
        self.partition_view.render_table()
        snack = ft.SnackBar(ft.Text("Dispositivo EDL desconectado."))
        self.page.overlay.append(snack)
        snack.open = True
        self.page.update()
