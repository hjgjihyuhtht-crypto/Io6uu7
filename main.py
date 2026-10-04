#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py
Main entry point for Qualcomm EDL Android Application using Flet.
"""

import os
import sys

# Ensure parent directory is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import flet as ft
from core.session import EDLSession
from core.logbus import logbus
from ui.main_view import MainView


def main(page: ft.Page):
    page.title = "Qualcomm EDL Android Tool"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 0
    page.spacing = 0

    # Custom theme styling
    page.theme = ft.Theme(
        color_scheme_seed=ft.Colors.CYAN,
        visual_density=ft.VisualDensity.COMPACT,
    )

    # FilePicker for SAF (Storage Access Framework)
    file_picker = ft.FilePicker()
    page.overlay.append(file_picker)

    # Initialize EDL Session
    session = EDLSession()

    # Mount UI
    main_view = MainView(page=page, session=session, file_picker=file_picker)
    page.add(main_view)

    logbus.session("Qualcomm EDL Suite inicializado.")

    # Probe on startup
    try:
        dev = session.detect_device()
        if dev:
            main_view.update_hardware_info()
    except Exception as e:
        logbus.usb(f"Aviso na detecção inicial: {e}")

    page.update()


if __name__ == "__main__":
    ft.app(target=main)
