"""Measure a small avatar overlay on one CPU and CUDA GPU.

Run with: python3 gpu_avatar_benchmark.py --frames 250 --size 512
The Pillow path mirrors LightweightAvatarEngine's per-frame draw and RGB export.
The Torch CPU/CUDA paths use the same integer ellipse mask so their pixels can
be compared exactly. CUDA's readback result includes the transfer WebRTC needs.
"""

import argparse
import hashlib
import json
import statistics
import time

import numpy as np
from PIL import Image, ImageDraw
import torch


def run_pillow(size: int, openings: list[int]) -> tuple[float, bytes]:
    base = Image.new("RGB", (size, size), "#dce8f0")
    first = b""
    start = time.perf_counter()
    for i, opening in enumerate(openings):
        frame = base.copy()
        draw = ImageDraw.Draw(frame)
        draw.ellipse(
            (size * .41, size * .64 - opening / 2, size * .59, size * .64 + opening / 2),
            fill="#853f45", outline="#70383e", width=2,
        )
        rgb = frame.tobytes()
        if i == 0:
            first = rgb
    return time.perf_counter() - start, first


def torch_renderer(size: int, device: str):
    base = torch.empty((size, size, 3), dtype=torch.uint8, device=device)
    base[:] = torch.tensor([0xdc, 0xe8, 0xf0], dtype=torch.uint8, device=device)
    color = torch.tensor([0x85, 0x3f, 0x45], dtype=torch.uint8, device=device)
    x = torch.arange(size, device=device, dtype=torch.int32)[None, :] - round(size * .50)
    y = torch.arange(size, device=device, dtype=torch.int32)[:, None] - round(size * .64)
    x2 = x * x
    y2 = y * y
    rx2 = round(size * .09) ** 2

    def render(opening: int):
        ry2 = max(1, opening // 2) ** 2
        mask = x2 * ry2 + y2 * rx2 <= rx2 * ry2
        return torch.where(mask[:, :, None], color, base)

    return render


def run_torch(render, openings: list[int], device: str, readback: bool) -> tuple[float, bytes]:
    first = b""
    start = time.perf_counter()
    for i, opening in enumerate(openings):
        frame = render(opening)
        if readback:
            rgb = frame.cpu().numpy().tobytes()
            if i == 0:
                first = rgb
    if device == "cuda":
        torch.cuda.synchronize()
    return time.perf_counter() - start, first


def median_run(func, repeats: int = 3):
    measurements = [func() for _ in range(repeats)]
    return statistics.median(item[0] for item in measurements), measurements[0][1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=250)
    parser.add_argument("--size", type=int, default=512)
    args = parser.parse_args()
    if args.frames < 1 or args.size < 64:
        parser.error("frames must be positive and size must be at least 64")
    torch.set_num_threads(1)
    openings = [max(3, int(args.size * (.01 + .075 * abs(np.sin(i * .17)))))
                for i in range(args.frames)]
    pillow_s, _ = median_run(lambda: run_pillow(args.size, openings))
    cpu_render = torch_renderer(args.size, "cpu")
    cpu_render(openings[0])
    torch_cpu_s, cpu_first = median_run(lambda: run_torch(cpu_render, openings, "cpu", True))
    result = {
        "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "torch": torch.__version__,
        "frames": args.frames,
        "size": args.size,
        "repeats": 3,
        "pillow_cpu_seconds": round(pillow_s, 4),
        "torch_cpu_with_rgb_seconds": round(torch_cpu_s, 4),
    }
    if torch.cuda.is_available():
        gpu_render = torch_renderer(args.size, "cuda")
        torch.cuda.synchronize()
        for opening in openings[:10]:
            gpu_render(opening).cpu().numpy().tobytes()
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        gpu_compute_s, _ = median_run(lambda: run_torch(gpu_render, openings, "cuda", False))
        gpu_rgb_s, gpu_first = median_run(lambda: run_torch(gpu_render, openings, "cuda", True))
        distinct_openings = sorted(set(openings))
        pixel_match = all(torch.equal(cpu_render(o), gpu_render(o).cpu()) for o in distinct_openings)
        result.update({
            "torch_gpu_compute_seconds": round(gpu_compute_s, 4),
            "torch_gpu_with_rgb_seconds": round(gpu_rgb_s, 4),
            "gpu_peak_allocated_mib": round(torch.cuda.max_memory_allocated() / 1048576, 1),
            "cpu_gpu_all_openings_identical": pixel_match and cpu_first == gpu_first,
            "distinct_openings_checked": len(distinct_openings),
            "first_frame_sha256": hashlib.sha256(gpu_first).hexdigest(),
        })
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
