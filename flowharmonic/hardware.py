"""ALSA playback discovery; no capture, mixer changes, or default-device changes."""
import ctypes
import ctypes.util
import hashlib
import re
from pathlib import Path


def playback_outputs(proc=Path('/proc/asound'), sys=Path('/sys/class/sound')):
    outputs = []
    for card in sorted(proc.glob('card[0-9]*')):
        if not card.is_dir() or not re.fullmatch(r'card\d+', card.name):
            continue
        card_id = (card / 'id').read_text().strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]+', card_id):
            continue
        hardware_path = str((sys / card.name / 'device').resolve())
        # Physical connection path remains stable when ALSA card numbers change.
        if not (sys / card.name / 'device').exists():
            hardware_path = card_id
        elds = [p.read_text() for p in card.glob('eld*')]
        digital_connected = not elds or any(re.search(r'monitor_present\s+1', text) and re.search(r'eld_valid\s+1', text) for text in elds)
        for pcm in sorted(card.glob('pcm*p')):
            match = re.fullmatch(r'pcm(\d+)p', pcm.name)
            if not match or not (pcm / 'info').exists():
                continue
            device = int(match[1])
            info = dict(line.split(':', 1) for line in (pcm / 'info').read_text().splitlines() if ':' in line)
            label = info.get('name', info.get('id', f'Output {device}')).strip()
            digital = bool(re.search(r'HDMI|DisplayPort', label, re.I))
            stable = hashlib.sha256(f'{hardware_path}:{device}'.encode()).hexdigest()[:20]
            outputs.append({'key': stable, 'name': label, 'device': f'plughw:CARD={card_id},DEV={device}',
                            'connected': digital_connected if digital else True})
    return outputs


def probe_output(device):
    """Open and validate stereo playback without writing any frames."""
    name = ctypes.util.find_library('asound')
    if not name:
        return 'The local audio driver library is unavailable.'
    alsa = ctypes.CDLL(name)
    alsa.snd_pcm_open.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
    alsa.snd_pcm_open.restype = ctypes.c_int
    alsa.snd_pcm_set_params.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_int, ctypes.c_uint]
    alsa.snd_pcm_set_params.restype = ctypes.c_int
    alsa.snd_pcm_close.argtypes = [ctypes.c_void_p]
    handle = ctypes.c_void_p()
    result = alsa.snd_pcm_open(ctypes.byref(handle), device.encode(), 0, 1)
    if result < 0:
        return 'This output is in use or cannot be opened. It will be checked again automatically.'
    try:
        # S16_LE, RW_INTERLEAVED, stereo, 48 kHz, ALSA conversion, 100 ms latency.
        result = alsa.snd_pcm_set_params(handle, 2, 3, 2, 48000, 1, 100000)
        if result < 0:
            return 'This output is disconnected or does not support stereo playback.'
        return ''
    finally:
        alsa.snd_pcm_close(handle)


def capture_inputs(proc=Path('/proc/asound'), sys=Path('/sys/class/sound')):
    """Stable physical ALSA identities; never use the default capture device."""
    inputs=[]
    for card in sorted(proc.glob('card[0-9]*')):
        if not card.is_dir() or not re.fullmatch(r'card\d+',card.name):continue
        card_id=(card/'id').read_text().strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]+',card_id):continue
        physical=str((sys/card.name/'device').resolve()) if (sys/card.name/'device').exists() else card_id
        for pcm in sorted(card.glob('pcm*c')):
            match=re.fullmatch(r'pcm(\d+)c',pcm.name)
            if not match or not (pcm/'info').exists():continue
            info=dict(line.split(':',1) for line in (pcm/'info').read_text().splitlines() if ':' in line)
            device=int(match[1]);# A different USB product in the same port must not inherit capture.
            fingerprint=[physical,card_id]
            hardware=(sys/card.name/'device').resolve()
            for parent in [hardware,*hardware.parents]:
                if (parent/'idVendor').exists() and (parent/'idProduct').exists():
                    vendor=(parent/'idVendor').read_text().strip();product=(parent/'idProduct').read_text().strip()
                    serial=(parent/'serial').read_text().strip() if (parent/'serial').exists() else ''
                    fingerprint=['usb',vendor,product,serial] if serial else [physical,card_id,vendor,product]
                    break
            key=hashlib.sha256((':'.join(fingerprint)+f':capture:{device}').encode()).hexdigest()[:20]
            inputs.append({'key':'alsa:'+key,'name':card_id+' — '+info.get('name','Audio input').strip(),
                           'device':f'plughw:CARD={card_id},DEV={device}','backend':'alsa','channels':capture_channels(f'hw:CARD={card_id},DEV={device}')})
    return inputs


def capture_channels(device):
    """Read hardware channel capability without recording or changing a mixer."""
    name=ctypes.util.find_library('asound')
    if not name:return 0
    alsa=ctypes.CDLL(name);handle=ctypes.c_void_p();params=ctypes.c_void_p()
    alsa.snd_pcm_open.argtypes=[ctypes.POINTER(ctypes.c_void_p),ctypes.c_char_p,ctypes.c_int,ctypes.c_int]
    alsa.snd_pcm_hw_params_malloc.argtypes=[ctypes.POINTER(ctypes.c_void_p)]
    alsa.snd_pcm_hw_params_any.argtypes=[ctypes.c_void_p,ctypes.c_void_p]
    alsa.snd_pcm_hw_params_get_channels_max.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint)]
    alsa.snd_pcm_hw_params_free.argtypes=[ctypes.c_void_p];alsa.snd_pcm_close.argtypes=[ctypes.c_void_p]
    if alsa.snd_pcm_open(ctypes.byref(handle),device.encode(),1,1)<0:return 0
    try:
        if alsa.snd_pcm_hw_params_malloc(ctypes.byref(params))<0:return 0
        try:
            if alsa.snd_pcm_hw_params_any(handle,params)<0:return 0
            channels=ctypes.c_uint()
            if alsa.snd_pcm_hw_params_get_channels_max(params,ctypes.byref(channels))<0:return 0
            return min(32,channels.value)
        finally:alsa.snd_pcm_hw_params_free(params)
    finally:alsa.snd_pcm_close(handle)
