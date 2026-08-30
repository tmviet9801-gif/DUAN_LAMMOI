"""Điều khiển mute/unmute âm thanh các process Chromium qua Windows Core Audio.

Dùng `pycaw` (wrapper COM của Windows Core Audio) để bật/tắt tiếng NGAY LẬP TỨC
cho các cửa sổ trình duyệt đang mở — đáng tin cậy hơn flag `--mute-audio`
(không phải lúc nào cũng mute được WebAudio của game). Nếu chưa cài `pycaw`,
module vẫn import được và trả 0 (tính năng bị tắt nhẹ nhàng).
"""
import logging

log = logging.getLogger("audio_control")

try:
    import comtypes
    from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume

    _AVAILABLE = True
except Exception as e:  # pragma: no cover - môi trường chưa cài pycaw/comtypes
    comtypes = None
    AudioUtilities = None
    ISimpleAudioVolume = None
    _AVAILABLE = False
    log.warning("pycaw không khả dụng, mute live bị tắt: %s", e)


def set_processes_mute(pids, muted: bool) -> int:
    """Mute/unmute mọi audio session thuộc các pid cho trước.

    Trả về số session đã đổi trạng thái.
    """
    if not _AVAILABLE or not pids:
        return 0
    pids = set(int(p) for p in pids if p)
    if not pids:
        return 0

    try:
        comtypes.CoInitialize()
    except Exception:
        pass

    changed = 0
    try:
        sessions = AudioUtilities.GetAllSessions()
    except Exception as e:
        log.warning("GetAllSessions fail: %s", e)
        sessions = []
    for s in sessions:
        try:
            if s.Process is None or s.Process.pid not in pids:
                continue
            vol = s._ctl.QueryInterface(ISimpleAudioVolume)
            vol.SetMute(1 if muted else 0, None)
            changed += 1
        except Exception:
            continue

    try:
        comtypes.CoUninitialize()
    except Exception:
        pass

    if changed:
        log.info("set mute=%s cho %d audio sessions", muted, changed)
    return changed
