"""Windows Master Audio Ducking (temporarily lower/mute speaker output).

Useful for online classes, video calls, or meetings so playback through speakers
does not bleed into the microphone during speech recognition.
"""
import ctypes
from ctypes import POINTER, HRESULT, Structure, byref, c_float, c_int, c_ulong, c_void_p, wintypes
import threading

ole32 = ctypes.windll.ole32


class GUID(Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]


ole32.CLSIDFromString.argtypes = [wintypes.LPCWSTR, POINTER(GUID)]


def _guid(s: str) -> GUID:
    g = GUID()
    ole32.CLSIDFromString(s, byref(g))
    return g


CLSID_MMDeviceEnumerator = _guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
IID_IMMDeviceEnumerator = _guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
IID_IAudioEndpointVolume = _guid("{5CDF2C82-841E-4546-9722-0CF74078229A}")


class VolumeManager:
    """Controls the Windows default audio playback endpoint volume."""

    def __init__(self):
        self._lock = threading.Lock()
        self._is_ducked = False
        self._prev_volume = None
        self._prev_mute = None

    def _open_endpoint(self):
        """Returns (pVol, release_callback) or (None, None). Caller must call release_callback()."""
        hr_co = ole32.CoInitialize(None)
        co_init = hr_co in (0, 1)  # S_OK (0) or S_FALSE (1)

        pEnum = c_void_p()
        hr = ole32.CoCreateInstance(
            byref(CLSID_MMDeviceEnumerator),
            None,
            1,  # CLSCTX_INPROC_SERVER
            byref(IID_IMMDeviceEnumerator),
            byref(pEnum),
        )
        if hr != 0 or not pEnum.value:
            if co_init:
                ole32.CoUninitialize()
            return None, None

        vtbl_enum = POINTER(c_void_p).from_address(pEnum.value)
        GetDefault = ctypes.WINFUNCTYPE(HRESULT, c_void_p, c_int, c_int, POINTER(c_void_p))(vtbl_enum[4])
        Release_enum = ctypes.WINFUNCTYPE(c_ulong, c_void_p)(vtbl_enum[2])

        pDev = c_void_p()
        hr = GetDefault(pEnum, 0, 1, byref(pDev))  # eRender=0, eMultimedia=1
        Release_enum(pEnum)

        if hr != 0 or not pDev.value:
            if co_init:
                ole32.CoUninitialize()
            return None, None

        vtbl_dev = POINTER(c_void_p).from_address(pDev.value)
        Activate = ctypes.WINFUNCTYPE(
            HRESULT, c_void_p, POINTER(GUID), wintypes.DWORD, c_void_p, POINTER(c_void_p)
        )(vtbl_dev[3])
        Release_dev = ctypes.WINFUNCTYPE(c_ulong, c_void_p)(vtbl_dev[2])

        pVol = c_void_p()
        hr = Activate(pDev, byref(IID_IAudioEndpointVolume), 1, None, byref(pVol))
        Release_dev(pDev)

        if hr != 0 or not pVol.value:
            if co_init:
                ole32.CoUninitialize()
            return None, None

        def cleanup():
            try:
                vtbl_vol = POINTER(c_void_p).from_address(pVol.value)
                Release_vol = ctypes.WINFUNCTYPE(c_ulong, c_void_p)(vtbl_vol[2])
                Release_vol(pVol)
            finally:
                if co_init:
                    ole32.CoUninitialize()

        return pVol, cleanup

    def duck(self, target_percent: int = 15):
        """Temporarily duck or mute output volume. target_percent=0 mutes completely."""
        with self._lock:
            if self._is_ducked:
                return
            pVol, cleanup = self._open_endpoint()
            if not pVol:
                return
            try:
                vtbl_vol = POINTER(c_void_p).from_address(pVol.value)
                GetMasterVolume = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_float))(vtbl_vol[9])
                SetMasterVolume = ctypes.WINFUNCTYPE(HRESULT, c_void_p, c_float, c_void_p)(vtbl_vol[7])
                GetMute = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(wintypes.BOOL))(vtbl_vol[15])
                SetMute = ctypes.WINFUNCTYPE(HRESULT, c_void_p, wintypes.BOOL, c_void_p)(vtbl_vol[14])

                curr_vol = c_float()
                GetMasterVolume(pVol, byref(curr_vol))
                curr_mute = wintypes.BOOL()
                GetMute(pVol, byref(curr_mute))

                self._prev_volume = curr_vol.value
                self._prev_mute = bool(curr_mute.value)
                self._is_ducked = True

                if target_percent <= 0:
                    SetMute(pVol, True, None)
                else:
                    target_scalar = max(0.0, min(1.0, target_percent / 100.0))
                    # Only lower volume if current is higher than target
                    if curr_vol.value > target_scalar:
                        SetMasterVolume(pVol, target_scalar, None)
                    if self._prev_mute:
                        # If previously muted, keep it muted
                        pass
            except Exception as e:
                print(f"[volume] duck failed: {e}", flush=True)
            finally:
                cleanup()

    def restore(self):
        """Restore volume and mute status to their pre-duck states."""
        with self._lock:
            if not self._is_ducked:
                return
            pVol, cleanup = self._open_endpoint()
            if not pVol:
                self._is_ducked = False
                return
            try:
                vtbl_vol = POINTER(c_void_p).from_address(pVol.value)
                SetMasterVolume = ctypes.WINFUNCTYPE(HRESULT, c_void_p, c_float, c_void_p)(vtbl_vol[7])
                SetMute = ctypes.WINFUNCTYPE(HRESULT, c_void_p, wintypes.BOOL, c_void_p)(vtbl_vol[14])

                if self._prev_volume is not None:
                    SetMasterVolume(pVol, self._prev_volume, None)
                if self._prev_mute is not None:
                    SetMute(pVol, self._prev_mute, None)
            except Exception as e:
                print(f"[volume] restore failed: {e}", flush=True)
            finally:
                self._is_ducked = False
                self._prev_volume = None
                self._prev_mute = None
                cleanup()
