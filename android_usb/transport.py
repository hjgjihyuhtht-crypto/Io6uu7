#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
android_usb.transport
Android USB Transport providing the CDC interface contract expected by
bkerler/edl (Sahara, Firehose, Streaming).
"""

import time
import logging
from typing import Optional, Union, Any

logger = logging.getLogger("edl_transport")

MAX_USB_BULK_BUFFER_SIZE = 1048576  # 1 MB
DEFAULT_TIMEOUT_MS = 2000
USB_ENDPOINT_XFER_BULK = 2
USB_DIR_IN = 128
USB_DIR_OUT = 0


class AndroidUsbTransport:
    """
    Implements the CDC transport interface required by edlclient:
    - usbread()
    - write()
    - usbwrite()
    - usbreadwrite()
    - flush()
    - close()
    """

    def __init__(
        self,
        connection: Any,
        interface: Any,
        ep_in: Any,
        ep_out: Any,
        maxsize: int = MAX_USB_BULK_BUFFER_SIZE,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        loglevel: int = logging.INFO,
    ):
        self.connection = connection
        self.interface = interface
        self.ep_in = ep_in
        self.ep_out = ep_out
        self.maxsize = maxsize
        self.timeout = timeout_ms
        self.loglevel = loglevel

        self.connected = True
        self.xmlread = False
        self.is_serial = False

        self._read_buffer = bytearray()
        self._on_disconnect_callback = None

    def set_disconnect_callback(self, callback):
        self._on_disconnect_callback = callback

    def _notify_disconnect(self, reason: str = "Connection lost"):
        if self.connected:
            self.connected = False
            logger.warning("USB device disconnected: %s", reason)
            if self._on_disconnect_callback:
                try:
                    self._on_disconnect_callback(reason)
                except Exception:
                    pass

    def flush(self):
        """Flush internal buffers."""
        self._read_buffer.clear()

    def write(self, command: Union[bytes, bytearray, str], pktsize: Optional[int] = None) -> int:
        """
        Write bytes to bulk OUT endpoint.
        Returns total bytes transferred.
        """
        if not self.connected:
            raise ConnectionError("USB device is not connected.")

        if isinstance(command, str):
            command = command.encode("utf-8")
        elif not isinstance(command, (bytes, bytearray)):
            command = bytes(command)

        if len(command) == 0:
            return 0

        if pktsize is None or pktsize <= 0:
            pktsize = self.maxsize

        total_written = 0
        total_len = len(command)

        while total_written < total_len:
            chunk_len = min(pktsize, total_len - total_written)
            chunk = command[total_written : total_written + chunk_len]

            # Native bulk transfer
            written = self._bulk_write_raw(chunk, self.timeout)
            if written < 0:
                self._notify_disconnect("bulkTransfer OUT failed")
                raise ConnectionError(f"USB bulkTransfer OUT failed (code: {written})")
            total_written += written

        return total_written

    def usbwrite(self, data: Union[bytes, bytearray, str], pktsize: Optional[int] = None) -> int:
        """Alias expected by bkerler/edl."""
        return self.write(data, pktsize=pktsize)

    def usbread(self, resplen: Optional[int] = None, timeout: int = 0, length: Optional[int] = None, **kwargs) -> bytearray:
        """
        Read up to resplen bytes from bulk IN endpoint.
        Supports both resplen and length keyword arguments for complete edlclient compatibility.
        """
        if not self.connected:
            raise ConnectionError("USB device is not connected.")

        if resplen is None:
            resplen = length

        if timeout <= 0:
            timeout_ms = self.timeout
        elif timeout < 100:
            # If timeout was provided in seconds (common in bkerler/edl)
            timeout_ms = int(timeout * 1000)
        else:
            timeout_ms = int(timeout)

        if resplen is None or resplen <= 0:
            resplen = self.maxsize

        res = bytearray()

        # If data already cached in buffer
        if self._read_buffer:
            take = min(len(self._read_buffer), resplen)
            res.extend(self._read_buffer[:take])
            self._read_buffer = self._read_buffer[take:]
            if len(res) >= resplen:
                return res

        # For XML response reading
        if self.xmlread:
            return self._read_xml(timeout_ms)

        # Bulk read loop
        start_time = time.time()
        while len(res) < resplen:
            needed = resplen - len(res)
            chunk_size = min(needed, self.maxsize)

            raw_chunk = self._bulk_read_raw(chunk_size, timeout_ms)
            if not raw_chunk:
                # Timed out or no data
                break
            res.extend(raw_chunk)

            # Prevent infinite loop if timeout exceeded
            if (time.time() - start_time) * 1000 > timeout_ms:
                break

        return res

    def read(self, resplen: Optional[int] = None, timeout: int = 0, length: Optional[int] = None, **kwargs) -> bytearray:
        """Alias for usbread()."""
        return self.usbread(resplen=resplen, timeout=timeout, length=length, **kwargs)

    def usbreadwrite(self, data: Union[bytes, bytearray, str], resplen: int) -> bytearray:
        """Write data and immediately read response."""
        self.usbwrite(data)
        return self.usbread(resplen)

    def _read_xml(self, timeout_ms: int) -> bytearray:
        """Specialized reader for XML firehose responses."""
        res = bytearray()
        start = time.time()

        while True:
            chunk = self._bulk_read_raw(4096, timeout_ms)
            if chunk:
                res.extend(chunk)
                if b"</response>" in res or b"/>" in res or b"</data>" in res or b"</log>" in res:
                    break
            else:
                if (time.time() - start) * 1000 > timeout_ms:
                    break
            time.sleep(0.005)

        return res

    def _bulk_write_raw(self, data: Union[bytes, bytearray], timeout_ms: int) -> int:
        """Performs raw write using UsbDeviceConnection or mock connection."""
        conn = self.connection
        ep = self.ep_out

        # Mock connection support (implements bulkTransfer or write)
        if hasattr(conn, "bulkTransfer"):
            # PyJNIus requires byte array or byte string
            try:
                # If ep has native object
                native_ep = getattr(ep, "raw_endpoint", ep)
                return int(conn.bulkTransfer(native_ep, bytes(data), len(data), timeout_ms))
            except Exception as e:
                logger.error("bulkTransfer OUT error: %s", e)
                return -1
        elif hasattr(conn, "write"):
            # Mock or pyusb-like
            try:
                res = conn.write(ep, data, timeout=timeout_ms)
                return len(data) if res is None else res
            except Exception as e:
                logger.error("Connection write error: %s", e)
                return -1
        else:
            raise NotImplementedError("Connection object does not support bulkTransfer or write.")

    def _bulk_read_raw(self, length: int, timeout_ms: int) -> bytes:
        """Performs raw read using UsbDeviceConnection or mock connection."""
        conn = self.connection
        ep = self.ep_in

        if hasattr(conn, "bulkTransfer"):
            try:
                native_ep = getattr(ep, "raw_endpoint", ep)
                buf = bytearray(length)
                read_bytes = conn.bulkTransfer(native_ep, buf, length, timeout_ms)
                if read_bytes < 0:
                    return b""
                return bytes(buf[:read_bytes])
            except Exception as e:
                logger.error("bulkTransfer IN error: %s", e)
                return b""
        elif hasattr(conn, "read"):
            try:
                res = conn.read(ep, length, timeout=timeout_ms)
                return bytes(res)
            except Exception as e:
                # Timeout is normal in polling
                return b""
        else:
            raise NotImplementedError("Connection object does not support bulkTransfer or read.")

    def close(self):
        """Release interfaces and close connection."""
        if not self.connected:
            return

        self.connected = False
        try:
            if hasattr(self.connection, "releaseInterface") and self.interface:
                native_iface = getattr(self.interface, "raw_interface", self.interface)
                self.connection.releaseInterface(native_iface)
        except Exception as e:
            logger.debug("Error releasing interface: %s", e)

        try:
            if hasattr(self.connection, "close"):
                self.connection.close()
        except Exception as e:
            logger.debug("Error closing connection: %s", e)

        logger.info("AndroidUsbTransport closed.")
