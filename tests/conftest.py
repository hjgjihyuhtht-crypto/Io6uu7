"""
tests.conftest
Pytest fixtures for Qualcomm EDL Android test suite.
"""

import os
import sys
import pytest

# Ensure root is in sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from tests.fake_backend import FakeAndroidUsbBackend
from core.session import EDLSession


@pytest.fixture
def fake_backend():
    return FakeAndroidUsbBackend(permission_granted=True, device_connected=True)


@pytest.fixture
def fake_session(fake_backend):
    session = EDLSession(backend=fake_backend, memory_type="ufs")
    return session
