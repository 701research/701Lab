# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
from pathlib import Path
import math

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


def S(v: int | float, scale: int) -> int:
    return int(round(v * scale))


def draw_heart_icon(dr: ImageDraw.ImageDraw, x: int, y: int, size: int, outline, fill=None):
    w = size
    h = size

    rx = int(w * 0.24)
    ry = int(h * 0.24)

    left_cx = x + int(w * 0.30)
    right_cx = x + int(w * 0.70)
    cy = y + int(h * 0.28)

    bottom_x = x + int(w * 0.50)
    bottom_y = y + int(h * 0.98)

    left_shoulder = (x + int(w * 0.08), y + int(h * 0.42))
    right_shoulder = (x + int(w * 0.92), y + int(h * 0.42))

    if fill is not None:
        dr.ellipse([left_cx - rx, cy - ry, left_cx + rx, cy + ry], fill=fill)
        dr.ellipse([right_cx - rx, cy - ry, right_cx + rx, cy + ry], fill=fill)

        pts = [
            left_shoulder,
            (x + int(w * 0.22), y + int(h * 0.18)),
            (x + int(w * 0.50), y + int(h * 0.22)),
            (x + int(w * 0.78), y + int(h * 0.18)),
            right_shoulder,
            (bottom_x, bottom_y),
        ]
        dr.polygon(pts, fill=fill)

    dr.arc([left_cx - rx, cy - ry, left_cx + rx, cy + ry], start=180, end=360, fill=outline, width=2)
    dr.arc([right_cx - rx, cy - ry, right_cx + rx, cy + ry], start=180, end=360, fill=outline, width=2)
    dr.line([left_shoulder, (bottom_x, bottom_y)], fill=outline, width=2)
    dr.line([right_shoulder, (bottom_x, bottom_y)], fill=outline, width=2)


def interp_series(df: pd.DataFrame, tcol: str, vcol: str, t_query: np.ndarray) -> np.ndarray:
    if df is None or len(df) == 0:
        return np.full_like(t_query, np.nan, dtype=float)

    d = df[[tcol, vcol]].copy()
    d[tcol] = pd.to_numeric(d[tcol], errors="coerce")
    d[vcol] = pd.to_numeric(d[vcol], errors="coerce")
    d = d.dropna(subset=[tcol, vcol]).sort_values(tcol)

    if len(d) == 0:
        return np.full_like(t_query, np.nan, dtype=float)

    x = d[tcol].to_numpy(dtype=float)
    y = d[vcol].to_numpy(dtype=float)
    return np.interp(t_query, x, y)


def asof_hold(df: pd.DataFrame, tcol: str, vcol: str, t_query: np.ndarray) -> np.ndarray:
    if df is None or len(df) == 0:
        return np.full_like(t_query, np.nan, dtype=float)

    d = df[[tcol, vcol]].copy()
    d[tcol] = pd.to_numeric(d[tcol], errors="coerce")
    d[vcol] = pd.to_numeric(d[vcol], errors="coerce")
    d = d.dropna(subset=[tcol]).sort_values(tcol)

    if len(d) == 0:
        return np.full_like(t_query, np.nan, dtype=float)

    q = pd.DataFrame({tcol: t_query})
    out = pd.merge_asof(q, d, on=tcol, direction="backward")
    return out[vcol].to_numpy(dtype=float)


def asof_hold_datetime(df: pd.DataFrame, tcol: str, vcol: str, t_query: np.ndarray) -> np.ndarray:
    if df is None or len(df) == 0:
        return np.array([pd.NaT] * len(t_query), dtype="datetime64[ns]")

    d = df[[tcol, vcol]].copy()
    d[tcol] = pd.to_numeric(d[tcol], errors="coerce")
    d[vcol] = pd.to_datetime(d[vcol], errors="coerce")
    d = d.dropna(subset=[tcol, vcol]).sort_values(tcol)

    if len(d) == 0:
        return np.array([pd.NaT] * len(t_query), dtype="datetime64[ns]")

    q = pd.DataFrame({tcol: t_query})
    out = pd.merge_asof(q, d, on=tcol, direction="backward")
    return out[vcol].to_numpy()


def load_unified_parquet(p: Path, name: str, tcol="t_mono") -> pd.DataFrame:
    df = pd.read_parquet(p)
    df = df[df["name"].astype(str) == name].copy()
    df[tcol] = pd.to_numeric(df[tcol], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=[tcol]).sort_values(tcol)
    return df


def load_unified_temp_sensor(p: Path, sensor_name="28-0000006dff1d", tcol="t_mono") -> pd.DataFrame:
    df = pd.read_parquet(p)
    df = df[df["name"].astype(str) == sensor_name].copy()
    df[tcol] = pd.to_numeric(df[tcol], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=[tcol, "value"]).sort_values(tcol)

    if len(df) == 0:
        return df

    df["temp_value"] = (df["value"] / 1000).round().astype(int)
    return df[[tcol, "temp_value"]]


def load_unified_wall_time(p: Path, tcol="t_mono") -> pd.DataFrame:
    df = pd.read_csv(p)
    df[tcol] = pd.to_numeric(df[tcol], errors="coerce")
    df["t_wall"] = pd.to_datetime(df["t_wall"], errors="coerce")
    df = df.dropna(subset=[tcol, "t_wall"]).sort_values(tcol)
    return df[[tcol, "t_wall"]]


def load_imu_parquet(p: Path, tcol: str) -> pd.DataFrame:
    df = pd.read_parquet(p)
    df[tcol] = pd.to_numeric(df[tcol], errors="coerce")
    df = df.dropna(subset=[tcol]).sort_values(tcol)
    return df


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def blend_color(c0, c1, frac: float):
    frac = clamp(frac, 0.0, 1.0)
    return tuple(int(round(a + (b - a) * frac)) for a, b in zip(c0, c1))


def format_wall_datetime_jst(value) -> str:
    if pd.isna(value):
        return ""
    try:
        ts = pd.Timestamp(value)
        return ts.strftime("%H:%M:%S %d.%m.%Y JST")
    except Exception:
        return ""


def draw_text_right(dr: ImageDraw.ImageDraw, x_right: int, y: int, text: str, font, fill):
    if not text:
        return
    bbox = dr.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    dr.text((x_right - tw, y), text, font=font, fill=fill)


def draw_bpm_unit(
    dr: ImageDraw.ImageDraw,
    cx: int,
    base_y: int,
    hb: float,
    font_num,
    font_unit,
    fill=(245, 245, 245),
    unit_text: str = "BPM",
    gap: int = 6,
):
    num_txt = "--" if not np.isfinite(hb) else f"{int(round(hb))}"
    unit_txt = unit_text

    num_bbox = dr.textbbox((0, 0), num_txt, font=font_num)
    unit_bbox = dr.textbbox((0, 0), unit_txt, font=font_unit)

    num_w = num_bbox[2] - num_bbox[0]
    num_h = num_bbox[3] - num_bbox[1]
    unit_w = unit_bbox[2] - unit_bbox[0]
    unit_h = unit_bbox[3] - unit_bbox[1]

    group_w = num_w + gap + unit_w
    group_x = cx - group_w // 2

    dr.text((group_x, base_y - num_h), num_txt, font=font_num, fill=fill)
    dr.text((group_x + num_w + gap, base_y - unit_h), unit_txt, font=font_unit, fill=fill)


def draw_hr_heart_only(
    dr: ImageDraw.ImageDraw,
    x: int,
    y: int,
    size: int,
    hr_value: float,
    hr_min: float,
    hr_max: float,
    base=(90, 90, 90),
    peak=(160, 160, 160),
):
    if np.isfinite(hr_value):
        frac = (hr_value - hr_min) / (hr_max - hr_min)
        color = blend_color(base, peak, frac)
    else:
        color = base

    hi = (
        min(255, color[0] + 16),
        min(255, color[1] + 16),
        min(255, color[2] + 16),
    )
    shadow = (
        max(0, color[0] - 14),
        max(0, color[1] - 14),
        max(0, color[2] - 14),
    )

    draw_heart_icon(dr, x, y, size=size, outline=color, fill=color)

    dr.ellipse(
        [
            x + int(size * 0.16),
            y + int(size * 0.10),
            x + int(size * 0.42),
            y + int(size * 0.34),
        ],
        fill=hi,
    )

    dr.ellipse(
        [
            x + int(size * 0.56),
            y + int(size * 0.12),
            x + int(size * 0.74),
            y + int(size * 0.28),
        ],
        fill=hi,
    )

    dr.ellipse(
        [
            x + int(size * 0.54),
            y + int(size * 0.46),
            x + int(size * 0.84),
            y + int(size * 0.78),
        ],
        outline=shadow,
        width=1,
    )

    draw_heart_icon(dr, x, y, size=size, outline=color, fill=None)


def draw_hr_module(
    dr: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    hr_value: float,
    hr_min: float,
    hr_max: float,
    outline=(120, 120, 120),
    base=(85, 85, 85),
    peak=(255, 140, 0),
    scale: int = 1,
):
    side_pad = S(18, scale)
    heart_size = S(24, scale)

    x0 = x + side_pad
    x1 = x + w - side_pad
    line_y = y + h - S(8, scale)

    post_h = S(20, scale)
    rail_th = max(1, S(2, scale))
    rail_r = max(1, S(1, scale))

    dr.rounded_rectangle(
        [x0 - rail_th // 2, line_y - post_h, x0 + rail_th // 2, line_y],
        radius=rail_r,
        fill=base,
        outline=None,
    )
    dr.rounded_rectangle(
        [x1 - rail_th // 2, line_y - post_h, x1 + rail_th // 2, line_y],
        radius=rail_r,
        fill=base,
        outline=None,
    )
    dr.rounded_rectangle(
        [x0, line_y - rail_th // 2, x1, line_y + rail_th // 2],
        radius=rail_r,
        fill=base,
        outline=None,
    )

    usable_w = x1 - x0
    if np.isfinite(hr_value):
        frac = clamp((hr_value - hr_min) / (hr_max - hr_min), 0.0, 1.0)
    else:
        frac = 0.0

    heart_cx = x0 + int(round(usable_w * frac))
    heart_x = heart_cx - heart_size // 2

    gap_above_line = S(3, scale)
    heart_y = line_y - gap_above_line - heart_size

    draw_hr_heart_only(
        dr,
        x=heart_x,
        y=heart_y,
        size=heart_size,
        hr_value=hr_value,
        hr_min=hr_min,
        hr_max=hr_max,
        base=(90, 90, 90),
        peak=peak,
    )


def draw_glossy_dot(
    dr: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    r: int,
    base=(160, 160, 160),
    hi=(235, 235, 235),
    lo=(95, 95, 95),
    outline=(185, 185, 185),
):
    dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=base, outline=outline)

    hr = max(2, r // 2)
    hx0 = cx - r // 2 - max(1, r // 6)
    hy0 = cy - r // 2 - max(1, r // 6)
    dr.ellipse([hx0, hy0, hx0 + hr, hy0 + hr], fill=hi)

    dr.arc([cx - r, cy - r, cx + r, cy + r], start=210, end=30, fill=lo, width=1)


def draw_glossy_needle(
    dr: ImageDraw.ImageDraw,
    hub_x: float,
    hub_y: float,
    tip_x: float,
    tip_y: float,
    base=(160, 160, 160),
    hi=(235, 235, 235),
    lo=(95, 95, 95),
    hub_fill=(170, 170, 170),
    hub_outline=(210, 210, 210),
    scale: int = 1,
):
    vx = tip_x - hub_x
    vy = tip_y - hub_y
    vn = math.hypot(vx, vy)
    if vn < 1e-6:
        return

    ux = vx / vn
    uy = vy / vn
    bx = -uy
    by = ux

    tail_len = float(S(3, scale))
    tail_w = float(S(2, scale))
    head_len = float(S(10, scale))
    body_w = float(S(3, scale))

    p_tail_l = (hub_x - ux * tail_len + bx * tail_w, hub_y - uy * tail_len + by * tail_w)
    p_tail_r = (hub_x - ux * tail_len - bx * tail_w, hub_y - uy * tail_len - by * tail_w)
    p_mid_r = (tip_x - ux * head_len - bx * body_w, tip_y - uy * head_len - by * body_w)
    p_tip = (tip_x, tip_y)
    p_mid_l = (tip_x - ux * head_len + bx * body_w, tip_y - uy * head_len + by * body_w)

    dr.polygon([p_tail_l, p_tail_r, p_mid_r, p_tip, p_mid_l], fill=base)

    dr.line(
        [
            (hub_x + bx * 0.8, hub_y + by * 0.8),
            (tip_x - ux * S(6, scale) + bx * 0.8, tip_y - uy * S(6, scale) + by * 0.8),
        ],
        fill=hi,
        width=max(1, S(1, scale)),
    )
    dr.line(
        [
            (hub_x - bx * 0.8, hub_y - by * 0.8),
            (tip_x - ux * S(6, scale) - bx * 0.8, tip_y - uy * S(6, scale) - by * 0.8),
        ],
        fill=lo,
        width=max(1, S(1, scale)),
    )

    hr = S(4, scale)
    dr.ellipse([hub_x - hr, hub_y - hr, hub_x + hr, hub_y + hr], fill=hub_fill, outline=hub_outline)
    dr.ellipse([hub_x - S(2, scale), hub_y - S(2, scale), hub_x, hub_y], fill=hi)


def draw_attitude_module(
    dr: ImageDraw.ImageDraw,
    x: int,
    y: int,
    size: int,
    yaw_v: float,
    pitch_v: float,
    roll_v: float,
    yaw_full: float,
    pitch_full: float,
    roll_full: float,
    font_s,
    font_m,
    white=(245, 245, 245),
    gray=(170, 170, 170),
    dim=(120, 120, 120),
    orange=(255, 140, 0),
    scale: int = 1,
):
    cx = x + size // 2
    cy = y + size // 2 + S(6, scale)

    box_h = int(size * 0.62)
    box_w = int(round(box_h * 1.25))

    half_h = box_h // 2
    half_w = box_w // 2

    cross_pad = S(12, scale)

    dr.line(
        [(cx - half_w + cross_pad, cy), (cx + half_w - cross_pad, cy)],
        fill=dim,
        width=S(2, scale),
    )
    dr.line(
        [(cx, cy - half_h + cross_pad), (cx, cy + half_h - cross_pad)],
        fill=dim,
        width=S(2, scale),
    )
    dr.ellipse(
        [cx - S(3, scale), cy - S(3, scale), cx + S(3, scale), cy + S(3, scale)],
        fill=gray,
        outline=gray,
    )

    if np.isfinite(roll_v) and np.isfinite(pitch_v):
        dx = int(clamp(roll_v / roll_full, -1.0, 1.0) * (half_w - S(11, scale)))
        dy = int(clamp(-pitch_v / pitch_full, -1.0, 1.0) * (half_h - S(11, scale)))
        px = cx + dx
        py = cy + dy

        dr.line([(cx, cy), (px, py)], fill=dim, width=S(2, scale))

        draw_glossy_dot(
            dr,
            px,
            py,
            r=S(7, scale),
            base=orange,
            hi=(205, 205, 205),
            lo=(120, 120, 120),
            outline=(180, 180, 180),
        )

    yaw_gap = S(22, scale)
    yaw_w = int(size * 0.56 * 1.5)
    yaw_h = int(size * 0.22 * 1.5)

    yaw_x0 = cx + half_w + yaw_gap
    yaw_x1 = yaw_x0 + yaw_w

    arc_cx = (yaw_x0 + yaw_x1) / 2.0
    arc_cy = cy + yaw_h * 0.5

    arc_x0 = arc_cx - yaw_w / 2.0
    arc_x1 = arc_cx + yaw_w / 2.0
    arc_y0 = arc_cy - yaw_h
    arc_y1 = arc_cy + yaw_h

    dr.arc([arc_x0, arc_y0, arc_x1, arc_y1], start=200, end=340, fill=dim, width=S(2, scale))

    for frac in (-1.0, -0.5, 0.0, 0.5, 1.0):
        max_swing_deg = 55.0
        theta_deg = -90.0 + frac * max_swing_deg
        theta = math.radians(theta_deg)

        a = yaw_w / 2.0
        b = yaw_h

        tx = arc_cx + a * math.cos(theta)
        ty = arc_cy + b * math.sin(theta)

        nx = math.cos(theta) / max(a, 1e-6)
        ny = math.sin(theta) / max(b, 1e-6)
        nn = math.hypot(nx, ny)
        if nn > 1e-6:
            nx /= nn
            ny /= nn

        tick_len = S(6, scale) if frac in (-0.5, 0.0, 0.5) else S(8, scale)
        x1t = tx - nx * tick_len / 2
        y1t = ty - ny * tick_len / 2
        x2t = tx + nx * tick_len / 2
        y2t = ty + ny * tick_len / 2
        dr.line([(x1t, y1t), (x2t, y2t)], fill=dim, width=max(1, S(1, scale)))

    if np.isfinite(yaw_v):
        yaw_frac = clamp(yaw_v / yaw_full, -1.0, 1.0)
        max_swing_deg = 55.0
        theta_deg = -90.0 + yaw_frac * max_swing_deg
        theta = math.radians(theta_deg)

        a = yaw_w / 2.0
        b = yaw_h

        tip_x = arc_cx + a * math.cos(theta)
        tip_y = arc_cy + b * math.sin(theta)

        hub_x = arc_cx
        hub_y = arc_cy + S(2, scale)

        draw_glossy_needle(
            dr,
            hub_x=hub_x,
            hub_y=hub_y,
            tip_x=tip_x,
            tip_y=tip_y,
            base=orange,
            hi=(190, 190, 190),
            lo=(120, 120, 120),
            hub_fill=gray,
            hub_outline=(175, 175, 175),
            scale=scale,
        )


def draw_speed_scale(
    dr: ImageDraw.ImageDraw,
    x0: int,
    y0: int,
    w: int,
    value: float,
    vmax: float,
    line=(170, 170, 170),
    tick=(120, 120, 120),
    marker=(245, 245, 245),
    scale: int = 1,
):
    main_w = max(1, S(3, scale))
    tick_w = max(1, S(1, scale))
    tick_h_s = S(4, scale)
    tick_h_l = S(12, scale)

    dr.line([(x0, y0), (x0 + w, y0)], fill=line, width=main_w)

    tick_fracs = [0.0, 0.25, 0.5, 0.75, 1.0]
    for frac in tick_fracs:
        xx = x0 + int(round(w * frac))
        th = tick_h_l if frac in (0.0, 0.5, 1.0) else tick_h_s
        col = line if frac in (0.0, 0.5, 1.0) else tick
        dr.line([(xx, y0 - th // 2), (xx, y0 + th // 2)], fill=col, width=tick_w)

    if np.isfinite(value):
        frac = clamp(value / vmax, 0.0, 1.0)
        mx = x0 + int(round(w * frac))
        mh = S(16, scale)
        dr.line([(mx, y0 - mh // 2), (mx, y0 + mh // 2)], fill=marker, width=max(1, S(3, scale)))


def draw_acc_scale(
    dr: ImageDraw.ImageDraw,
    x0: int,
    y0: int,
    w: int,
    value: float,
    full_scale: float,
    line=(170, 170, 170),
    tick=(120, 120, 120),
    marker=(245, 245, 245),
    center_line=(210, 210, 210),
    scale: int = 1,
    blink: bool = False,
    blink_on: bool = True,
):
    main_w = max(1, S(3, scale))
    center_w = max(1, S(3, scale))
    tick_w = max(1, S(1, scale))
    tick_h_s = S(4, scale)
    tick_h_l = S(10, scale)

    cx = x0 + w // 2

    dr.line([(x0, y0), (x0 + w, y0)], fill=line, width=main_w)

    # ここだけ元に戻す：中央線の長さを控えめに
    dr.line([(cx, y0 - tick_h_l), (cx, y0 + tick_h_l)], fill=center_line, width=center_w)

    for frac in (-1.0, -0.5, 0.5, 1.0):
        xx = int(round(cx + frac * (w / 2)))
        th = tick_h_l if abs(frac) == 1.0 else tick_h_s
        col = line if abs(frac) == 1.0 else tick
        dr.line([(xx, y0 - th // 2), (xx, y0 + th // 2)], fill=col, width=tick_w)

    if not np.isfinite(value):
        return
    if blink and (not blink_on):
        return

    frac = clamp(value / full_scale, -1.0, 1.0)
    mx = int(round(cx + frac * (w / 2)))
    mh = S(16, scale)
    dr.line([(mx, y0 - mh // 2), (mx, y0 + mh // 2)], fill=marker, width=max(1, S(3, scale)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="run_20260308_060029_104785")
    ap.add_argument("--b2-root", default=r"D:\701lab\work\phaseB\derived\b2\runs")
    ap.add_argument("--immutable-root", default=r"D:\701lab\immutable\runs")
    ap.add_argument("--out-root", default=r"D:\701lab\work\phaseB\visualization")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--sec-limit", type=float, default=60.0)
    ap.add_argument("--w", type=int, default=1280)
    ap.add_argument("--h", type=int, default=720)
    ap.add_argument("--route", default="Hamamatsu")
    ap.add_argument("--bike", default="BMW R18")
    ap.add_argument("--start-sec", type=float, default=0.0, help="Start offset from run start (seconds)")
    args = ap.parse_args()

    run_dir = Path(args.b2_root) / args.run_id
    if not run_dir.exists():
        raise SystemExit(f"[NG] missing run dir: {run_dir}")

    immutable_run_dir = Path(args.immutable_root) / args.run_id
    p_unified_csv = immutable_run_dir / "unified.csv"
    if not p_unified_csv.exists():
        raise SystemExit(f"[NG] missing unified.csv: {p_unified_csv}")

    p_gps = run_dir / "unified_gps.parquet"
    p_hr = run_dir / "unified_polar_hr.parquet"
    p_tmp = run_dir / "unified_temp.parquet"
    p_acc = run_dir / "imu_accel.parquet"
    p_ang = run_dir / "imu_angle.parquet"

    gps_speed = load_unified_parquet(p_gps, "speed_mps", tcol="t_mono")
    gps_lat = load_unified_parquet(p_gps, "lat", tcol="t_mono")
    gps_lon = load_unified_parquet(p_gps, "lon", tcol="t_mono")

    hr_bpm = load_unified_parquet(p_hr, "hr", tcol="t_mono")
    temp_sensor = load_unified_temp_sensor(p_tmp, sensor_name="28-0000006dff1d", tcol="t_mono")

    imu_acc = load_imu_parquet(p_acc, tcol="t_mono_s")
    imu_ang = load_imu_parquet(p_ang, tcol="t_mono_s")
    wall_df = load_unified_wall_time(p_unified_csv, tcol="t_mono")

    t0 = np.nanmin([
        gps_speed["t_mono"].iloc[0] if len(gps_speed) else np.nan,
        hr_bpm["t_mono"].iloc[0] if len(hr_bpm) else np.nan,
        imu_acc["t_mono_s"].iloc[0] if len(imu_acc) else np.nan,
        imu_ang["t_mono_s"].iloc[0] if len(imu_ang) else np.nan,
    ])
    t0 = t0 + args.start_sec

    t1 = np.nanmax([
        gps_speed["t_mono"].iloc[-1] if len(gps_speed) else np.nan,
        hr_bpm["t_mono"].iloc[-1] if len(hr_bpm) else np.nan,
        imu_acc["t_mono_s"].iloc[-1] if len(imu_acc) else np.nan,
        imu_ang["t_mono_s"].iloc[-1] if len(imu_ang) else np.nan,
    ])
    if not np.isfinite(t0) or not np.isfinite(t1) or t1 <= t0:
        raise SystemExit("[NG] bad time range")

    if args.sec_limit and args.sec_limit > 0:
        t1 = min(t1, t0 + args.sec_limit)

    fps = args.fps
    n_frames = int(math.floor((t1 - t0) * fps)) + 1
    t = t0 + (np.arange(n_frames) / fps)

    speed_kmh = interp_series(gps_speed, "t_mono", "value", t) * 3.6
    speed_kmh = pd.Series(speed_kmh).rolling(3, center=True, min_periods=1).mean().to_numpy().copy()
    speed_kmh[np.abs(speed_kmh) < 1.0] = 0.0
    lat = asof_hold(gps_lat, "t_mono", "value", t)
    lon = asof_hold(gps_lon, "t_mono", "value", t)
    wall_time = asof_hold_datetime(wall_df, "t_mono", "t_wall", t)

    hr = asof_hold(hr_bpm, "t_mono", "value", t)
    temp = asof_hold(temp_sensor, "t_mono", "temp_value", t)

    ax = asof_hold(imu_acc, "t_mono_s", "ax_g", t)
    bias_n = min(300, len(ax))
    ax_bias = np.nanmedian(ax[:bias_n]) if bias_n > 0 else 0.0
    acc_signed_g = ax - ax_bias
    acc_signed_g = pd.Series(acc_signed_g).rolling(7, center=True, min_periods=1).mean().to_numpy()

    roll = asof_hold(imu_ang, "t_mono_s", "roll_deg", t)
    pitch = asof_hold(imu_ang, "t_mono_s", "pitch_deg", t)
    yaw_raw = asof_hold(imu_ang, "t_mono_s", "yaw_deg", t)
    yaw_raw = pd.Series(yaw_raw).rolling(11, center=True, min_periods=1).mean().to_numpy()

    yaw_unwrapped = np.rad2deg(np.unwrap(np.deg2rad(yaw_raw)))
    if len(yaw_unwrapped) >= 2:
        yaw_rate = np.gradient(yaw_unwrapped, t)
        yaw_rate = pd.Series(yaw_rate).rolling(21, center=True, min_periods=1).mean().to_numpy()
    else:
        yaw_rate = np.full_like(yaw_unwrapped, np.nan, dtype=float)

    out_dir = Path(args.out_root) / args.run_id / f"frames_like_sample_{args.w}x{args.h}_{args.fps}fps"
    out_dir.mkdir(parents=True, exist_ok=True)

    W, H = args.w, args.h
    render_scale = 2
    RW, RH = W * render_scale, H * render_scale

    try:
        font_s = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", S(18, render_scale))
        font_m = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", S(22, render_scale))
        font_xl = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", S(30, render_scale))
        font_bpm = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", S(18, render_scale))
    except Exception:
        font_s = ImageFont.load_default()
        font_m = ImageFont.load_default()
        font_xl = ImageFont.load_default()
        font_bpm = ImageFont.load_default()

    top_h = S(70, render_scale)

    video_aspect = 2.35
    line_gap = S(5, render_scale)
    video_w = RW
    video_h = int(round(video_w / video_aspect))

    video_top = (RH - video_h) // 2
    video_bottom = video_top + video_h

    center_top_line_y = video_top - line_gap
    center_bottom_line_y = video_bottom + line_gap

    WHITE = (245, 245, 245)
    GRAY = (170, 170, 170)
    DIM = (120, 120, 120)
    BLACK = (0, 0, 0)

    HUD_ACCENT = (160, 160, 160)
    HUD_LABEL = (190, 190, 190)

    SPD_MAX = 200.0
    HR_MIN, HR_MAX = 80.0, 120.0

    YAW_FULL = 30.0
    PIT_FULL = 30.0
    ROL_FULL = 30.0

    for i in range(n_frames):
        im_large = Image.new("RGB", (RW, RH), BLACK)
        dr = ImageDraw.Draw(im_large)

        dr.rectangle([0, 0, RW, top_h], fill=BLACK)
        dr.text(
            (S(20, render_scale), S(14, render_scale)),
            f"{args.route} / {args.bike}",
            font=font_m,
            fill=WHITE,
        )

        date_txt = format_wall_datetime_jst(wall_time[i])
        dr.text((S(20, render_scale), S(50, render_scale)), date_txt, font=font_m, fill=WHITE)

        hb = hr[i]
        draw_bpm_unit(
            dr,
            cx=RW // 2,
            base_y=S(38, render_scale),
            hb=hb,
            font_num=font_xl,
            font_unit=font_bpm,
            fill=WHITE,
            unit_text="BPM",
            gap=S(6, render_scale),
        )

        la, lo = lat[i], lon[i]
        latlon_txt = f"{la:.4f}N {lo:.4f}E" if (np.isfinite(la) and np.isfinite(lo)) else ""
        draw_text_right(dr, RW - S(20, render_scale), S(14, render_scale), latlon_txt, font_m, WHITE)

        tp = temp[i]
        tp_txt = "" if not np.isfinite(tp) else f"{tp:.0f}°C"
        draw_text_right(dr, RW - S(20, render_scale), S(50, render_scale), tp_txt, font_m, WHITE)

        dr.line([(0, center_top_line_y), (RW, center_top_line_y)], fill=DIM, width=S(2, render_scale))
        if center_bottom_line_y < RH:
            dr.rectangle([0, center_bottom_line_y, RW, RH], fill=BLACK)
        dr.line([(0, center_bottom_line_y), (RW, center_bottom_line_y)], fill=DIM, width=S(2, render_scale))

        hr_box_x = S(55, render_scale)
        hr_box_w = S(220, render_scale)
        hr_box_h = S(44, render_scale)
        hr_box_y = RH - S(18, render_scale) - hr_box_h

        if hr_box_y + hr_box_h <= RH:
            draw_hr_module(
                dr,
                x=hr_box_x,
                y=hr_box_y,
                w=hr_box_w,
                h=hr_box_h,
                hr_value=hb,
                hr_min=HR_MIN,
                hr_max=HR_MAX,
                outline=(90, 90, 90),
                base=(85, 85, 85),
                peak=HUD_ACCENT,
                scale=render_scale,
            )

        center_block_w = S(620, render_scale)
        bottom_margin = S(45, render_scale)   # 少し下げる
        left_balance_shift = S(10, render_scale)  # 左側全体を少し下げて右下との高さバランスを取る

        bar_x = RW // 2 - center_block_w // 2
        spd_bar_w = center_block_w

        spd_y = RH - bottom_margin + left_balance_shift

        sp = speed_kmh[i]
        if spd_y <= RH:
            draw_speed_scale(
                dr,
                bar_x,
                spd_y,
                spd_bar_w,
                value=sp,
                vmax=SPD_MAX,
                line=HUD_LABEL,
                tick=DIM,
                marker=WHITE,
                scale=render_scale,
            )

        att_size = S(96, render_scale)
        rx = RW - S(280, render_scale)
        ry = RH - att_size

        if ry + att_size <= RH:
            draw_attitude_module(
                dr,
                x=rx,
                y=ry,
                size=att_size,
                yaw_v=yaw_rate[i],
                pitch_v=pitch[i],
                roll_v=roll[i],
                yaw_full=YAW_FULL,
                pitch_full=PIT_FULL,
                roll_full=ROL_FULL,
                font_s=font_s,
                font_m=font_m,
                white=WHITE,
                gray=GRAY,
                dim=DIM,
                orange=HUD_ACCENT,
                scale=render_scale,
            )

        try:
            im = im_large.resize((W, H), Image.Resampling.LANCZOS)
        except AttributeError:
            im = im_large.resize((W, H), Image.LANCZOS)

        out_png = out_dir / f"frame_{i:06d}.png"
        im.save(out_png)

        if i % 300 == 0:
            print(f"[INFO] wrote {out_png.name} ({i + 1}/{n_frames})")

    print(f"[OK] frames: {n_frames}")
    print(f"[OK] out_dir: {out_dir}")
    print(
        f'ffmpeg -y -r {fps} -i "{out_dir}\\frame_%06d.png" '
        f'-c:v libx264 -pix_fmt yuv420p "{out_dir}\\..\\{args.run_id}_like_sample_{fps}fps.mp4"'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())