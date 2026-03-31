# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import math
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def ease_out(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    return 1.0 - (1.0 - t) ** 3


def alpha_fade(now_sec: float, start_sec: float, fade_sec: float) -> int:
    if now_sec < start_sec:
        return 0
    if fade_sec <= 0:
        return 255
    a = ease_out((now_sec - start_sec) / fade_sec)
    return int(round(255 * a))


def load_font_candidates(candidates: list[str], size: int):
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def load_times_regular(size: int):
    return load_font_candidates([
        "C:/Windows/Fonts/times.ttf",
        "C:/Windows/Fonts/georgia.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ], size)


def load_times_bold(size: int):
    return load_font_candidates([
        "C:/Windows/Fonts/timesbd.ttf",
        "C:/Windows/Fonts/georgiab.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ], size)


def load_times_italic(size: int):
    return load_font_candidates([
        "C:/Windows/Fonts/timesi.ttf",
        "C:/Windows/Fonts/georgiai.ttf",
        "C:/Windows/Fonts/ariali.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ], size)


def load_arial_regular(size: int):
    return load_font_candidates([
        "C:/Windows/Fonts/arial.ttf",
    ], size)


def load_arial_bold(size: int):
    return load_font_candidates([
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ], size)


def text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def draw_center_text(
    base_img: Image.Image,
    text: str,
    font,
    center_x: int,
    y: int,
    fill=(245, 245, 245),
    alpha: int = 255,
):
    if not text or alpha <= 0:
        return

    overlay = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(overlay)

    bbox = dr.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    tx = center_x - tw // 2

    dr.text((tx, y), text, font=font, fill=(*fill, alpha))
    base_img.alpha_composite(overlay)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-root", default=r"D:\701lab\work\phaseB\visualization\title_intro")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--w", type=int, default=1280)
    ap.add_argument("--h", type=int, default=720)

    # 時間設定
    ap.add_argument("--duration", type=float, default=9.0)
    ap.add_argument("--first-start", type=float, default=1.2)
    ap.add_argument("--interval", type=float, default=2.2)
    ap.add_argument("--fade-sec", type=float, default=3.0)
    ap.add_argument("--hold-after-all", type=float, default=10.0)

    # 表示テキスト
    ap.add_argument("--line1", default="Spring, at Dawn")
    ap.add_argument("--line2", default="after Sei Shonagon")
    ap.add_argument("--line3", default="BMW K1600GT")
    ap.add_argument("--line4", default="Readings in First Light")
    ap.add_argument("--line5", default="08 Mar 2026 — Hamamatsu")

    # レイアウト
    ap.add_argument("--group-gap", type=int, default=42)
    ap.add_argument("--line-gap-small", type=int, default=8)

    # 位置微調整
    ap.add_argument("--group1-y-offset", type=int, default=-80)  # 1,2行目を上へ
    ap.add_argument("--group2-y-offset", type=int, default=0)    # 3,4行目
    ap.add_argument("--group3-y-offset", type=int, default=80)   # 5行目を下へ

    ap.add_argument("--bg", default="0,0,0")
    ap.add_argument("--fg", default="245,245,245")

    ap.add_argument("--make-mp4", action="store_true")
    ap.add_argument("--mp4-name", default="title_intro.mp4")

    ap.add_argument("--concat-with", default="")
    ap.add_argument("--concat-out", default="title_plus_dashboard.mp4")

    args = ap.parse_args()

    out_root = Path(args.out_root)
    frames_dir = out_root / f"frames_{args.w}x{args.h}_{args.fps}fps"
    frames_dir.mkdir(parents=True, exist_ok=True)

    bg = tuple(int(v) for v in args.bg.split(","))
    fg = tuple(int(v) for v in args.fg.split(","))

    W, H = args.w, args.h
    fps = args.fps
    #n_frames = int(math.floor(args.duration * fps))

    # 指定フォント設定
    # line1: times, 32, bold, 斜体無し
    font1 = load_times_bold(32)

    # line2: times, 24, boldなし, 斜体
    font2 = load_times_italic(24)

    # line3: Arial, 24, bold, 斜体無し
    font3 = load_arial_bold(24)

    # line4: Arial, 24, bold, 斜体無し
    font4 = load_arial_bold(24)

    # line5: Arial, 20, boldなし, 斜体無し
    font5 = load_arial_regular(20)

    # レイアウト計算
    dummy = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr_dummy = ImageDraw.Draw(dummy)

    _, h1 = text_size(dr_dummy, args.line1, font1)
    _, h2 = text_size(dr_dummy, args.line2, font2)
    _, h3 = text_size(dr_dummy, args.line3, font3)
    _, h4 = text_size(dr_dummy, args.line4, font4)
    _, h5 = text_size(dr_dummy, args.line5, font5)

    group1_h = h1 + args.line_gap_small + h2
    group2_h = h3 + args.line_gap_small + h4
    group3_h = h5

    total_h = group1_h + args.group_gap + group2_h + args.group_gap + group3_h
    top_y = (H - total_h) // 2

    # 基本位置
    y1_base = top_y
    y2_base = y1_base + h1 + args.line_gap_small
    y3_base = y2_base + h2 + args.group_gap
    y4_base = y3_base + h3 + args.line_gap_small
    y5_base = y4_base + h4 + args.group_gap

    # ブロックごとの微調整
    y1 = y1_base + args.group1_y_offset
    y2 = y2_base + args.group1_y_offset

    y3 = y3_base + args.group2_y_offset
    y4 = y4_base + args.group2_y_offset

    y5 = y5_base + args.group3_y_offset

    # フェード開始時刻
    t_start_1 = args.first_start
    t_start_2 = args.first_start + args.interval
    t_start_3 = args.first_start + args.interval * 2

    # 最後の行のフェード完了時刻
    all_shown_sec = t_start_3 + args.fade_sec

    # 動画全体の長さを自動調整
    effective_duration = all_shown_sec + args.hold_after_all
    n_frames = int(math.floor(effective_duration * fps))


    for i in range(n_frames):
        now_sec = i / fps
        im = Image.new("RGBA", (W, H), (*bg, 255))

        a1 = alpha_fade(now_sec, t_start_1, args.fade_sec)
        a2 = alpha_fade(now_sec, t_start_1, args.fade_sec)
        a3 = alpha_fade(now_sec, t_start_2, args.fade_sec)
        a4 = alpha_fade(now_sec, t_start_2, args.fade_sec)
        a5 = alpha_fade(now_sec, t_start_3, args.fade_sec)

        draw_center_text(im, args.line1, font1, W // 2, y1, fill=fg, alpha=a1)
        draw_center_text(im, args.line2, font2, W // 2, y2, fill=fg, alpha=a2)
        draw_center_text(im, args.line3, font3, W // 2, y3, fill=fg, alpha=a3)
        draw_center_text(im, args.line4, font4, W // 2, y4, fill=fg, alpha=a4)
        draw_center_text(im, args.line5, font5, W // 2, y5, fill=fg, alpha=a5)

        out_png = frames_dir / f"frame_{i:06d}.png"
        im.convert("RGB").save(out_png)

        if i % 30 == 0:
            print(f"[INFO] wrote {out_png.name} ({i + 1}/{n_frames})")

    print(f"[OK] frames written: {n_frames}")
    print(f"[OK] frames_dir: {frames_dir}")

    mp4_path = out_root / args.mp4_name

    if args.make_mp4:
        cmd = [
            "ffmpeg",
            "-y",
            "-r",
            str(fps),
            "-i",
            str(frames_dir / "frame_%06d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(mp4_path),
        ]
        print("[INFO] ffmpeg:", " ".join(cmd))
        subprocess.run(cmd, check=True)
        print(f"[OK] mp4: {mp4_path}")

    if args.concat_with:
        dashboard_mp4 = Path(args.concat_with)
        concat_list = out_root / "concat_list.txt"

        title_src = mp4_path if args.make_mp4 else (out_root / args.mp4_name)
        if not title_src.exists():
            raise SystemExit(f"[NG] title mp4 not found: {title_src}")
        if not dashboard_mp4.exists():
            raise SystemExit(f"[NG] dashboard mp4 not found: {dashboard_mp4}")

        concat_list.write_text(
            f"file '{title_src.as_posix()}'\n"
            f"file '{dashboard_mp4.as_posix()}'\n",
            encoding="utf-8"
        )

        concat_out = out_root / args.concat_out
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(concat_out),
        ]
        print("[INFO] concat ffmpeg:", " ".join(cmd))
        subprocess.run(cmd, check=True)
        print(f"[OK] concatenated mp4: {concat_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())