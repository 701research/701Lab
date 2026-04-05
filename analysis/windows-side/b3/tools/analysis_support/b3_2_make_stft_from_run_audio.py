# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from scipy.io import wavfile
from scipy.signal import spectrogram


def parse_args():
    p = argparse.ArgumentParser(
        description="Create STFT spectrogram data from audio.wav in a run folder."
    )
    p.add_argument(
        "--run-id",
        type=str,
        required=True,
        help='Example: "run_20260308_060029_104785"',
    )
    p.add_argument(
        "--t-start",
        type=float,
        required=True,
        help="Start time in seconds",
    )
    p.add_argument(
        "--t-end",
        type=float,
        required=True,
        help="End time in seconds",
    )
    p.add_argument(
        "--immutable-root",
        type=str,
        default=r"D:\701lab\immutable\runs",
        help=r'Root directory of immutable runs. Default: D:\701lab\immutable\runs',
    )
    p.add_argument(
        "--output-root",
        type=str,
        default=r"D:\701lab\work\phaseB\analysis\b3\STFT\by_run",
        help=r'Output root directory. Default: D:\701lab\work\phaseB\analysis\b3\STFT\by_run',
    )
    p.add_argument(
        "--nperseg",
        type=int,
        default=1024,
        help="STFT window length. Default: 1024",
    )
    p.add_argument(
        "--noverlap",
        type=int,
        default=768,
        help="STFT overlap. Default: 768",
    )
    p.add_argument(
        "--nfft",
        type=int,
        default=1024,
        help="FFT size. Default: 1024",
    )
    p.add_argument(
        "--fmax",
        type=float,
        default=None,
        help="Maximum frequency to keep/display in Hz. Default: None (all)",
    )
    return p.parse_args()


def ensure_float_audio(audio: np.ndarray) -> np.ndarray:
    if np.issubdtype(audio.dtype, np.integer):
        info = np.iinfo(audio.dtype)
        max_abs = max(abs(info.min), abs(info.max))
        audio = audio.astype(np.float32) / float(max_abs)
    else:
        audio = audio.astype(np.float32)

    return audio


def to_mono(audio: np.ndarray) -> np.ndarray:
    if audio.ndim == 1:
        return audio
    if audio.ndim == 2:
        return audio.mean(axis=1).astype(np.float32)
    raise ValueError(f"Unsupported audio shape: {audio.shape}")


def save_spectrogram_png(
    out_path: Path,
    times_abs: np.ndarray,
    freqs: np.ndarray,
    power_db: np.ndarray,
    title: str,
    ylim: tuple[float, float] | None = None,
):
    plt.figure(figsize=(12, 6))
    plt.pcolormesh(times_abs, freqs, power_db, shading="auto")
    plt.xlabel("Time [s]")
    plt.ylabel("Frequency [Hz]")
    plt.title(title)
    if ylim is not None:
        plt.ylim(*ylim)
    plt.colorbar(label="Intensity [dB]")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


def save_mean_spectrum_png(
    out_path: Path,
    freqs: np.ndarray,
    mean_power_db: np.ndarray,
    title: str,
    xlim: tuple[float, float] | None = None,
):
    plt.figure(figsize=(12, 6))
    plt.plot(freqs, mean_power_db)
    plt.xlabel("Frequency [Hz]")
    plt.ylabel("Mean Intensity [dB]")
    plt.title(title)
    if xlim is not None:
        plt.xlim(*xlim)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


def main():
    args = parse_args()

    if args.t_end <= args.t_start:
        raise ValueError("--t-end must be greater than --t-start")

    input_wav = (
        Path(args.immutable_root)
        / args.run_id
        / "raw"
        / "audio.wav"
    )

    output_dir = Path(args.output_root) / args.run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_wav.exists():
        raise FileNotFoundError(f"audio.wav not found: {input_wav}")

    print(f"[INFO] input_wav  : {input_wav}")
    print(f"[INFO] output_dir : {output_dir}")

    sr, audio = wavfile.read(str(input_wav))
    print(f"[INFO] sample_rate: {sr}")
    print(f"[INFO] raw_shape   : {audio.shape}")
    print(f"[INFO] raw_dtype   : {audio.dtype}")

    audio = to_mono(audio)
    audio = ensure_float_audio(audio)

    total_sec = len(audio) / sr
    print(f"[INFO] total_sec   : {total_sec:.3f}")

    start_idx = max(0, int(round(args.t_start * sr)))
    end_idx = min(len(audio), int(round(args.t_end * sr)))

    if start_idx >= len(audio):
        raise ValueError("--t-start is beyond audio length")
    if end_idx <= start_idx:
        raise ValueError("Segment length is zero or negative after clipping")

    segment = audio[start_idx:end_idx]
    seg_sec = len(segment) / sr

    print(f"[INFO] start_idx   : {start_idx}")
    print(f"[INFO] end_idx     : {end_idx}")
    print(f"[INFO] seg_samples : {len(segment)}")
    print(f"[INFO] seg_sec     : {seg_sec:.3f}")

    if len(segment) < args.nperseg:
        raise ValueError(
            f"Segment too short for nperseg={args.nperseg}. "
            f"Segment samples={len(segment)}"
        )

    freqs, times_rel, Sxx = spectrogram(
        segment,
        fs=sr,
        window="hann",
        nperseg=args.nperseg,
        noverlap=args.noverlap,
        nfft=args.nfft,
        scaling="spectrum",
        mode="magnitude",
    )

    power_db = 20.0 * np.log10(Sxx + 1e-12)
    times_abs = times_rel + args.t_start

    if args.fmax is not None:
        mask = freqs <= args.fmax
        freqs = freqs[mask]
        power_db = power_db[mask, :]

    mean_power_db = np.mean(power_db, axis=1)

    npz_path = output_dir / "spectrogram_data.npz"
    csv_path = output_dir / "spectrogram_power_db.csv"
    png_path = output_dir / "spectrogram.png"
    png_0_3000_path = output_dir / "spectrogram_0_3000Hz.png"
    mean_spec_png_path = output_dir / "mean_spectrum.png"
    mean_spec_0_3000_png_path = output_dir / "mean_spectrum_0_3000Hz.png"
    mean_spec_csv_path = output_dir / "mean_spectrum.csv"
    wav_seg_path = output_dir / "audio_segment.wav"
    meta_path = output_dir / "spectrogram_info.txt"

    np.savez(
        npz_path,
        run_id=args.run_id,
        sample_rate=sr,
        t_start=args.t_start,
        t_end=args.t_end,
        times=times_abs,
        freqs=freqs,
        power_db=power_db,
        mean_power_db=mean_power_db,
        nperseg=args.nperseg,
        noverlap=args.noverlap,
        nfft=args.nfft,
    )

    np.savetxt(csv_path, power_db, delimiter=",")

    mean_spec_table = np.column_stack([freqs, mean_power_db])
    np.savetxt(
        mean_spec_csv_path,
        mean_spec_table,
        delimiter=",",
        header="frequency_hz,mean_intensity_db",
        comments="",
    )

    seg_int16 = np.clip(segment, -1.0, 1.0)
    seg_int16 = (seg_int16 * 32767.0).astype(np.int16)
    wavfile.write(str(wav_seg_path), sr, seg_int16)

    title_base = f"Spectrogram: {args.run_id}  ({args.t_start:.1f}s - {args.t_end:.1f}s)"

    save_spectrogram_png(
        out_path=png_path,
        times_abs=times_abs,
        freqs=freqs,
        power_db=power_db,
        title=title_base,
        ylim=None,
    )

    save_spectrogram_png(
        out_path=png_0_3000_path,
        times_abs=times_abs,
        freqs=freqs,
        power_db=power_db,
        title=title_base + " [0-3000 Hz]",
        ylim=(0, 3000),
    )

    save_mean_spectrum_png(
        out_path=mean_spec_png_path,
        freqs=freqs,
        mean_power_db=mean_power_db,
        title=f"Mean Spectrum: {args.run_id}  ({args.t_start:.1f}s - {args.t_end:.1f}s)",
        xlim=None,
    )

    save_mean_spectrum_png(
        out_path=mean_spec_0_3000_png_path,
        freqs=freqs,
        mean_power_db=mean_power_db,
        title=f"Mean Spectrum: {args.run_id}  ({args.t_start:.1f}s - {args.t_end:.1f}s) [0-3000 Hz]",
        xlim=(0, 3000),
    )

    with open(meta_path, "w", encoding="utf-8") as f:
        f.write(f"run_id={args.run_id}\n")
        f.write(f"input_wav={input_wav}\n")
        f.write(f"sample_rate={sr}\n")
        f.write(f"t_start={args.t_start}\n")
        f.write(f"t_end={args.t_end}\n")
        f.write(f"segment_seconds={seg_sec}\n")
        f.write(f"nperseg={args.nperseg}\n")
        f.write(f"noverlap={args.noverlap}\n")
        f.write(f"nfft={args.nfft}\n")
        f.write(f"freq_bins={len(freqs)}\n")
        f.write(f"time_bins={len(times_abs)}\n")
        f.write("extra_plot=spectrogram_0_3000Hz.png\n")
        f.write("extra_plot=mean_spectrum.png\n")
        f.write("extra_plot=mean_spectrum_0_3000Hz.png\n")
        f.write("extra_csv=mean_spectrum.csv\n")
        if args.fmax is not None:
            f.write(f"fmax={args.fmax}\n")

    print("[INFO] saved:")
    print(f"  {npz_path}")
    print(f"  {csv_path}")
    print(f"  {png_path}")
    print(f"  {png_0_3000_path}")
    print(f"  {mean_spec_png_path}")
    print(f"  {mean_spec_0_3000_png_path}")
    print(f"  {mean_spec_csv_path}")
    print(f"  {wav_seg_path}")
    print(f"  {meta_path}")
    print("[DONE]")


if __name__ == "__main__":
    main()