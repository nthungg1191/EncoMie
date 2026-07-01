import os
import sys
import shutil
import subprocess
from pathlib import Path


def print_banner(text):
    print("=" * 60)
    print(f" {text}")
    print("=" * 60)


def install_if_missing(pip_name, import_name):
    try:
        __import__(import_name)
        print(f"  - {pip_name}: Đã cài đặt")
        return True
    except ImportError:
        print(f"  - {pip_name}: Chưa cài đặt. Đang cài đặt...")

    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", pip_name],
            check=True
        )
        __import__(import_name)
        print(f"  - {pip_name}: Cài đặt thành công!")
        return True
    except Exception as e:
        print(f"  - Lỗi khi cài {pip_name}: {e}")
        return False


def main():
    print_banner("ENCOMIE - BẮT ĐẦU ĐÓNG GÓI ỨNG DỤNG")

    root_dir = Path(__file__).parent.resolve()

    main_py = root_dir / "main.py"
    asset_dir = root_dir / "Asset"
    presets_dir = root_dir / "presets"
    img_dir = asset_dir / "Img"
    logo_png = img_dir / "Logo.png"
    logo_ico = img_dir / "Logo.ico"
    bin_dir = root_dir / "bin"

    # 0. Kiểm tra file chính
    if not main_py.exists():
        print(f"Lỗi: Không tìm thấy file main.py tại: {main_py}")
        return

    # 1. Kiểm tra thư viện yêu cầu
    print("[1/5] Kiểm tra và cài đặt thư viện cần thiết...")

    required_libs = {
        "pyinstaller": "PyInstaller",
        "Pillow": "PIL",
    }

    for pip_name, import_name in required_libs.items():
        ok = install_if_missing(pip_name, import_name)
        if not ok:
            print("Vui lòng tự chạy:")
            print("python -m pip install pyinstaller Pillow")
            return

    # 2. Tạo file Logo.ico từ Logo.png
    print("\n[2/5] Tạo file icon ứng dụng (Logo.ico)...")

    if not logo_png.exists():
        print(f"  - Cảnh báo: Không tìm thấy logo tại: {logo_png}")
        print("  - Ứng dụng sẽ được đóng gói với icon mặc định.")
    else:
        try:
            from PIL import Image

            img = Image.open(logo_png)

            if img.mode != "RGBA":
                img = img.convert("RGBA")

            img.save(
                logo_ico,
                format="ICO",
                sizes=[
                    (256, 256),
                    (128, 128),
                    (64, 64),
                    (32, 32),
                    (16, 16),
                ],
            )

            print(f"  - Tạo file icon thành công tại: {logo_ico}")

        except Exception as e:
            print(f"  - Lỗi khi chuyển đổi logo sang ICO: {e}")
            print("  - Ứng dụng sẽ được đóng gói với icon mặc định.")

    # 3. Đóng gói bằng PyInstaller
    print("\n[3/5] Đang đóng gói bằng PyInstaller...")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconsole",
        "--onedir",
        "--name=EncoMie",
        "--clean",
        "--add-data",
        f"{asset_dir}{os.pathsep}Asset",
    ]

    if presets_dir.exists():
        cmd.extend([
            "--add-data",
            f"{presets_dir}{os.pathsep}presets",
        ])
    else:
        print("  - Cảnh báo: Không tìm thấy thư mục presets/, bỏ qua.")

    if logo_ico.exists():
        cmd.extend(["--icon", str(logo_ico)])

    cmd.append(str(main_py))

    print("  - Lệnh build:")
    print(" ".join(cmd))

    try:
        subprocess.run(cmd, cwd=root_dir, check=True)
        print("\n  - Biên dịch thành công!")
    except subprocess.CalledProcessError as e:
        print(f"\n  - Lỗi khi đóng gói bằng PyInstaller. Exit code: {e.returncode}")
        return
    except Exception as e:
        print(f"\n  - Lỗi khi đóng gói bằng PyInstaller: {e}")
        return

    # 4. Sao chép thư mục bin vào dist/EncoMie/bin
    print("\n[4/5] Sao chép thư mục công cụ FFmpeg bin/ vào sản phẩm đóng gói...")

    dist_dir = root_dir / "dist" / "EncoMie"
    dist_bin_target = dist_dir / "bin"

    if not dist_dir.exists():
        print(f"  - Lỗi: Không tìm thấy thư mục output: {dist_dir}")
        return

    if bin_dir.exists():
        if dist_bin_target.exists():
            shutil.rmtree(dist_bin_target)

        shutil.copytree(bin_dir, dist_bin_target)
        print(f"  - Đã sao chép thư mục bin vào: {dist_bin_target}")
    else:
        print("  - Cảnh báo: Không tìm thấy thư mục bin/ ở gốc dự án.")
        print("  - Nếu app cần FFmpeg, hãy đặt ffmpeg.exe và ffprobe.exe vào:")
        print(f"    {dist_bin_target}")

    # 5. Dọn dẹp file rác
    print("\n[5/5] Dọn dẹp thư mục tạm...")

    spec_file = root_dir / "EncoMie.spec"
    build_temp_dir = root_dir / "build"

    if spec_file.exists():
        os.remove(spec_file)

    if build_temp_dir.exists():
        shutil.rmtree(build_temp_dir)

    print("  - Đã dọn dẹp file .spec và thư mục build/ tạm thời.")

    print("\n" + "=" * 60)
    print(" ĐÓNG GÓI HOÀN TẤT THÀNH CÔNG!")
    print("=" * 60)
    print(f" Thư mục sản phẩm: {dist_dir}")
    print(f" File chạy ứng dụng: {dist_dir / 'EncoMie.exe'}")
    print(f" Thư mục FFmpeg đi kèm: {dist_bin_target}")
    print("=" * 60)


if __name__ == "__main__":
    main()