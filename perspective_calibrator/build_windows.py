from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image


APP_NAME = "PerspectiveMatrixCalibrator"


def build_icon(source_path: Path, output_path: Path) -> Path:
    """!
    @brief 由 JPG Logo 生成 Windows 可执行文件图标。
    @param source_path 源图片路径。
    @param output_path 输出 ico 路径。
    @return 生成后的 ico 文件路径。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    source = Image.open(source_path).convert("RGBA")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    frames: list[Image.Image] = []

    for size in sizes:
        canvas = Image.new("RGBA", size, (0, 0, 0, 0))
        frame = source.copy()
        frame.thumbnail(size, Image.Resampling.LANCZOS)
        offset = ((size[0] - frame.width) // 2, (size[1] - frame.height) // 2)
        canvas.paste(frame, offset, frame)
        frames.append(canvas)

    frames[0].save(output_path, format="ICO", sizes=sizes)
    return output_path


def main() -> None:
    """!
    @brief 执行 Windows 单文件打包流程。

    @details
    自动查找 Logo、生成 ico 图标并调用 PyInstaller，
    输出带图标的单文件可执行程序。
    """
    tool_dir = Path(__file__).resolve().parent
    repo_root = tool_dir
    logo_candidates = [
        tool_dir / "assets" / "anan.jpg",
        tool_dir.parent / "LOGO" / "anan.jpg",
    ]
    logo_path = next((path for path in logo_candidates if path.exists()), logo_candidates[0])
    icon_path = tool_dir / "build_assets" / "anan.ico"
    dist_dir = tool_dir / "dist"
    build_dir = tool_dir / "build"
    spec_dir = tool_dir / "build_spec"
    app_path = tool_dir / "app.py"

    if not logo_path.exists():
        raise FileNotFoundError(f"Logo file not found: {logo_path}")

    pyinstaller_path = shutil.which("pyinstaller")
    if pyinstaller_path is None:
        raise RuntimeError("PyInstaller is not available in the current environment.")

    build_icon(logo_path, icon_path)

    output_exe = dist_dir / f"{APP_NAME}.exe"
    if output_exe.exists():
        try:
            output_exe.unlink()
        except PermissionError:
            dist_dir = tool_dir / f"dist_{datetime.now():%Y%m%d_%H%M%S}"

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--name",
        APP_NAME,
        "--icon",
        str(icon_path),
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(build_dir),
        "--specpath",
        str(spec_dir),
        "--add-data",
        f"{logo_path};assets",
        str(app_path),
    ]

    subprocess.run(command, cwd=repo_root, check=True)
    print(dist_dir / f"{APP_NAME}.exe")


if __name__ == "__main__":
    main()
