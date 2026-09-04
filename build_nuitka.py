"""
Nuitka packaging for EncoMie — compiles the app to a native binary instead of
shipping Python bytecode.

Why: the PyInstaller build (build.py) can be unpacked with `pyinstxtractor` and
the `.pyc` decompiled back to readable source in minutes, which exposes the
whole licence path (license_manager.py / security.py / entitlements.py). Nuitka
compiles Python -> C -> machine code, so there is no bytecode to decompile.

Usage:
    python build_nuitka.py            # standalone folder (default)
    python build_nuitka.py --onefile  # single .exe (slower start, more AV noise)

Notes:
  * The C build runs OUTSIDE the project folder (in the temp dir) so the IDE's
    file watcher / AV real-time scan can't lock Nuitka's generated .c/.o files
    mid-build. Only the finished dist is copied back into ./dist.
  * First run downloads a bundled C compiler (zig). ~5-15 min; later builds cache.
  * pip install nuitka  (done automatically here if missing)
"""

import os
import sys
import time
import shutil
import tempfile
import subprocess
from pathlib import Path

APP_NAME = "EncoMie"
ENTRY = "main.py"
VERSION = "1.5.0"


def step(msg: str) -> None:
    print(f"\n{'=' * 60}\n[STEP] {msg}\n{'=' * 60}", flush=True)


def robust_rmtree(path: Path, attempts: int = 6) -> None:
    """rmtree that copes with read-only files and transient locks (AV / IDE)."""
    for i in range(attempts):
        if not path.exists():
            return
        try:
            for p in path.rglob("*"):
                try:
                    p.chmod(0o777)
                except OSError:
                    pass
            shutil.rmtree(path)
            return
        except (PermissionError, OSError) as exc:
            wait = 2 * (i + 1)
            print(f"[warn] could not remove {path} ({exc}); retry in {wait}s", flush=True)
            time.sleep(wait)
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        raise RuntimeError(f"Cannot clean {path} — close the IDE / stop AV scanning it and retry.")


def kill_stale_builders() -> None:
    """Best-effort: kill leftover compiler processes from a crashed build."""
    if os.name != "nt":
        return
    for name in ("zig.exe", "scons.exe", "gcc.exe", "clang.exe", "ld.exe"):
        subprocess.run(["taskkill", "/F", "/IM", name, "/T"],
                       capture_output=True)


def run_nuitka(build_dir: Path, onefile: bool) -> Path:
    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        "--enable-plugin=pyqt6",
        "--windows-console-mode=disable",
        "--windows-icon-from-ico=Asset/Img/Logo.ico",
        "--include-data-dir=Asset=Asset",
        "--include-data-dir=presets=presets",
        "--include-package=nacl",
        "--include-module=_cffi_backend",
        "--include-module=core.entitlements",
        "--python-flag=no_asserts",
        "--python-flag=no_docstrings",
        f"--company-name={APP_NAME}",
        f"--product-name={APP_NAME}",
        f"--file-version={VERSION}",
        f"--product-version={VERSION}",
        "--file-description=EncoMie Auto Video Editor",
        f"--output-dir={build_dir}",
        f"--output-filename={APP_NAME}.exe",
        "--remove-output",
    ]
    if onefile:
        cmd.append("--onefile")
    cmd.append(ENTRY)

    print("  " + " ".join(cmd), flush=True)
    for attempt in (1, 2):
        result = subprocess.run(cmd)
        if result.returncode == 0:
            break
        if attempt == 1:
            print("[warn] Nuitka failed (often a transient file lock); "
                  "killing builders, cleaning, retrying once...", flush=True)
            kill_stale_builders()
            time.sleep(3)
            robust_rmtree(build_dir)
        else:
            raise SystemExit("Nuitka build failed twice — see output above.")

    if onefile:
        produced = build_dir / f"{APP_NAME}.exe"
        if not produced.exists():
            raise SystemExit(f"Expected {produced} not found.")
        return produced

    for cand in (build_dir / "main.dist", build_dir / f"{Path(ENTRY).stem}.dist"):
        if cand.exists():
            return cand
    raise SystemExit(f"Nuitka .dist folder not found under {build_dir}")


def main() -> None:
    root = Path(__file__).resolve().parent
    os.chdir(root)
    onefile = "--onefile" in sys.argv

    step("Installing runtime dependencies (requirements.txt)")
    req = root / "requirements.txt"
    if req.exists():
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req)], check=True)

    step("Ensuring Nuitka is installed")
    try:
        import nuitka  # noqa: F401
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "nuitka"], check=True)

    # Build outside the workspace so IDE/AV file locks don't break Scons.
    build_dir = Path(tempfile.gettempdir()) / "encomie-nuitka-build"

    step("Cleaning previous output")
    kill_stale_builders()
    robust_rmtree(build_dir)
    robust_rmtree(root / "dist")
    build_dir.mkdir(parents=True, exist_ok=True)

    step("Compiling with Nuitka (this takes a while)")
    produced = run_nuitka(build_dir, onefile)

    step("Assembling ./dist + FFmpeg")
    dist_root = root / "dist" / APP_NAME
    dist_root.mkdir(parents=True, exist_ok=True)

    if onefile:
        shutil.copy2(produced, dist_root / f"{APP_NAME}.exe")
    else:
        for item in produced.iterdir():
            target = dist_root / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)

    src_bin = root / "bin"
    if src_bin.exists():
        shutil.copytree(src_bin, dist_root / "bin", dirs_exist_ok=True)
        print(f"[INFO] Copied FFmpeg -> {dist_root / 'bin'}")
    else:
        print("[WARNING] bin/ not found — place ffmpeg.exe / ffprobe.exe manually.")

    step("Creating distribution ZIP")
    zip_base = root / f"{APP_NAME}_Windows_nuitka"
    if zip_base.with_suffix(".zip").exists():
        zip_base.with_suffix(".zip").unlink()
    shutil.make_archive(str(zip_base), "zip", root / "dist", APP_NAME)

    step("Cleaning temp build dir")
    robust_rmtree(build_dir)

    print(f"\n[SUCCESS] Nuitka build complete.")
    print(f"  App: {dist_root / (APP_NAME + '.exe')}")
    print(f"  Zip: {zip_base}.zip")
    print("\n>> Test the .exe end to end (activate a licence + run a full render)")
    print(">> and scan it with your AV before distributing.")


if __name__ == "__main__":
    main()
