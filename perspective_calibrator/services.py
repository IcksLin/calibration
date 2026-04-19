from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

if __package__ in (None, ""):
    from core import CalibrationState, solve_global_matrices  # type: ignore
else:
    from .core import CalibrationState, solve_global_matrices


@dataclass
class ImageBundle:
    """!
    @brief 图像缓存包。

    @details
    将原始 RGB、灰度图和二值图统一缓存，
    供显示层与预览计算层重复复用，避免不必要的重复转换。
    """

    rgb: np.ndarray
    gray: np.ndarray
    binary: np.ndarray


class CalibrationService:
    """!
    @brief 功能层服务对象。

    @details
    负责图像载入、阈值更新、逆透视预览计算与预览图保存，
    对 UI 层屏蔽底层图像处理细节。
    """

    def __init__(self) -> None:
        """!
        @brief 初始化功能层缓存。
        """
        self.original_rgb: np.ndarray | None = None
        self.current_bundle: ImageBundle | None = None

    def load_image(self, path: str | Path, threshold: int) -> ImageBundle:
        """!
        @brief 从磁盘加载图像并建立缓存。
        @param path 图像路径。
        @param threshold 初始二值化阈值。
        @return 当前图像对应的缓存包。
        """
        image = Image.open(path).convert("RGB")
        rgb = np.asarray(image, dtype=np.uint8)
        self.original_rgb = rgb
        self.current_bundle = self._build_bundle(rgb, threshold)
        return self.current_bundle

    def update_threshold(self, threshold: int) -> ImageBundle:
        """!
        @brief 根据新的阈值重建灰度图与二值图缓存。
        @param threshold 二值化阈值。
        @return 更新后的缓存包。
        """
        if self.original_rgb is None:
            raise RuntimeError("No image loaded.")
        self.current_bundle = self._build_bundle(self.original_rgb, threshold)
        return self.current_bundle

    def get_display_image(self, state: CalibrationState) -> np.ndarray:
        """!
        @brief 获取左侧显示区当前应显示的图像。
        @param state 当前标定状态。
        @return 原图或二值辅助图。
        """
        if self.current_bundle is None:
            raise RuntimeError("No image loaded.")
        return (
            self.current_bundle.binary.copy()
            if state.binary_view_enabled
            else self.current_bundle.rgb.copy()
        )

    def warp_preview(
        self,
        state: CalibrationState,
    ) -> tuple[np.ndarray | None, list[tuple[float, float]]]:
        """!
        @brief 生成一次完整的全局逆透视预览。
        @param state 当前标定状态。
        @return 预览图数组与排序后的四点。
        """
        if self.current_bundle is None or not state.has_complete_selection:
            return None, []

        matrix, inverse, ordered, virtual_rect = solve_global_matrices(
            state.points,
            state,
            self.current_bundle.rgb.shape[0],
        )
        state.homography = matrix
        state.inverse_homography = inverse
        state.virtual_rectangle = virtual_rect

        source = self.get_display_image(state)
        dst_h, dst_w = source.shape[:2]
        warped = warp_perspective(
            source,
            inverse,
            dst_w,
            dst_h,
        )
        return warped, ordered

    @staticmethod
    def save_preview_image(image: Image.Image, path: str | Path) -> Path:
        """!
        @brief 保存逆透视预览图。
        @param image 待保存的 PIL 图像。
        @param path 输出路径。
        @return 实际保存路径。

        @details
        显式打开文件句柄并在保存后立即关闭，
        避免运行中长期占用文件影响复制或调试。
        """
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # Write through an explicit file handle so the OS handle is released
        # as soon as the save completes.
        with output_path.open("wb") as fh:
            image.save(fh, format="PNG")
        return output_path

    @staticmethod
    def _build_bundle(rgb: np.ndarray, threshold: int) -> ImageBundle:
        """!
        @brief 从原始 RGB 图像生成显示缓存。
        @param rgb 原始 RGB 图像数组。
        @param threshold 二值化阈值。
        @return 包含 RGB、灰度图和二值图的缓存包。
        """
        gray = (
            0.299 * rgb[:, :, 0]
            + 0.587 * rgb[:, :, 1]
            + 0.114 * rgb[:, :, 2]
        ).astype(np.uint8)
        binary_mask = gray >= np.uint8(np.clip(threshold, 0, 255))
        binary = np.where(binary_mask[..., None], 255, 0).astype(np.uint8)
        binary = np.repeat(binary[:, :, :1], 3, axis=2)
        return ImageBundle(rgb=rgb.copy(), gray=gray, binary=binary)


def warp_perspective(
    image: np.ndarray,
    inverse_matrix: np.ndarray,
    dst_w: int,
    dst_h: int,
) -> np.ndarray:
    """!
    @brief 对整幅图像执行逆透视映射。
    @param image 输入图像数组。
    @param inverse_matrix 逆透视矩阵。
    @param dst_w 输出图宽度。
    @param dst_h 输出图高度。
    @return 逆透视后的输出图像。

    @details
    使用双线性插值从源图采样，生成完整视野的鸟瞰预览图，
    而不是只映射四边形内部区域。
    """
    src_h, src_w = image.shape[:2]

    yy, xx = np.meshgrid(
        np.arange(dst_h, dtype=np.float64),
        np.arange(dst_w, dtype=np.float64),
        indexing="ij",
    )
    dst_points = np.stack([xx, yy, np.ones_like(xx)], axis=-1).reshape(-1, 3)
    src_points = dst_points @ inverse_matrix.T
    src_points[:, 0] /= src_points[:, 2]
    src_points[:, 1] /= src_points[:, 2]

    x = src_points[:, 0]
    y = src_points[:, 1]
    valid = (x >= 0) & (x <= src_w - 1) & (y >= 0) & (y <= src_h - 1)

    output = np.zeros((dst_h * dst_w, image.shape[2]), dtype=np.float64)
    if not np.any(valid):
        return output.reshape(dst_h, dst_w, image.shape[2]).astype(np.uint8)

    xv = x[valid]
    yv = y[valid]
    x0 = np.floor(xv).astype(np.int32)
    y0 = np.floor(yv).astype(np.int32)
    x1 = np.clip(x0 + 1, 0, src_w - 1)
    y1 = np.clip(y0 + 1, 0, src_h - 1)

    wx = xv - x0
    wy = yv - y0

    top_left = image[y0, x0].astype(np.float64)
    top_right = image[y0, x1].astype(np.float64)
    bottom_left = image[y1, x0].astype(np.float64)
    bottom_right = image[y1, x1].astype(np.float64)

    top = top_left * (1.0 - wx[:, None]) + top_right * wx[:, None]
    bottom = bottom_left * (1.0 - wx[:, None]) + bottom_right * wx[:, None]
    output[valid] = top * (1.0 - wy[:, None]) + bottom * wy[:, None]

    warped = output.reshape(dst_h, dst_w, image.shape[2])
    return np.clip(warped, 0, 255).astype(np.uint8)
