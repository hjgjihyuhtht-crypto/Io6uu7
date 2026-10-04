#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui.log_view
Real-time diagnostic log viewer for Flet with category filtering and export.
"""

import flet as ft
from core.logbus import logbus, LogEntry


class LogView(ft.Container):
    """Component displaying live streaming logs from EDL operations."""

    def __init__(self, page: ft.Page):
        super().__init__()
        self.page = page
        self.expand = True
        self.padding = 10

        self.current_filter = "ALL"
        self.log_list = ft.ListView(
            expand=True,
            spacing=4,
            auto_scroll=True,
        )

        self.filter_buttons = ft.Row(
            wrap=True,
            spacing=8,
            controls=[
                ft.ElevatedButton("TODOS", on_click=lambda e: self.set_filter("ALL")),
                ft.OutlinedButton("USB", on_click=lambda e: self.set_filter("USB")),
                ft.OutlinedButton("SAHARA", on_click=lambda e: self.set_filter("SAHARA")),
                ft.OutlinedButton("FIREHOSE", on_click=lambda e: self.set_filter("FIREHOSE")),
                ft.OutlinedButton("GPT", on_click=lambda e: self.set_filter("GPT")),
                ft.OutlinedButton("READ", on_click=lambda e: self.set_filter("READ")),
                ft.OutlinedButton("WRITE", on_click=lambda e: self.set_filter("WRITE")),
                ft.OutlinedButton("ERROS", on_click=lambda e: self.set_filter("ERROR")),
            ],
        )

        self.action_bar = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                self.filter_buttons,
                ft.Row(
                    controls=[
                        ft.IconButton(
                            icon=ft.Icons.DELETE_SWEEP,
                            tooltip="Limpar Logs",
                            on_click=self.clear_logs,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.SAVE_ALT,
                            tooltip="Exportar logs.txt",
                            on_click=self.export_logs,
                        ),
                    ]
                ),
            ],
        )

        self.content = ft.Column(
            expand=True,
            spacing=10,
            controls=[
                self.action_bar,
                ft.Container(
                    expand=True,
                    bgcolor=ft.Colors.BLACK,
                    border_radius=8,
                    padding=10,
                    border=ft.border.all(1, ft.Colors.BLUE_GREY_900),
                    content=self.log_list,
                ),
            ],
        )

        # Register to LogBus
        logbus.subscribe(self.on_log_entry)
        self.load_existing_history()

    def set_filter(self, category: str):
        self.current_filter = category
        self.refresh_display()

    def load_existing_history(self):
        for entry in logbus.get_history():
            self._append_entry_ui(entry)

    def on_log_entry(self, entry: LogEntry):
        self._append_entry_ui(entry)
        try:
            self.page.update()
        except Exception:
            pass

    def _append_entry_ui(self, entry: LogEntry):
        if self.current_filter != "ALL" and entry.category != self.current_filter:
            return

        color_map = {
            "USB": ft.Colors.CYAN_300,
            "SAHARA": ft.Colors.AMBER_400,
            "FIREHOSE": ft.Colors.GREEN_400,
            "GPT": ft.Colors.PURPLE_300,
            "READ": ft.Colors.LIGHT_BLUE_300,
            "WRITE": ft.Colors.ORANGE_400,
            "ERROR": ft.Colors.RED_400,
            "SESSION": ft.Colors.TEAL_300,
        }
        color = color_map.get(entry.category, ft.Colors.WHITE)

        row = ft.Text(
            f"[{entry.timestamp}] [{entry.category}] {entry.message}",
            color=color,
            size=12,
            font_family="monospace",
            selectable=True,
        )
        self.log_list.controls.append(row)

    def refresh_display(self):
        self.log_list.controls.clear()
        for entry in logbus.get_history():
            self._append_entry_ui(entry)
        try:
            self.page.update()
        except Exception:
            pass

    def clear_logs(self, e):
        logbus.clear()
        self.log_list.controls.clear()
        self.page.update()

    def export_logs(self, e):
        default_path = "/storage/emulated/0/Download/edl_logs.txt"
        ok = logbus.export_to_file(default_path)
        if ok:
            snack = ft.SnackBar(ft.Text(f"Logs salvos em {default_path}"))
        else:
            snack = ft.SnackBar(ft.Text("Erro ao salvar logs."))
        self.page.overlay.append(snack)
        snack.open = True
        self.page.update()
