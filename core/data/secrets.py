import base64
import ctypes
import os


DPAPI_PREFIX = "dpapi:"


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


_IS_WINDOWS = os.name == "nt"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01

if _IS_WINDOWS:
    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32
else:
    _crypt32 = None
    _kernel32 = None


def is_encrypted_secret(value):
    return isinstance(value, str) and value.startswith(DPAPI_PREFIX)


def _blob_from_bytes(data):
    if not data:
        return DATA_BLOB(0, None), None
    buf = ctypes.create_string_buffer(data, len(data))
    blob = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    return blob, buf


def _blob_to_bytes(blob):
    if blob.cbData == 0:
        return b""
    return ctypes.string_at(blob.pbData, blob.cbData)


def encrypt_secret(value):
    if value is None or value == "":
        return value
    if is_encrypted_secret(value):
        return value
    if not _IS_WINDOWS:
        return value

    plain = value.encode("utf-8")
    in_blob, in_buf = _blob_from_bytes(plain)
    out_blob = DATA_BLOB()

    try:
        ok = _crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not ok:
            raise ctypes.WinError()

        encrypted = _blob_to_bytes(out_blob)
        encoded = base64.b64encode(encrypted).decode("ascii")
        return DPAPI_PREFIX + encoded
    finally:
        # Keep input buffer alive for the API call.
        _ = in_buf
        if out_blob.pbData:
            _kernel32.LocalFree(out_blob.pbData)


def decrypt_secret(value):
    if value is None or value == "":
        return value
    if not isinstance(value, str):
        return value
    if not is_encrypted_secret(value):
        return value
    if not _IS_WINDOWS:
        return value

    payload = value[len(DPAPI_PREFIX) :]
    encrypted = base64.b64decode(payload.encode("ascii"))
    in_blob, in_buf = _blob_from_bytes(encrypted)
    out_blob = DATA_BLOB()

    try:
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not ok:
            raise ctypes.WinError()

        plain = _blob_to_bytes(out_blob)
        return plain.decode("utf-8")
    finally:
        _ = in_buf
        if out_blob.pbData:
            _kernel32.LocalFree(out_blob.pbData)
