# CLAUDE.md — thumbleweed

> This file is the authoritative reference for AI assistants (and humans) working on this repository.
> It describes the architecture, conventions, API surface, roadmap ideas, and security/performance notes.

---

## 1. Project overview

**thumbleweed** is a unified Python image-hashing library backed by a Rust core via [PyO3](https://pyo3.rs/) + [maturin](https://www.maturin.rs/).

It ships **three algorithms** under one wheel, with zero mandatory Python dependencies:

| Algorithm | What it does | Drop-in replacement for |
|-----------|-------------|------------------------|
| **ThumbHash** | Compact, high-fidelity image placeholder hash (supports alpha) | `thumbhash-python`, `fast-thumbhash` |
| **BlurHash** | Smooth gradient placeholder string | `blurhash-python` |
| **ColorThief** | Dominant colour + palette extraction from any image format | `colorthief`, `fast-colorthief` |

**Key properties:**
- Pure-Rust algorithms — no C extensions, no NumPy, no OpenCV
- Pillow (`>11`) is **optional** — needed only for the `encode_image` / `decode_image` helpers that accept `PIL.Image` objects
- Fully typed: `py.typed` marker + `.pyi` stub file for `_core`
- Supports CPython 3.10–3.14 including free-threaded (`3.13t`, `3.14t`)
- GIL released for all CPU-bound operations via `py.detach()`

---

## 2. Repository structure

```
thumbleweed/
├── src/                        # Rust source
│   ├── lib.rs                  # PyO3 module — all Python bindings, registers functions
│   ├── thumbhash.rs            # Pure Rust ThumbHash encode / decode
│   ├── blurhash.rs             # Pure Rust BlurHash encode / decode (base-83)
│   └── colorthief.rs           # ColorThief: wraps the `color-thief` crate
├── python/                     # Python source (maturin python-source)
│   ├── thumbleweed/
│   │   ├── __init__.py         # Unified top-level package; lazy re-exports image helpers
│   │   ├── _core.pyi           # Type stubs for the compiled Rust extension
│   │   └── py.typed            # PEP 561 marker
│   ├── thumbhash/
│   │   └── __init__.py         # Backward-compatible shim; encode_image / decode_image helpers
│   ├── blurhash/
│   │   └── __init__.py         # Backward-compatible shim; encode_image / decode_image helpers
│   └── colorthief/
│       └── __init__.py         # Compatibility shim; get_color / get_palette / ColorThief
├── tests/
│   ├── test_thumbhash.py       # 70+ ThumbHash tests (raw bytes, Pillow, BytesIO, edge cases)
│   ├── test_blurhash.py        # 28+ BlurHash tests
│   ├── test_colorthief.py      # 30+ ColorThief tests including BytesIO / PIL.Image variants
│   ├── test_imports.py         # Import consistency & version-parity checks
│   ├── bench_comparison.py     # Head-to-head performance benchmark; output is injected into README.md
│   └── *.jpg                   # Real JPEG test fixtures (one.jpg, two.jpg, four.jpg, OPS.jpg)
├── scripts/
│   ├── update_readme.py         # Runs benchmark and refreshes README.md benchmark block
│   └── build_all.sh             # Local wheel build helper for supported interpreters
├── Cargo.toml                  # Rust dependencies
├── pyproject.toml              # PEP 621 metadata + maturin config
├── .github/workflows/          # CI: build wheels for Linux x86_64/aarch64, macOS, Windows
└── .nextest.toml               # cargo-nextest config (Rust unit tests)
```

---

## 3. Architecture

### 3.1 Rust core (`src/`)

Each algorithm lives in its own `.rs` file with:
- A typed **error enum** deriving `thiserror::Error`
- `impl From<XError> for PyErr` so `?` at the Rust→Python boundary becomes a `ValueError`
- Pure functions operating on `&[u8]` / `Vec<u8>` — no PyO3 types inside the algorithm
- `#[cfg(test)]` unit tests (run with `cargo test` / `cargo nextest run`)

**PyO3 bindings** all live in `src/lib.rs`:
- Each `#[pyfunction]` is a thin wrapper that calls `py.detach(|| ...)` to release the GIL, then forwards to the algorithm
- Function naming convention: `{algorithm}_{verb}` e.g. `thumbhash_encode`, `blurhash_decode`, `colorthief_get_palette_bytes`

### 3.2 Python shim packages (`python/`)

Three compatibility packages (`thumbhash`, `blurhash`, `colorthief`) mirror the APIs of the libraries they replace.

Each shim imports exclusively from `thumbleweed._core` — **never** from `thumbleweed` — to avoid circular imports.

`thumbleweed/__init__.py` imports core functions eagerly from `_core`, then re-exports the higher-level `encode_image`/`decode_image` helpers and strict ColorThief `get_color`/`get_palette` helpers **lazily** via `__getattr__` to avoid the circular import that would arise from importing the shim packages at module load time.

### 3.3 Input normalisation

All higher-level image helper functions (`encode_image`, `get_color`, `get_palette`) accept:

| Input type | Behaviour |
|------------|-----------|
| `PIL.Image.Image` | Used directly by ThumbHash/BlurHash helpers (Pillow required because caller supplied a Pillow object); converted to encoded PNG bytes for ColorThief |
| `bytes` / `bytearray` / `memoryview` | Treated as encoded image data (PNG/JPEG/WebP/GIF/BMP) — decoded in Rust via the `image` crate; no Pillow required |
| File-like with `.read()` (`io.BytesIO`, open file) | Read to EOF, then decoded in Rust via the `image` crate; no Pillow required |
| `str` / `pathlib.Path` | Opened in binary mode, then decoded in Rust via the `image` crate; no Pillow required |

Raw pixel-level APIs (`thumbhash_encode`, `blurhash_encode`) accept `bytes`, `bytearray`, or `memoryview` of raw RGBA pixel data directly — **no Pillow required**.

---

## 4. Dependencies

### Rust (`Cargo.toml`)
| Crate | Purpose |
|-------|---------|
| `pyo3 ^0.28.3` | Python ↔ Rust bindings |
| `thiserror 2` | Ergonomic error types |
| `image 0.25` | Decode PNG/JPEG/WebP/GIF/BMP from bytes / file |
| `color-thief 0.2` | Median-cut palette extraction |
| `itertools 0.13` | `.unique()` deduplication of palette entries |

### Python (runtime)
- **None** — zero mandatory runtime dependencies
- `Pillow >11` optional (for `encode_image` / `decode_image` helpers)

### Python (dev)
```
maturin >=1.10,<2
Pillow >12
pytest >=9
```

---

## 5. API reference

### 5.1 `thumbhash` / `thumbleweed.thumbhash_*`

| Function | Input | Output | Notes |
|----------|-------|--------|-------|
| `encode(w, h, rgba)` | width, height, raw RGBA bytes | `bytes` (5–32 B) | w,h ≤ 100; len(rgba) == w×h×4 |
| `decode(hash)` | ThumbHash bytes | `(w, h, rgba_bytes)` | Output ≈32 px, RGBA |
| `average_rgba(hash)` | ThumbHash bytes | `(r,g,b,a)` floats [0,1] | RGB not premultiplied |
| `approximate_aspect_ratio(hash)` | ThumbHash bytes | `float` | w/h of original |
| `encode_image(image)` | Any (see §3.3) | `str` | Base64 ThumbHash string; Pillow required only for `PIL.Image.Image` inputs |
| `decode_image(hash)` | Base64 ThumbHash string or raw ThumbHash bytes | `PIL.Image` (RGBA) | Requires Pillow |

### 5.2 `blurhash` / `thumbleweed.blurhash_*`

| Function | Input | Output | Notes |
|----------|-------|--------|-------|
| `encode(pixels, cx, cy, w, h)` | raw RGBA bytes, components | `str` | cx,cy ∈ [1,9] |
| `decode(hash, w, h)` | BlurHash string, output size | `bytes` (RGBA) | alpha=255 always |
| `encode_image(image, cx, cy)` | Any (see §3.3) | `str` | Pillow required only for `PIL.Image.Image` inputs |
| `decode_image(hash, w, h)` | BlurHash string | `PIL.Image` (RGBA) | Requires Pillow |

### 5.3 `colorthief` / `thumbleweed.colorthief_*`

| Function | Input | Output | Notes |
|----------|-------|--------|-------|
| `get_color(image)` | Any (see §3.3) | `(r,g,b)` | normalises input first |
| `get_palette(image, color_count, quality)` | Any (see §3.3) | `list[(r,g,b)]` | deduplicated, normalises input first |
| `ColorThief(image)` | Any (see §3.3) | instance | class-based API |
| `ColorThief.get_color(quality)` | — | `(r,g,b)` | |
| `ColorThief.get_palette(color_count, quality)` | — | `list[(r,g,b)]` | |

**ColorThief quality parameter:** must be in `[1, 10]` (1 = best/slowest, 10 = fastest). Values outside this range raise `ValueError`.

---

## 6. Development workflow

### Build
```bash
python -m venv .venv && . .venv/bin/activate
pip install "maturin>=1.10,<2" "Pillow>12" pytest
maturin develop          # debug build
maturin develop --release  # optimised build
```

### Test
```bash
pytest -v                   # Python tests
cargo test                  # Rust unit tests
cargo nextest run           # Rust tests via nextest (preferred)
```

### Benchmark
```bash
pip install blurhash-python thumbhash-python fast-colorthief numpy
python tests/bench_comparison.py --rounds 5 --warmup 2 --iters 500
```

### Build wheels (local)

All supported Python interpreters must be installed on PATH:
`python3.10`, `python3.11`, `python3.12`, `python3.13`, `python3.13-nogil`, `python3.14`, `python3.14-nogil`

On Ubuntu, install them via the [deadsnakes PPA](https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa):
```bash
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get install -y python3.10-dev python3.11-dev python3.12-dev python3.13-dev python3.13-nogil python3.14-dev python3.14-nogil
```

Then run the build script:
```bash
chmod +x build_all.sh
./build_all.sh            # builds 7 wheels + sdist into dist/
./build_all.sh --upload   # build + upload to PyPI via twine
```

The script:
1. Iterates over every supported interpreter (GIL + free-threaded)
2. Calls `maturin build --release --skip-auditwheel` for each
3. Builds an sdist with `maturin sdist`
4. Validates all artifacts with `twine check`

> **Note:** `--skip-auditwheel` is needed because the host glibc is typically
> too new for manylinux compliance. For production manylinux-compliant wheels,
> use the CI workflow (below) which builds inside the manylinux Docker image.

### Release / CI
- Wheels are built by `.github/workflows/` on `v*` tags via `maturin-action`
- Targets: Linux x86_64 + aarch64 (manylinux2014), macOS x86_64 + aarch64, Windows x86_64
- All supported Python versions (3.10–3.14 including free-threaded `t` builds) are built per target
- CI uses the manylinux Docker image so wheels are portable (no `--skip-auditwheel` needed)

---

## 7. Performance benchmarks and review notes

Benchmark tables are generated only in `README.md` between the `BENCHMARK_TABLE` markers. `scripts/update_readme.py` runs `tests/bench_comparison.py` and refreshes that README block; `make prepare` calls this script.

**Notes on ColorThief timing:** thumbleweed includes image decode in its timing because it accepts raw encoded bytes from the real test fixtures, while `fast-colorthief` also reads from in-memory file-like objects in these benchmarks. This measures realistic end-to-end usage rather than just the inner palette routine.

### Security/performance review notes

Reviewed areas: `src/`, `python/`, `tests/`, `scripts/`, `Makefile`, `Cargo.toml`, and `pyproject.toml`.

Minimal fixes made:
- Benchmark fixture image loading uses a context manager so Pillow file handles are closed promptly.
- Benchmark fixture setup avoids an unnecessary initial image copy before resizing.
- File-like input normalisation restores seek position in `finally` for ThumbHash, BlurHash, and ColorThief helpers.
- BlurHash decoding rejects invalid base-83 characters instead of silently treating them as zero.

Follow-up considerations:
- ColorThief converts decoded images to RGBA before palette extraction, which is simple and safe but does extra work for opaque RGB images.
- Very large encoded image inputs are delegated to the `image` crate; callers handling untrusted input should apply application-level upload size limits.

---

## 8. Known issues / gotchas

| Issue | Detail |
|-------|--------|
| `thumbhash-python` 0.1.2 bug | `thumb_hash_to_rgba()` has a stray `print(ratio)` on stdout. Our benchmark suppresses it via `os.dup2`. This is a bug in the upstream package, not in thumbleweed. |
| `blurhash-python` API | `blurhash.encode()` expects a NumPy `H×W×C` array, not a PIL Image. |
| `fast-colorthief` API | `get_dominant_color()` / `get_palette()` expect a file path or `BytesIO`, not a PIL Image. |
| ColorThief quality range | The upstream `color-thief` Rust crate hard-asserts `1 ≤ quality ≤ 10`. thumbleweed validates this and raises `ValueError` before calling the crate. |
| Circular import | `thumbleweed/__init__.py` uses `__getattr__` for lazy imports of the shim helpers to avoid: `thumbleweed` → `blurhash` → `thumbleweed._core` (partially initialised) → `thumbleweed`. |
| `image` crate always converts to RGBA8 | For ColorThief, any input image (RGB, JPEG, etc.) is converted to RGBA8 before palette extraction. This is slightly wasteful for opaque images but simplifies the code and is fast. |

---

## 9. What else could this library do?

Below are natural extensions, roughly ordered by value vs. effort:

### High value / low effort
- **Average/dominant colour from ThumbHash** — already exposed as `thumbhash_average_rgba()`; add a `dominant_color_from_hash()` that converts the `(r,g,b,a)` float tuple to `(int, int, int)` for easy consumption alongside ColorThief results
- **`colorthief` quality validation in Python** — surface a named constant `colorthief.MAX_QUALITY = 10` so callers don't need to guess the range

### Medium value / medium effort
- **Perceptual hash (pHash / dHash / aHash)** — fast, compact fingerprints for near-duplicate detection; good complement to the existing placeholder hashes
- **Palette-to-CSS** helper — `colorthief.to_css(palette)` returning `["#b43c28", ...]`
- **Async-friendly wrappers** — thin `async def encode_image_async(...)` wrappers using `asyncio.to_thread` for use in FastAPI / asyncio services without blocking the event loop
- **Streaming / chunked ColorThief** — accept image data incrementally rather than requiring the whole buffer at once (useful for large raw images received over a network)
- **WebP / AVIF / JXL encode output for decode_image** — currently `decode_image` always returns a Pillow RGBA Image; offer a `decode_image_bytes(hash, format="webp")` returning compressed bytes
- **`thumbhash` ↔ `blurhash` interop** — given a BlurHash, generate a ThumbHash approximation from the decoded pixels (and vice-versa); useful for migrating between the two standards

### Lower priority / research
- **GPU-accelerated palette extraction** — the `color-thief` crate is CPU-only; an optional WGPU/Metal/CUDA path could be interesting at very large scale
- **WASM / `wasm32-unknown-unknown` target** — maturin supports `wasm32-wasi`; a WASM build would let the same Rust core run in a browser or Cloudflare Worker
- **Batch API** — `thumbhash_encode_batch([(w1,h1,rgba1), ...])` releasing the GIL once and processing all images in a Rayon parallel iterator
- **Python 3.13 free-threaded (`nogil`) benchmarks** — the CI already builds `t` wheels; add a benchmark that spawns multiple threads and shows the GIL-free throughput scaling

---

## 10. Versioning

The Python package version is set in `pyproject.toml` (`project.version`) and mirrored into the Rust extension via `env!("CARGO_PKG_VERSION")` from `Cargo.toml`. Both must be kept in sync. All four importable packages (`thumbleweed`, `thumbhash`, `blurhash`, `colorthief`) report the same `__version__` string from the compiled extension.
