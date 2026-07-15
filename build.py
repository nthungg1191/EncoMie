import os
import sys
import shutil
import subprocess
from pathlib import Path

def print_step(msg):
    print(f"\n========================================\n[STEP] {msg}\n========================================")

def main():
    root_dir = Path(__file__).resolve().parent
    os.chdir(root_dir)
    
    # 1. Check/Install PyInstaller
    print_step("Checking PyInstaller installation...")
    try:
        import PyInstaller
        print("[INFO] PyInstaller is already installed.")
    except ImportError:
        print("[INFO] PyInstaller not found. Installing via pip...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
            print("[INFO] PyInstaller installed successfully.")
        except Exception as e:
            print(f"[ERROR] Failed to install PyInstaller: {e}")
            print("[ERROR] Please install it manually: pip install pyinstaller")
            sys.exit(1)

    # 2. Parse arguments for onefile vs onedir
    # Default to onedir (directory mode) because it is faster to start, but allow --onefile
    onefile = "--onefile" in sys.argv or "-F" in sys.argv
    mode_str = "One-File (.exe)" if onefile else "One-Directory (Folder)"
    print(f"[INFO] Building in {mode_str} mode.")

    # 3. Clean previous builds
    print_step("Cleaning old build/dist directories...")
    for folder in ["build", "dist"]:
        if os.path.exists(folder):
            print(f"[INFO] Removing existing {folder} folder...")
            shutil.rmtree(folder, ignore_errors=True)
            
    # 4. Construct PyInstaller command
    pyinstaller_cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name=EncoMie",
        "--noconsole",
        "--icon=Asset/Img/Logo.ico",
        "--add-data=Asset;Asset",
        "--add-data=presets;presets",
        "--clean",
    ]
    
    if onefile:
        pyinstaller_cmd.append("--onefile")
    else:
        pyinstaller_cmd.append("--onedir")
        
    pyinstaller_cmd.append("main.py")
    
    print_step(f"Running PyInstaller command: {' '.join(pyinstaller_cmd)}")
    try:
        subprocess.run(pyinstaller_cmd, check=True)
        print("[INFO] PyInstaller build finished successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] PyInstaller execution failed: {e}")
        sys.exit(1)

    # 5. Copy bin directory (ffmpeg and ffprobe) to the output folder
    print_step("Copying FFmpeg bin folder to release directory...")
    src_bin = root_dir / "bin"
    
    if onefile:
        dest_bin = root_dir / "dist" / "bin"
    else:
        dest_bin = root_dir / "dist" / "EncoMie" / "bin"
        
    if src_bin.exists():
        print(f"[INFO] Copying {src_bin} to {dest_bin}...")
        shutil.copytree(src_bin, dest_bin, dirs_exist_ok=True)
        print("[INFO] Bin directory copied.")
    else:
        print("[WARNING] 'bin' directory not found in project root. Make sure ffmpeg.exe and ffprobe.exe are placed manually.")

    # 6. Archive/Zip the output for easy distribution
    print_step("Creating ZIP archive for distribution...")
    zip_name = "EncoMie_Windows"
    archive_format = "zip"
    
    try:
        if onefile:
            # For onefile, we zip the EncoMie.exe + bin folder
            dist_dir = root_dir / "dist"
            archive_dir = root_dir / "dist_release"
            if archive_dir.exists():
                shutil.rmtree(archive_dir)
            os.makedirs(archive_dir)
            shutil.copy2(dist_dir / "EncoMie.exe", archive_dir / "EncoMie.exe")
            if dest_bin.exists():
                shutil.copytree(dest_bin, archive_dir / "bin")
            shutil.make_archive(str(root_dir / zip_name), archive_format, archive_dir)
            shutil.rmtree(archive_dir)
        else:
            # For onedir, we zip the entire EncoMie folder
            target_dir = root_dir / "dist" / "EncoMie"
            shutil.make_archive(str(root_dir / zip_name), archive_format, root_dir / "dist", "EncoMie")
            
        print(f"[INFO] Release archive created: {zip_name}.zip")
    except Exception as e:
        print(f"[WARNING] Failed to create ZIP archive: {e}")

    print("\n[SUCCESS] Packaging process completed successfully!")
    print(f"Check the 'dist' directory for the executable/folder.")
    print(f"Check the root directory for '{zip_name}.zip'.")

if __name__ == "__main__":
    main()
