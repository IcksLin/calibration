from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Sequence

import json
import math

import numpy as np


Point = tuple[float, float]
POINT_ROLE_NAMES = ("左上", "右上", "右下", "左下")


@dataclass
class HoverPoint:
    """!
    @brief 鼠标悬停点状态。

    @details
    用于在显示层之间共享当前悬停像素坐标和可见性状态，
    便于同步绘制高亮标记与左侧坐标读数。
    """

    x: int = -1
    y: int = -1
    visible: bool = False


@dataclass
class VirtualRectangle:
    """!
    @brief 虚拟参考矩形。

    @details
    保存由用户四点和控制参数推导出的目标矩形几何信息，
    后续矩阵求解与辅助显示都依赖这一结构。
    """

    points: list[Point]
    width: float
    height: float


@dataclass
class CalibrationState:
    """!
    @brief 标定工具核心状态容器。

    @details
    统一保存用户输入参数、交互点位、悬停状态以及求解得到的矩阵和虚拟矩形，
    供 UI 层、缓冲层和计算层共享。
    """

    image_path: str = ""
    threshold: int = 128
    binary_view_enabled: bool = False
    rect_width_ratio: float = 4.0
    rect_height_ratio: float = 3.0
    virtual_bottom_margin: int = 0
    virtual_horizontal_offset: int = 0
    ground_width_scale: float = 1.0
    physical_ground_width_m: float = 0.45
    points: List[Point] = field(default_factory=list)
    hover: HoverPoint = field(default_factory=HoverPoint)
    homography: np.ndarray | None = None
    inverse_homography: np.ndarray | None = None
    virtual_rectangle: VirtualRectangle | None = None

    @property
    def aspect_ratio(self) -> float:
        """!
        @brief 获取当前矩形宽高比。
        @return 矩形宽高比，异常情况下回退为 1.0。
        """
        if self.rect_height_ratio <= 0:
            return 1.0
        return self.rect_width_ratio / self.rect_height_ratio

    @property
    def has_complete_selection(self) -> bool:
        """!
        @brief 判断是否已经完成四点选取。
        @return 选点数量恰好为 4 时返回 true。
        """
        return len(self.points) == 4

    def clear_points(self) -> None:
        """!
        @brief 清空当前选点和相关计算结果。
        """
        self.points.clear()
        self.homography = None
        self.inverse_homography = None
        self.virtual_rectangle = None

    def undo_last_point(self) -> None:
        """!
        @brief 撤销最后一个选点并清空关联求解结果。
        """
        if self.points:
            self.points.pop()
        self.homography = None
        self.inverse_homography = None
        self.virtual_rectangle = None

    def add_point(self, point: Point) -> None:
        """!
        @brief 追加一个选点。
        @param point 新增点坐标。

        @details
        当已有四个点时，会先清空旧点再从头开始新一轮标定。
        """
        if len(self.points) >= 4:
            self.points.clear()
        self.points.append(point)
        self.homography = None
        self.inverse_homography = None
        self.virtual_rectangle = None

    def to_dict(self) -> dict:
        """!
        @brief 序列化当前状态到字典。
        @return 可直接写入 JSON 的状态字典。
        """
        return {
            "image_path": self.image_path,
            "threshold": self.threshold,
            "binary_view_enabled": self.binary_view_enabled,
            "rect_width_ratio": self.rect_width_ratio,
            "rect_height_ratio": self.rect_height_ratio,
            "virtual_bottom_margin": self.virtual_bottom_margin,
            "virtual_horizontal_offset": self.virtual_horizontal_offset,
            "ground_width_scale": self.ground_width_scale,
            "physical_ground_width_m": self.physical_ground_width_m,
            "points": [[float(x), float(y)] for x, y in self.points],
        }

    def save(self, path: str | Path) -> None:
        """!
        @brief 将当前状态保存到磁盘。
        @param path 保存路径。
        """
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "CalibrationState":
        """!
        @brief 从会话文件恢复标定状态。
        @param path 会话文件路径。
        @return 恢复后的状态对象。
        """
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        state = cls()
        state.image_path = str(data.get("image_path", ""))
        state.threshold = int(data.get("threshold", 128))
        state.binary_view_enabled = bool(data.get("binary_view_enabled", False))
        state.rect_width_ratio = float(data.get("rect_width_ratio", 4.0))
        state.rect_height_ratio = float(data.get("rect_height_ratio", 3.0))
        state.virtual_bottom_margin = int(data.get("virtual_bottom_margin", 0))
        state.virtual_horizontal_offset = int(data.get("virtual_horizontal_offset", 0))
        state.ground_width_scale = float(data.get("ground_width_scale", 1.0))
        state.physical_ground_width_m = float(data.get("physical_ground_width_m", 0.45))

        if "target_width" in data and "target_height" in data:
            state.rect_width_ratio = float(data["target_width"])
            state.rect_height_ratio = float(max(float(data["target_height"]), 1.0))

        state.points = [
            (float(pair[0]), float(pair[1])) for pair in data.get("points", [])
        ]
        return state


def sort_quad_points(points: Sequence[Point]) -> list[Point]:
    """!
    @brief 对四边形点位进行标准排序。
    @param points 原始四点集合。
    @return 按左上、右上、右下、左下排序后的点列表。
    """
    if len(points) != 4:
        raise ValueError("Exactly four points are required.")

    pts = np.asarray(points, dtype=np.float64)
    y_sorted = pts[np.argsort(pts[:, 1])]
    top = y_sorted[:2][np.argsort(y_sorted[:2, 0])]
    bottom = y_sorted[2:][np.argsort(y_sorted[2:, 0])]

    tl, tr = top
    bl, br = bottom
    ordered = np.array([tl, tr, br, bl], dtype=np.float64)
    return [(float(x), float(y)) for x, y in ordered]


def compute_homography(src_points: Sequence[Point], dst_points: Sequence[Point]) -> np.ndarray:
    """!
    @brief 根据四组对应点求解单应矩阵。
    @param src_points 源图四点。
    @param dst_points 目标平面四点。
    @return 3x3 单应矩阵。
    """
    if len(src_points) != 4 or len(dst_points) != 4:
        raise ValueError("Homography requires four source and four destination points.")

    src = np.asarray(src_points, dtype=np.float64)
    dst = np.asarray(dst_points, dtype=np.float64)

    a_rows = []
    b_rows = []
    for (x, y), (u, v) in zip(src, dst):
        a_rows.append([x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y])
        a_rows.append([0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y])
        b_rows.append(u)
        b_rows.append(v)

    a = np.asarray(a_rows, dtype=np.float64)
    b = np.asarray(b_rows, dtype=np.float64)
    solution = np.linalg.solve(a, b)

    return np.array(
        [
            [solution[0], solution[1], solution[2]],
            [solution[3], solution[4], solution[5]],
            [solution[6], solution[7], 1.0],
        ],
        dtype=np.float64,
    )


def build_virtual_rectangle(
    ordered_points: Sequence[Point],
    state: CalibrationState,
    image_height: int,
) -> VirtualRectangle:
    """!
    @brief 构造虚拟目标矩形。
    @param ordered_points 已标准排序的四点。
    @param state 当前标定状态。
    @param image_height 输入图像高度。
    @return 用于逆透视求解的虚拟矩形。

    @details
    宽度参考近端地面边，位置受底边距底部与水平偏移控制，
    高度由当前长宽比推导得到。
    """
    tl, tr, br, bl = ordered_points

    bottom_left = np.asarray(bl, dtype=np.float64)
    bottom_right = np.asarray(br, dtype=np.float64)
    bottom_vector = bottom_right - bottom_left

    width = abs(float(bottom_vector[0]))
    if width < 1.0:
        width = float(np.linalg.norm(bottom_vector))
    width *= max(state.ground_width_scale, 0.05)
    width = max(width, 1.0)

    image_bottom_y = max(float(image_height - 1), 0.0)
    bottom_y = image_bottom_y - float(max(state.virtual_bottom_margin, 0))
    bottom_y = min(max(bottom_y, 0.0), image_bottom_y)
    top_y_min = min(tl[1], tr[1])
    auto_height = max(bottom_y - top_y_min, 1.0)

    height = max(width / max(state.aspect_ratio, 1e-6), 1.0)

    center_x = (float(bl[0]) + float(br[0])) * 0.5 + float(state.virtual_horizontal_offset)
    half_width = width * 0.5
    dest_left_x = center_x - half_width
    dest_right_x = center_x + half_width

    dest_tl = (dest_left_x, float(bottom_y - height))
    dest_tr = (dest_right_x, float(bottom_y - height))
    dest_br = (dest_right_x, float(bottom_y))
    dest_bl = (dest_left_x, float(bottom_y))

    return VirtualRectangle(
        points=[dest_tl, dest_tr, dest_br, dest_bl],
        width=width,
        height=height,
    )


def solve_global_matrices(
    points: Sequence[Point],
    state: CalibrationState,
    image_height: int,
) -> tuple[np.ndarray, np.ndarray, list[Point], VirtualRectangle]:
    """!
    @brief 求解正向矩阵、逆矩阵与辅助几何结果。
    @param points 用户原始四点。
    @param state 当前标定状态。
    @param image_height 输入图像高度。
    @return 正向矩阵、逆矩阵、排序后点位和虚拟矩形。
    """
    ordered = sort_quad_points(points)
    virtual_rect = build_virtual_rectangle(ordered, state, image_height)
    m = compute_homography(ordered, virtual_rect.points)
    m_reverse = np.linalg.inv(m)
    return m, m_reverse, ordered, virtual_rect


def ordered_point_rows(points: Sequence[Point]) -> list[tuple[str, Point]]:
    """!
    @brief 为左侧点位面板生成带角色名的点列表。
    @param points 用户原始四点。
    @return 形如“点名 + 坐标”的列表。
    """
    ordered = sort_quad_points(points)
    return list(zip(POINT_ROLE_NAMES, ordered))


def calculate_m2pix(virtual_rect: VirtualRectangle | None, physical_ground_width_m: float) -> float | None:
    """!
    @brief 由虚拟矩形宽度计算工程参数 M2PIX。
    @param virtual_rect 虚拟矩形。
    @param physical_ground_width_m 底面边实际物理宽度，单位米。
    @return 计算得到的像素每米，无法计算时返回 None。
    """
    if virtual_rect is None or physical_ground_width_m <= 0:
        return None
    return virtual_rect.width / physical_ground_width_m


def format_cpp_matrix(name: str, matrix: np.ndarray) -> str:
    """!
    @brief 将矩阵格式化为工程兼容的 OpenCV C++ 初始化代码。
    @param name 矩阵变量名。
    @param matrix 3x3 矩阵。
    @return 可直接粘贴到工程中的 C++ 文本。
    """
    rows = []
    matrix = matrix.astype(np.float64)
    for row_idx in range(3):
        row = ",".join(_format_float(value) for value in matrix[row_idx])
        if row_idx < 2:
            row += ","
        rows.append(row)
    body = "\n".join(rows)
    return f"cv::Mat {name} = (cv::Mat_<float>(3, 3) <<\n{body});"


def format_output_block(
    m: np.ndarray,
    m_reverse: np.ndarray,
    virtual_rect: VirtualRectangle | None,
    physical_ground_width_m: float,
) -> str:
    """!
    @brief 生成完整的工程输出文本块。
    @param m 正向透视矩阵。
    @param m_reverse 逆透视矩阵。
    @param virtual_rect 虚拟矩形。
    @param physical_ground_width_m 底面边实际物理宽度。
    @return 包含矩阵与 M2PIX 的输出文本。
    """
    blocks = [
        format_cpp_matrix("M", m),
        format_cpp_matrix("M_Reverse", m_reverse),
    ]
    m2pix = calculate_m2pix(virtual_rect, physical_ground_width_m)
    if m2pix is not None:
        blocks.append(
            "\n".join(
                [
                    "// Auxiliary calibration values",
                    f"// ground_width_m = {_format_float(physical_ground_width_m)}",
                    f"#define M2PIX {_format_float(m2pix)} // 米转像素",
                ]
            )
        )
    return "\n\n".join(blocks)


def _format_float(value: float) -> str:
    """!
    @brief 统一格式化浮点数输出。
    @param value 原始浮点值。
    @return 适合写入 C++ 代码的紧凑字符串。
    """
    if math.isclose(value, 0.0, abs_tol=1e-12):
        value = 0.0
    return f"{value:.16g}"
