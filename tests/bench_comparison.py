"""
bench_comparison.py
===================
Head-to-head performance benchmark:
    thumbleweed  vs  blurhash-python  vs  thumbhash-python  vs  fast-colorthief

Uses the real image fixtures in ``tests/``.

Run with:
    python tests/bench_comparison.py
or:
    python tests/bench_comparison.py --rounds 5 --warmup 2 --iters 200

The script prints a Markdown table and also wraps the results in marker comments
so `scripts/update_readme.py` can inject them into `README.md`.
"""

from __future__ import annotations

import argparse
import importlib
import statistics
import sys
import time
from pathlib import Path
from typing import Callable

# ── Import helpers ───────────────────────────────────────────────────────────

_PYTHON_SRC = str(Path(__file__).parent.parent / "python")


def _import_competitor(name: str):
    """Import a competitor package by temporarily deprioritising our python/ dir."""
    removed = False
    if sys.path and sys.path[0] == _PYTHON_SRC:
        sys.path.pop(0)
        removed = True
    cached = sys.modules.pop(name, None)
    try:
        return importlib.import_module(name)
    except ImportError:
        return None
    finally:
        if removed:
            sys.path.insert(0, _PYTHON_SRC)
        if cached is not None:
            sys.modules[name] = cached


import thumbleweed  # noqa: E402

_bh_py = _import_competitor("blurhash")
HAS_BH_PY = _bh_py is not None and hasattr(_bh_py, "encode")

_th_py_raw = _import_competitor("thumbhash")
HAS_TH_PY = _th_py_raw is not None and hasattr(_th_py_raw, "image_to_thumbhash")
_th_py = _th_py_raw if HAS_TH_PY else None

try:
    import fast_colorthief as _fct  # noqa: E402

    HAS_FCT = True
except ImportError:
    HAS_FCT = False

from PIL import Image  # noqa: E402

TESTS_DIR = Path(__file__).parent
IMAGE_PATHS = [
    TESTS_DIR / "one.jpg",
    TESTS_DIR / "two.jpg",
    TESTS_DIR / "four.jpg",
    TESTS_DIR / "OPS.jpg",
]


# ── Fixture preparation ──────────────────────────────────────────────────────


def _load_image(path: Path) -> Image.Image:
    with Image.open(path) as img:
        return img.convert("RGBA").copy()


def _fit_thumbhash_image(img: Image.Image) -> Image.Image:
    max_side = 100
    w, h = img.size
    if w > max_side or h > max_side:
        scale = max_side / max(w, h)
        w = max(1, round(w * scale))
        h = max(1, round(h * scale))
        img = img.resize((w, h), Image.LANCZOS)
    return img


def _fixture_data() -> dict:
    thumbhash_images = []
    blurhash_images = []
    colorthief_bytes = []

    for path in IMAGE_PATHS:
        fitted = _fit_thumbhash_image(_load_image(path))
        thumbhash_images.append(
            {
                "name": path.name,
                "w": fitted.size[0],
                "h": fitted.size[1],
                "rgba": fitted.tobytes(),
                "pil": fitted,
            }
        )
        blurhash_images.append(
            {
                "name": path.name,
                "w": fitted.size[0],
                "h": fitted.size[1],
                "rgba": fitted.tobytes(),
                "pil": fitted,
            }
        )
        colorthief_bytes.append(
            {
                "name": path.name,
                "bytes": path.read_bytes(),
            }
        )

    return {
        "thumbhash": thumbhash_images,
        "blurhash": blurhash_images,
        "colorthief": colorthief_bytes,
    }


FIXTURES = _fixture_data()


# ── Benchmark harness ────────────────────────────────────────────────────────


def _bench(
    fn: Callable, rounds: int = 3, warmup: int = 1, iterations: int = 100
) -> dict:
    for _ in range(warmup):
        for _ in range(max(1, iterations // 10)):
            fn()

    round_means: list[float] = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        for _ in range(iterations):
            fn()
        elapsed = time.perf_counter() - t0
        round_means.append(elapsed / iterations * 1_000_000)

    return {
        "mean_us": statistics.mean(round_means),
        "median_us": statistics.median(round_means),
        "stdev_us": statistics.stdev(round_means) if len(round_means) > 1 else 0.0,
        "min_us": min(round_means),
        "max_us": max(round_means),
    }


def _fmt(us: float) -> str:
    if us >= 1_000_000:
        return f"{us / 1_000_000:.2f} s"
    if us >= 1_000:
        return f"{us / 1_000:.2f} ms"
    return f"{us:.1f} µs"


def _average(values: list[dict], key: str) -> float:
    return statistics.mean(item[key] for item in values)


# ── Benchmarks ───────────────────────────────────────────────────────────────


def bench_thumbhash(rounds: int, warmup: int, iters: int) -> list[dict]:
    rows: list[dict] = []

    rust_encodes = []
    rust_decodes = []
    for item in FIXTURES["thumbhash"]:
        rust_encodes.append(
            _bench(
                lambda item=item: thumbleweed.thumbhash_encode(
                    item["w"], item["h"], item["rgba"]
                ),
                rounds,
                warmup,
                iters,
            )
        )
    for item in FIXTURES["thumbhash"]:
        h = thumbleweed.thumbhash_encode(item["w"], item["h"], item["rgba"])
        rust_decodes.append(
            _bench(lambda h=h: thumbleweed.thumbhash_decode(h), rounds, warmup, iters)
        )

    rows.append(
        {
            "lib": "thumbleweed (Rust)",
            "op": "ThumbHash encode (real test images)",
            "mean_us": _average(rust_encodes, "mean_us"),
        }
    )
    rows.append(
        {
            "lib": "thumbleweed (Rust)",
            "op": "ThumbHash decode (real test images)",
            "mean_us": _average(rust_decodes, "mean_us"),
        }
    )

    if HAS_TH_PY:
        py_encodes = []
        py_decodes = []
        for item in FIXTURES["thumbhash"]:
            pil_img = (
                item["pil"]
                if "pil" in item
                else Image.frombytes("RGBA", (item["w"], item["h"]), item["rgba"])
            )
            py_encodes.append(
                _bench(
                    lambda pil_img=pil_img: _th_py.image_to_thumbhash(pil_img),
                    rounds,
                    warmup,
                    max(1, iters // 20),
                )
            )
            th_hash_str = _th_py.image_to_thumbhash(pil_img)
            py_decodes.append(
                _bench(
                    lambda th_hash_str=th_hash_str: _th_py.thumbhash_to_image(
                        th_hash_str
                    ),
                    rounds,
                    warmup,
                    max(1, iters // 20),
                )
            )

        rows.append(
            {
                "lib": "thumbhash-python (pure Python)",
                "op": "ThumbHash encode (real test images)",
                "mean_us": _average(py_encodes, "mean_us"),
            }
        )
        rows.append(
            {
                "lib": "thumbhash-python (pure Python)",
                "op": "ThumbHash decode (real test images)",
                "mean_us": _average(py_decodes, "mean_us"),
            }
        )
    return rows


def bench_blurhash(rounds: int, warmup: int, iters: int) -> list[dict]:
    rows: list[dict] = []
    rust_encodes = []
    rust_decodes = []
    py_encodes = []
    py_decodes = []

    for item in FIXTURES["blurhash"]:
        rust_encodes.append(
            _bench(
                lambda item=item: thumbleweed.blurhash_encode(
                    item["rgba"], 4, 3, item["w"], item["h"]
                ),
                rounds,
                warmup,
                iters,
            )
        )
        bh = thumbleweed.blurhash_encode(item["rgba"], 4, 3, item["w"], item["h"])
        rust_decodes.append(
            _bench(
                lambda bh=bh: thumbleweed.blurhash_decode(bh, 64, 64),
                rounds,
                warmup,
                iters,
            )
        )

        if HAS_BH_PY:
            pil_img = item["pil"]
            py_encodes.append(
                _bench(
                    lambda pil_img=pil_img: _bh_py.encode(pil_img, 4, 3),
                    rounds,
                    warmup,
                    max(1, iters // 20),
                )
            )
            bh_py = _bh_py.encode(pil_img, 4, 3)
            py_decodes.append(
                _bench(
                    lambda bh_py=bh_py: _bh_py.decode(bh_py, 64, 64),
                    rounds,
                    warmup,
                    max(1, iters // 20),
                )
            )

    rows.append(
        {
            "lib": "thumbleweed (Rust)",
            "op": "BlurHash encode (real test images)",
            "mean_us": _average(rust_encodes, "mean_us"),
        }
    )
    rows.append(
        {
            "lib": "thumbleweed (Rust)",
            "op": "BlurHash decode 64×64 (real test images)",
            "mean_us": _average(rust_decodes, "mean_us"),
        }
    )
    if HAS_BH_PY:
        rows.append(
            {
                "lib": "blurhash-python (pure Python)",
                "op": "BlurHash encode (real test images)",
                "mean_us": _average(py_encodes, "mean_us"),
            }
        )
        rows.append(
            {
                "lib": "blurhash-python (pure Python)",
                "op": "BlurHash decode 64×64 (real test images)",
                "mean_us": _average(py_decodes, "mean_us"),
            }
        )
    return rows


def bench_colorthief(rounds: int, warmup: int, iters: int) -> list[dict]:
    rows: list[dict] = []
    rust_dom = []
    rust_pal = []
    py_dom = []
    py_pal = []

    import io

    for item in FIXTURES["colorthief"]:
        raw = item["bytes"]
        rust_dom.append(
            _bench(
                lambda raw=raw: thumbleweed.colorthief_get_color_bytes(raw),
                rounds,
                warmup,
                iters,
            )
        )
        rust_pal.append(
            _bench(
                lambda raw=raw: thumbleweed.colorthief_get_palette_bytes(raw, 10),
                rounds,
                warmup,
                iters,
            )
        )

        if HAS_FCT:

            def _dom(raw=raw):
                buf = io.BytesIO(raw)
                return _fct.get_dominant_color(buf, quality=10)

            def _pal(raw=raw):
                buf = io.BytesIO(raw)
                return _fct.get_palette(buf, color_count=10, quality=10)

            py_dom.append(_bench(_dom, rounds, warmup, iters))
            py_pal.append(_bench(_pal, rounds, warmup, iters))

    rows.append(
        {
            "lib": "thumbleweed (Rust)",
            "op": "ColorThief dominant (real test images)",
            "mean_us": _average(rust_dom, "mean_us"),
        }
    )
    rows.append(
        {
            "lib": "thumbleweed (Rust)",
            "op": "ColorThief palette-10 (real test images)",
            "mean_us": _average(rust_pal, "mean_us"),
        }
    )
    if HAS_FCT:
        rows.append(
            {
                "lib": "fast-colorthief (C ext + NumPy)",
                "op": "ColorThief dominant (real test images)",
                "mean_us": _average(py_dom, "mean_us"),
            }
        )
        rows.append(
            {
                "lib": "fast-colorthief (C ext + NumPy)",
                "op": "ColorThief palette-10 (real test images)",
                "mean_us": _average(py_pal, "mean_us"),
            }
        )
    return rows


# ── Reporting ────────────────────────────────────────────────────────────────


def _speedup(our_us: float | None, their_us: float | None) -> str:
    if our_us is None or their_us is None or our_us <= 0:
        return "—"
    x = their_us / our_us
    if x >= 1:
        return f"**{x:.1f}×** faster"
    return f"{1 / x:.1f}× slower"


def render_markdown_table(all_rows: list[dict], rounds: int, iters: int) -> str:
    lines: list[str] = []
    lines.append("## Performance Benchmark Results")
    lines.append("")
    lines.append(
        f"> Benchmark configuration: {rounds} rounds × {iters} iterations (pure-Python libraries use {max(1, iters // 20)} iterations)."
    )
    lines.append(
        "> Input corpus: all real image fixtures in `tests/` (`one.jpg`, `two.jpg`, `four.jpg`, `OPS.jpg`)."
    )
    lines.append("> All times are mean per-call latency. Lower is better.")
    lines.append("")

    lines.append("| Operation | thumbleweed | Comparison | Result |")
    lines.append("|-----------|-------------|------------|--------|")

    ops: dict[str, list[dict]] = {}
    for row in all_rows:
        ops.setdefault(row["op"], []).append(row)

    for op, op_rows in ops.items():
        ours = next((r for r in op_rows if r["lib"].startswith("thumbleweed")), None)
        if ours is None:
            raise RuntimeError(f"missing thumbleweed benchmark result for {op!r}")

        competitors = [r for r in op_rows if not r["lib"].startswith("thumbleweed")]
        if not competitors:
            lines.append(f"| {op} | {_fmt(ours['mean_us'])} | — | — |")
            continue

        for row in competitors:
            lines.append(
                f"| {op} | {_fmt(ours['mean_us'])} | {row['lib']}: {_fmt(row['mean_us'])} | {_speedup(ours['mean_us'], row.get('mean_us'))} |"
            )

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="thumbleweed performance benchmark")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--iters", type=int, default=100)
    args = parser.parse_args()

    print(f"thumbleweed benchmark — Python {sys.version.split()[0]}", flush=True)
    print(f"Using real test images: {', '.join(path.name for path in IMAGE_PATHS)}")
    print()

    print("Running ThumbHash benchmarks...", end=" ", flush=True)
    th_rows = bench_thumbhash(args.rounds, args.warmup, args.iters)
    print("done")
    print("Running BlurHash benchmarks...", end=" ", flush=True)
    bh_rows = bench_blurhash(args.rounds, args.warmup, args.iters)
    print("done")
    print("Running ColorThief benchmarks...", end=" ", flush=True)
    ct_rows = bench_colorthief(args.rounds, args.warmup, args.iters)
    print("done")

    markdown = render_markdown_table(
        th_rows + bh_rows + ct_rows, args.rounds, args.iters
    )
    print()
    print("<!-- BENCHMARK_TABLE:START -->")
    print(markdown)
    print("<!-- BENCHMARK_TABLE:END -->")


if __name__ == "__main__":
    main()
