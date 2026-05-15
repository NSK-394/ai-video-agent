"""
semantic_classifier.py
-----------------------
Classifies video segments via OpenCV heuristics (no ML model).
cv2 is lazy-imported inside functions to keep module-level load fast.

Label taxonomy
--------------
motion_speed  : static | slow_motion | medium | fast_motion  (MAD thresholds)
shot_scale    : close_up | medium_shot | wide_shot            (edge density)
tone          : dark | bright | cinematic | flat              (brightness/contrast)
energy_level  : calm | neutral | intense                      (motion)
color_mood    : warm | cool | neutral                         (mean R vs B)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List

from utils.logger import get_logger

logger = get_logger(__name__)

# -- Thresholds ---------------------------------------------------------------
_M_STATIC, _M_SLOW, _M_MED = 3.0, 8.0, 20.0
_E_CLOSE, _E_WIDE = 0.12, 0.04
_B_DARK, _B_BRIGHT, _C_CIN = 60.0, 170.0, 45.0
_EG_CALM, _EG_NEUT = 5.0, 15.0
_COLOR_OFF = 20.0
_DW = 160  # downscale width for MAD


# -- Data model ---------------------------------------------------------------

@dataclass
class SemanticProfile:
    """Per-second semantic snapshot of a video clip."""
    second: int
    start_time: float
    end_time: float
    motion_score: float    # MAD
    brightness: float      # mean pixel 0-255
    contrast: float        # std-dev of pixel values
    edge_density: float    # canny edges / total pixels
    saturation: float      # mean HSV-S 0-255
    motion_speed: str
    shot_scale: str
    tone: str
    energy_level: str
    color_mood: str
    energy_score: float    # normalised 0-1 composite
    cinematic_score: float # contrast*(1-overexposed)*saturation factor


# -- Label helpers ------------------------------------------------------------

def _labels(mad, edge, br, con, sat, mr, mb):
    """Return (motion_speed, shot_scale, tone, energy_level, color_mood)."""
    ms = ("static" if mad < _M_STATIC else
          "slow_motion" if mad < _M_SLOW else
          "medium" if mad < _M_MED else "fast_motion")
    ss = ("close_up" if edge > _E_CLOSE else
          "wide_shot" if edge < _E_WIDE else "medium_shot")
    tone = ("dark" if br < _B_DARK else
            "bright" if br > _B_BRIGHT else
            "cinematic" if con > _C_CIN else "flat")
    el = "calm" if mad < _EG_CALM else "neutral" if mad < _EG_NEUT else "intense"
    cm = ("warm" if mr > mb + _COLOR_OFF else
          "cool" if mb > mr + _COLOR_OFF else "neutral")
    return ms, ss, tone, el, cm


def _scores(mad, con, sat, br):
    """Return (energy_score, cinematic_score), both in [0,1]."""
    e = min(1.0, mad/30)*0.5 + min(1.0, con/80)*0.3 + min(1.0, sat/255)*0.2
    oe = max(0.0, (br - 200) / 55)
    c = min(1.0, con/80) * (1.0 - oe) * min(1.0, sat/180)
    return round(e, 4), round(max(0.0, min(1.0, c)), 4)


def _resize(cv2, frame, w):
    h, ow = frame.shape[:2]
    return cv2.resize(frame, (w, max(1, int(h * w / max(1, ow)))),
                      interpolation=cv2.INTER_AREA)


# -- Public API ---------------------------------------------------------------

def classify_clip(clip_path: str, sample_every: int = 4) -> List[SemanticProfile]:
    """
    Return one SemanticProfile per second for *clip_path*.
    Empty list on any failure.  cv2 is imported here (lazy).
    """
    import cv2  # noqa: PLC0415

    if not os.path.isfile(clip_path):
        logger.info("semantic_classifier: not found: {}", clip_path)
        return []
    cap = cv2.VideoCapture(clip_path)
    if not cap.isOpened():
        logger.info("semantic_classifier: cannot open: {}", clip_path)
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    profiles: List[SemanticProfile] = []

    for sec in range(int(total / fps) + 1):
        cfi = int(sec * fps) + int(fps / 2)
        if cfi >= total:
            break

        cap.set(cv2.CAP_PROP_POS_FRAMES, float(cfi))
        ok, frame = cap.read()
        if not ok or frame is None:
            break

        small = _resize(cv2, frame, _DW)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        br = float(gray.mean())
        con = float(gray.std())
        edges = cv2.Canny(gray, 50, 150)
        edge_d = float(edges.sum() / 255) / max(1, edges.size)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        sat = float(hsv[:, :, 1].mean())
        mb = float(small[:, :, 0].mean())
        mr = float(small[:, :, 2].mean())

        # MAD over sampled frames in this second
        mads, prev = [], None
        for fi in range(int(sec * fps), min(int((sec+1)*fps), total), max(1, sample_every)):
            cap.set(cv2.CAP_PROP_POS_FRAMES, float(fi))
            ok2, f2 = cap.read()
            if not ok2 or f2 is None:
                continue
            g2 = cv2.cvtColor(_resize(cv2, f2, _DW), cv2.COLOR_BGR2GRAY).astype(float)
            if prev is not None:
                mads.append(float(abs(g2 - prev).mean()))
            prev = g2
        mad = float(sum(mads) / len(mads)) if mads else 0.0

        ms, ss, tone, el, cm = _labels(mad, edge_d, br, con, sat, mr, mb)
        es, cs = _scores(mad, con, sat, br)
        profiles.append(SemanticProfile(
            second=sec, start_time=float(sec), end_time=float(sec+1),
            motion_score=round(mad, 3), brightness=round(br, 2),
            contrast=round(con, 2), edge_density=round(edge_d, 5),
            saturation=round(sat, 2), motion_speed=ms, shot_scale=ss,
            tone=tone, energy_level=el, color_mood=cm,
            energy_score=es, cinematic_score=cs,
        ))

    cap.release()
    logger.info("semantic_classifier: {} profiles for {}",
                len(profiles), os.path.basename(clip_path))
    return profiles


def classify_segment(profiles: List[SemanticProfile],
                     start_time: float, end_time: float) -> dict:
    """
    Aggregate profiles over [start_time, end_time] and return a summary dict.

    Keys: dominant_motion, dominant_shot_scale, dominant_tone,
    dominant_energy, dominant_color_mood, mean_energy_score,
    mean_cinematic_score, tags (list[str]).
    """
    win = [p for p in profiles if p.start_time >= start_time and p.end_time <= end_time]
    if not win:
        win = [p for p in profiles if p.start_time < end_time and p.end_time > start_time]
    if not win:
        logger.info("semantic_classifier: no profiles in [{}, {}]", start_time, end_time)
        return {"dominant_motion": "unknown", "dominant_shot_scale": "unknown",
                "dominant_tone": "unknown", "dominant_energy": "unknown",
                "dominant_color_mood": "unknown",
                "mean_energy_score": 0.5, "mean_cinematic_score": 0.5, "tags": []}

    def _dom(attr):
        counts = {}
        for p in win:
            v = getattr(p, attr)
            counts[v] = counts.get(v, 0) + 1
        return max(counts, key=lambda k: counts[k])

    dm, ds, dt, de, dc = (_dom("motion_speed"), _dom("shot_scale"),
                          _dom("tone"), _dom("energy_level"), _dom("color_mood"))
    me = round(sum(p.energy_score for p in win) / len(win), 4)
    mc = round(sum(p.cinematic_score for p in win) / len(win), 4)

    tags = (
        (["intense"] if de == "intense" else []) +
        (["fast_motion"] if dm == "fast_motion" else []) +
        (["slow_motion"] if dm == "slow_motion" else []) +
        (["close_up"] if ds == "close_up" else []) +
        (["wide_shot"] if ds == "wide_shot" else []) +
        (["cinematic"] if dt == "cinematic" else []) +
        (["calm"] if de == "calm" else []) +
        (["action"] if me >= 0.6 else []) +
        (["static"] if dm == "static" else [])
    )
    return {"dominant_motion": dm, "dominant_shot_scale": ds, "dominant_tone": dt,
            "dominant_energy": de, "dominant_color_mood": dc,
            "mean_energy_score": me, "mean_cinematic_score": mc, "tags": tags}
