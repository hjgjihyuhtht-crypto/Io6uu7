#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui.partition_view
Interactive GPT partition table view with per-partition Read and Write actions,
search filtering, multi-partition backup queue, and real-time streaming progress.
"""

import os
import threading
import flet as ft
from typing import List, Optional, Set

from android_usb.models import PartitionEntry
from core.session import EDLSession
from core.backup import PartitionBackup, BackupProgress
from core.writer import PartitionWriter, WriteProgress, WriteValidation, CRITICAL_PARTITIONS
from core.logbus import logbus


class PartitionView(ft.Container):
    """Component displaying real GPT partitions and handling read/write workflows."""

    def __init__(self, page: ft.Page, session: EDLSession, file_picker: ft.FilePicker):
        super().__init__()
        self.page = page
        self.session = session
        self.file_picker = file_picker
        self.expand = True
        self.padding = 10

        self.selected_partitions: Set[str] = set()
        self.search_query = ""
        self.active_backup_engine: Optional[PartitionBackup] = None
        self.active_writer_engine: Optional[PartitionWriter] = None

        # Search and batch toolbar
        self.search_input = ft.TextField(
            hint_text="Filtrar partição (ex: boot, system, modem, vbmeta)...",
            prefix_icon=ft.Icons.SEARCH,
            expand=True,
            on_change=self.on_search_changed,
            dense=True,
        )

        self.btn_select_all = ft.OutlinedButton(
            "Selecionar Todos",
            icon=ft.Icons.SELECT_ALL,
            on_click=self.on_toggle_select_all,
        )

        self.btn_backup_selected = ft.ElevatedButton(
            "Backup Selecionados",
            icon=ft.Icons.DOWNLOAD,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE),
            on_click=self.on_backup_selected_click,
        )

        self.stats_text = ft.Text(
            "Nenhuma tabela GPT carregada.",
            color=ft.Colors.GREY_400,
            size=13,
        )

        self.table_column = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.ADAPTIVE,
            controls=[],
        )

        self.content = ft.Column(
            expand=True,
            spacing=10,
            controls=[
                ft.Row(
                    controls=[
                        self.search_input,
                        self.btn_select_all,
                        self.btn_backup_selected,
                    ]
                ),
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        self.stats_text,
                        ft.IconButton(
                            icon=ft.Icons.REFRESH,
                            tooltip="Recarregar GPT",
                            on_click=lambda e: self.reload_gpt(),
                        ),
                    ],
                ),
                ft.Divider(height=1, color=ft.Colors.BLUE_GREY_800),
                ft.Container(
                    expand=True,
                    border=ft.border.all(1, ft.Colors.BLUE_GREY_900),
                    border_radius=8,
                    padding=6,
                    content=self.table_column,
                ),
            ],
        )

    def on_search_changed(self, e):
        self.search_query = (e.control.value or "").strip().lower()
        self.render_table()

    def reload_gpt(self):
        """Worker thread to read real GPT from Firehose."""
        def worker():
            logbus.gpt("Recarregando GPT via Firehose...")
            try:
                self.session.read_gpt()
            except Exception as ex:
                logbus.error(f"Erro ao ler GPT: {ex}")
            self.render_table()
            try:
                self.page.update()
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def on_toggle_select_all(self, e):
        partitions = self.session.partition_manager.all()
        if len(self.selected_partitions) == len(partitions) and partitions:
            self.selected_partitions.clear()
            self.btn_select_all.text = "Selecionar Todos"
        else:
            self.selected_partitions = {f"{p.lun}_{p.name}" for p in partitions}
            self.btn_select_all.text = "Desmarcar Todos"
        self.render_table()

    def render_table(self):
        """Build data table with current partitions matching search filter."""
        partitions = self.session.partition_manager.all()
        if not partitions:
            self.stats_text.value = "Nenhuma tabela GPT carregada. Conecte ao Firehose e clique em 'Ler GPT'."
            self.table_column.controls = [
                ft.Container(
                    alignment=ft.alignment.center,
                    padding=40,
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=10,
                        controls=[
                            ft.Icon(ft.Icons.STORAGE, size=48, color=ft.Colors.GREY_600),
                            ft.Text("Aguardando leitura da tabela GPT.", color=ft.Colors.GREY_400),
                        ],
                    ),
                )
            ]
            try:
                self.page.update()
            except Exception:
                pass
            return

        filtered = [
            p for p in partitions
            if not self.search_query or self.search_query in p.name.lower() or self.search_query in f"lun{p.lun}"
        ]

        self.stats_text.value = f"Total: {len(partitions)} partições | Filtradas: {len(filtered)} | Selecionadas: {len(self.selected_partitions)}"

        rows = []
        for p in filtered:
            p_key = f"{p.lun}_{p.name}"
            is_checked = p_key in self.selected_partitions
            is_crit = p.name.lower() in CRITICAL_PARTITIONS or "gpt" in p.name.lower()

            def make_check_cb(key):
                return lambda e: self.toggle_single_select(key, e.control.value)

            def make_read_cb(part):
                return lambda e: self.open_read_dialog(part)

            def make_write_cb(part):
                return lambda e: self.open_write_dialog(part)

            name_widget = ft.Row(
                spacing=6,
                controls=[
                    ft.Text(p.name, weight=ft.FontWeight.W_600, color=ft.Colors.WHITE),
                    ft.Container(
                        content=ft.Text("CRÍTICA", size=9, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                        bgcolor=ft.Colors.RED_900,
                        padding=ft.padding.symmetric(horizontal=4, vertical=2),
                        border_radius=4,
                        visible=is_crit,
                    ),
                ],
            )

            row = ft.DataRow(
                cells=[
                    ft.DataCell(
                        ft.Checkbox(
                            value=is_checked,
                            on_change=make_check_cb(p_key),
                        )
                    ),
                    ft.DataCell(ft.Text(f"LUN {p.lun}", color=ft.Colors.CYAN_300)),
                    ft.DataCell(name_widget),
                    ft.DataCell(ft.Text(p.size_formatted, color=ft.Colors.AMBER_300)),
                    ft.DataCell(ft.Text(str(p.start_sector), color=ft.Colors.GREY_300, font_family="monospace")),
                    ft.DataCell(ft.Text(str(p.end_sector), color=ft.Colors.GREY_300, font_family="monospace")),
                    ft.DataCell(
                        ft.Row(
                            spacing=4,
                            controls=[
                                ft.ElevatedButton(
                                    "Ler",
                                    icon=ft.Icons.DOWNLOAD,
                                    style=ft.ButtonStyle(
                                        padding=ft.padding.symmetric(horizontal=8, vertical=4),
                                        bgcolor=ft.Colors.BLUE_900,
                                        color=ft.Colors.WHITE,
                                    ),
                                    on_click=make_read_cb(p),
                                ),
                                ft.ElevatedButton(
                                    "Gravar",
                                    icon=ft.Icons.UPLOAD,
                                    style=ft.ButtonStyle(
                                        padding=ft.padding.symmetric(horizontal=8, vertical=4),
                                        bgcolor=ft.Colors.ORANGE_900 if is_crit else ft.Colors.DEEP_ORANGE_800,
                                        color=ft.Colors.WHITE,
                                    ),
                                    on_click=make_write_cb(p),
                                ),
                            ],
                        )
                    ),
                ]
            )
            rows.append(row)

        table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Sel")),
                ft.DataColumn(ft.Text("LUN")),
                ft.DataColumn(ft.Text("Partição")),
                ft.DataColumn(ft.Text("Tamanho")),
                ft.DataColumn(ft.Text("Início")),
                ft.DataColumn(ft.Text("Fim")),
                ft.DataColumn(ft.Text("Ações")),
            ],
            rows=rows,
            column_spacing=12,
            heading_row_color=ft.Colors.BLUE_GREY_900,
            border=ft.border.all(1, ft.Colors.BLUE_GREY_800),
        )

        self.table_column.controls = [table]
        try:
            self.page.update()
        except Exception:
            pass

    def toggle_single_select(self, p_key: str, selected: bool):
        if selected:
            self.selected_partitions.add(p_key)
        else:
            self.selected_partitions.discard(p_key)
        self.stats_text.value = f"Selecionadas: {len(self.selected_partitions)}"
        self.page.update()

    def open_read_dialog(self, partition: PartitionEntry):
        """Open Read/Backup dialog with real-time byte progress."""
        dest_dir = "/storage/emulated/0/Download"
        output_file = os.path.join(dest_dir, f"{partition.name}.img")

        progress_bar = ft.ProgressBar(value=0.0, color=ft.Colors.BLUE_400, bgcolor=ft.Colors.GREY_800)
        progress_text = ft.Text("Pronto para iniciar leitura.", size=12, font_family="monospace")
        speed_text = ft.Text("0 MB/s", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400)
        eta_text = ft.Text("ETA --", size=12, color=ft.Colors.AMBER_400)

        btn_cancel = ft.TextButton("Fechar")
        btn_start = ft.ElevatedButton("Iniciar Backup", bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Backup da Partição: {partition.name}"),
            content=ft.Container(
                width=450,
                content=ft.Column(
                    main_axis_size=ft.MainAxisSize.MIN,
                    spacing=12,
                    controls=[
                        ft.Text(f"LUN: {partition.lun} | Tamanho: {partition.size_formatted}"),
                        ft.Text(f"Setor inicial: {partition.start_sector} | Total: {partition.sector_count}"),
                        ft.Text(f"Destino: {output_file}", size=11, color=ft.Colors.GREY_400),
                        progress_bar,
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[speed_text, eta_text],
                        ),
                        progress_text,
                    ],
                ),
            ),
            actions=[btn_cancel, btn_start],
        )

        def on_progress(p: BackupProgress):
            progress_bar.value = p.percentage / 100.0
            progress_text.value = f"{p.bytes_done / (1024*1024):.2f} MB / {p.bytes_total / (1024*1024):.2f} MB ({p.percentage:.1f}%)"
            speed_text.value = p.speed_formatted
            eta_text.value = f"ETA {p.eta_formatted}"
            if p.is_complete:
                progress_text.value = "✅ Backup concluído com sucesso!"
                btn_start.visible = False
                btn_cancel.text = "Concluir"
            if p.error:
                progress_text.value = f"❌ Erro: {p.error}"
            self.page.update()

        def do_cancel(e):
            if self.active_backup_engine and self.active_backup_engine.is_running:
                self.active_backup_engine.request_cancel()
                progress_text.value = "Cancelando backup..."
                self.page.update()
            else:
                dlg.open = False
                self.page.update()

        def do_start(e):
            btn_start.disabled = True
            btn_cancel.text = "Cancelar"
            self.page.update()

            def run_worker():
                self.active_backup_engine = PartitionBackup(self.session)
                try:
                    self.active_backup_engine.backup_partition(
                        partition=partition,
                        output_file_path=output_file,
                        progress_callback=on_progress,
                    )
                except Exception as ex:
                    logbus.error(f"Erro ao ler partição: {ex}")
                    progress_text.value = f"Erro: {ex}"
                    self.page.update()

            threading.Thread(target=run_worker, daemon=True).start()

        btn_cancel.on_click = do_cancel
        btn_start.on_click = do_start

        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    def open_write_dialog(self, partition: PartitionEntry):
        """
        Open Write/Flash dialog enforcing strict warnings, size checks,
        and explicit confirmation gates.
        """
        is_crit = partition.name.lower() in CRITICAL_PARTITIONS or "gpt" in partition.name.lower()
        selected_file_path = [None]

        lbl_selected_file = ft.Text("Nenhum arquivo selecionado.", size=12, color=ft.Colors.GREY_400)
        lbl_validation = ft.Text("", size=12)
        chk_confirm = ft.Checkbox(label="Compreendo que esta operação grava diretamente no hardware.")
        chk_critical = ft.Checkbox(
            label="CONFIRMO A GRAVAÇÃO NA PARTIÇÃO CRÍTICA DO SISTEMA.",
            visible=is_crit,
        )
        chk_reset = ft.Checkbox(label="Reiniciar dispositivo ao concluir gravação", value=False)

        progress_bar = ft.ProgressBar(value=0.0, color=ft.Colors.ORANGE_400, bgcolor=ft.Colors.GREY_800, visible=False)
        progress_text = ft.Text("", size=12, font_family="monospace")

        btn_pick = ft.ElevatedButton("Selecionar Arquivo .img", icon=ft.Icons.FOLDER_OPEN)
        btn_cancel = ft.TextButton("Cancelar")
        btn_write = ft.ElevatedButton("GRAVAR IMAGEM", bgcolor=ft.Colors.RED_800, color=ft.Colors.WHITE, disabled=True)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                spacing=8,
                controls=[
                    ft.Icon(ft.Icons.WARNING_ROUNDED, color=ft.Colors.RED_400),
                    ft.Text(f"Gravação: {partition.name}"),
                ],
            ),
            content=ft.Container(
                width=500,
                content=ft.Column(
                    main_axis_size=ft.MainAxisSize.MIN,
                    spacing=12,
                    controls=[
                        ft.Text(
                            f"DISPOSITIVO: {self.session.chipset_info.msm_name or 'Qualcomm EDL'}\n"
                            f"PARTIÇÃO: {partition.name} (LUN {partition.lun})\n"
                            f"CAPACIDADE DA PARTIÇÃO: {partition.size_formatted}",
                            weight=ft.FontWeight.W_500,
                        ),
                        ft.Container(
                            bgcolor=ft.Colors.RED_950,
                            padding=8,
                            border_radius=6,
                            border=ft.border.all(1, ft.Colors.RED_700),
                            content=ft.Text(
                                "ATENÇÃO: Esta operação grava diretamente no armazenamento do dispositivo. "
                                "A gravação de arquivos inválidos pode corromper o aparelho.",
                                color=ft.Colors.RED_200,
                                size=12,
                                weight=ft.FontWeight.BOLD,
                            ),
                        ),
                        ft.Row(controls=[btn_pick, lbl_selected_file]),
                        lbl_validation,
                        chk_confirm,
                        chk_critical,
                        chk_reset,
                        progress_bar,
                        progress_text,
                    ],
                ),
            ),
            actions=[btn_cancel, btn_write],
        )

        def update_button_state():
            has_file = selected_file_path[0] is not None
            confirmed = chk_confirm.value
            crit_confirmed = (not is_crit) or chk_critical.value
            btn_write.disabled = not (has_file and confirmed and crit_confirmed)
            self.page.update()

        chk_confirm.on_change = lambda e: update_button_state()
        chk_critical.on_change = lambda e: update_button_state()

        def on_file_selected(e: ft.FilePickerResultEvent):
            if e.files:
                path = e.files[0].path
                selected_file_path[0] = path
                lbl_selected_file.value = os.path.basename(path)

                writer = PartitionWriter(self.session)
                val = writer.validate_image(path, partition)
                if not val.is_valid:
                    lbl_validation.value = f"❌ {val.error}"
                    lbl_validation.color = ft.Colors.RED_400
                    selected_file_path[0] = None
                else:
                    lbl_validation.value = f"✅ Imagem válida: {val.image_size_bytes / (1024*1024):.2f} MB ({val.sectors_needed} setores)"
                    lbl_validation.color = ft.Colors.GREEN_400
                update_button_state()

        btn_pick.on_click = lambda e: self.file_picker.pick_files(
            dialog_title="Selecionar imagem de partição (.img)",
            allowed_extensions=["img", "bin"],
        )
        self.file_picker.on_result = on_file_selected

        def on_write_progress(p: WriteProgress):
            progress_bar.value = p.percentage / 100.0
            progress_text.value = f"{p.bytes_written / (1024*1024):.2f} MB / {p.bytes_total / (1024*1024):.2f} MB ({p.percentage:.1f}%) | {p.speed_formatted} | ETA {p.eta_formatted}"
            if p.is_complete:
                progress_text.value = "✅ Gravação concluída com sucesso!"
                btn_cancel.text = "Concluir"
                btn_write.visible = False
            if p.error:
                progress_text.value = f"❌ Erro na gravação: {p.error}"
            self.page.update()

        def do_write(e):
            if not selected_file_path[0]:
                return
            btn_write.disabled = True
            btn_pick.disabled = True
            btn_cancel.text = "Cancelar"
            progress_bar.visible = True
            self.page.update()

            def run_writer_worker():
                self.active_writer_engine = PartitionWriter(self.session)
                try:
                    self.active_writer_engine.write_partition(
                        image_path=selected_file_path[0],
                        partition=partition,
                        user_confirmed=True,
                        extra_critical_confirmed=chk_critical.value,
                        reset_on_finish=chk_reset.value,
                        progress_callback=on_write_progress,
                    )
                except Exception as ex:
                    logbus.error(f"Erro fatal ao gravar partição: {ex}")
                    progress_text.value = f"Erro: {ex}"
                    self.page.update()

            threading.Thread(target=run_writer_worker, daemon=True).start()

        def do_cancel(e):
            if self.active_writer_engine and self.active_writer_engine.is_running:
                self.active_writer_engine.request_cancel()
                progress_text.value = "Cancelando após lote atual..."
                self.page.update()
            else:
                dlg.open = False
                self.page.update()

        btn_write.on_click = do_write
        btn_cancel.on_click = do_cancel

        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    def on_backup_selected_click(self, e):
        """Batch backup all selected partitions into Download folder."""
        if not self.selected_partitions:
            snack = ft.SnackBar(ft.Text("Nenhuma partição selecionada para backup."))
            self.page.overlay.append(snack)
            snack.open = True
            self.page.update()
            return

        selected_parts = [
            p for p in self.session.partition_manager.all()
            if f"{p.lun}_{p.name}" in self.selected_partitions
        ]

        dest_dir = f"/storage/emulated/0/Download/edl_backup_{int(os.getpid())}"
        os.makedirs(dest_dir, exist_ok=True)

        logbus.session(f"Iniciando backup em lote de {len(selected_parts)} partições para {dest_dir}...")

        def batch_worker():
            backup_engine = PartitionBackup(self.session)
            for part in selected_parts:
                out_path = os.path.join(dest_dir, f"{part.name}.img")
                try:
                    backup_engine.backup_partition(part, out_path)
                except Exception as ex:
                    logbus.error(f"Falha ao realizar backup de {part.name}: {ex}")
            # Also save metadata
            backup_engine.save_device_metadata(dest_dir)
            logbus.session("Backup em lote finalizado.")

        threading.Thread(target=batch_worker, daemon=True).start()
