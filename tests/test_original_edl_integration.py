#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests.test_original_edl_integration
Verifies seamless compatibility between AndroidUsbTransport and original
bkerler/edl classes without modifying upstream protocol implementations.
"""

import logging
from tests.fake_backend import FakeUsbDeviceConnection, FakeUsbEndpoint, make_fake_sahara_hello_pkt
from android_usb.transport import AndroidUsbTransport
from edlclient.Library.sahara import sahara
from edlclient.Library.gpt import gpt
from edlclient.Config.qualcomm_config import msmids


def test_sahara_connect_with_android_transport():
    conn = FakeUsbDeviceConnection()
    ep_in = FakeUsbEndpoint(address=0x81, direction=128)
    ep_out = FakeUsbEndpoint(address=0x01, direction=0)
    transport = AndroidUsbTransport(conn, interface=0, ep_in=ep_in, ep_out=ep_out)

    # Queue standard Sahara hello packet
    hello_pkt = make_fake_sahara_hello_pkt(version=2)
    conn.queue_incoming_data(hello_pkt)

    s = sahara(cdc=transport, loglevel=logging.WARNING)
    res = s.connect()

    assert res is not None
    assert res["mode"] == "sahara"
    assert s.version == 2


def test_msmids_mapping():
    assert 0x000460E1 in msmids
    assert "MSM8953" in msmids[0x000460E1]


def test_gpt_structure_instantiation():
    g = gpt(num_part_entries=128, part_entry_size=128, part_entry_start_lba=2)
    assert g.num_part_entries == 128
    assert g.part_entry_size == 128
