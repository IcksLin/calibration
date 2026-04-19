from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

if __package__ in (None, ""):
    CURRENT_DIR = Path(__file__).resolve().parent
    if str(CURRENT_DIR) not in sys.path:
        sys.path.insert(0, str(CURRENT_DIR))
    from core import (  # type: ignore
        CalibrationState,
        calculate_m2pix,
        format_output_block,
        ordered_point_rows,
        sort_quad_points,
    )
    from services import CalibrationService  # type: ignore
else:
    from .core import (
        CalibrationState,
        calculate_m2pix,
        format_output_block,
        ordered_point_rows,
        sort_quad_points,
    )
    from .services import CalibrationService


PANEL_BG = "#f3ede6"
CARD_BG = "#fffaf5"
TEXT_DARK = "#2d241d"
TEXT_SOFT = "#6a5849"
ACCENT = "#b43b28"
ACCENT_SOFT = "#e8c0b5"
CANVAS_BG = "#ece3d7"
CANVAS_BORDER = "#baa898"
POINT_STYLES = (
    {"label": "左上", "color": "#e25555"},
    {"label": "右上", "color": "#4c7df0"},
    {"label": "右下", "color": "#2aa36b"},
    {"label": "左下", "color": "#f0a43a"},
)


def resolve_resource_path(*parts: str) -> Path:
    """!
    @brief 在源码模式和打包模式下解析资源路径。
    @param parts 资源路径片段。
    @return 命中的资源路径，若未命中则返回首个候选路径。
    """
    tool_dir = Path(__file__).resolve().parent
    candidates: list[Path] = []

    if getattr(sys, "frozen", False):
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        candidates.extend(
            [
                bundle_root.joinpath(*parts),
                bundle_root / "assets" / parts[-1],
                Path(sys.executable).resolve().parent.joinpath(*parts),
                Path(sys.executable).resolve().parent / "assets" / parts[-1],
            ]
        )
    else:
        candidates.extend(
            [
                tool_dir.joinpath(*parts),
                tool_dir / "assets" / parts[-1],
                tool_dir.parent / "LOGO" / parts[-1],
            ]
        )

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


class ImageViewport(ttk.Frame):
    """!
    @brief 图像显示视口。

    @details
    封装画布缩放、坐标换算和底图绘制，
    让原图区与预览区复用同一套显示逻辑。
    """

    def __init__(self, master: tk.Misc, title: str, redraw_callback) -> None:
        """!
        @brief 初始化图像视口。
        @param master 父控件。
        @param title 视口标题。
        @param redraw_callback 画布尺寸变化后的重绘回调。
        """
        super().__init__(master)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self.title_var = tk.StringVar(value=title)
        ttk.Label(self, textvariable=self.title_var, style="PanelTitle.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
            pady=(0, 6),
        )

        self.canvas = tk.Canvas(
            self,
            background=CANVAS_BG,
            highlightthickness=1,
            highlightbackground=CANVAS_BORDER,
            cursor="crosshair",
        )
        self.canvas.grid(row=1, column=0, sticky="nsew")

        self.redraw_callback = redraw_callback
        self.base_image: Image.Image | None = None
        self.photo: ImageTk.PhotoImage | None = None
        self.scale = 1.0
        self.image_size = (0, 0)
        self.display_size = (0.0, 0.0)
        self.image_offset = (0.0, 0.0)
        self._resize_job: str | None = None

        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def set_image(self, image: Image.Image | None) -> None:
        """!
        @brief 设置当前视口底图。
        @param image 待显示图像，为 None 时清空视口。
        """
        self.base_image = image
        self._draw_base()

    def clear_overlay(self) -> None:
        """!
        @brief 清除视口上的叠加绘制层。
        """
        self.canvas.delete("overlay")

    def canvas_to_image(self, event_x: int, event_y: int) -> tuple[int, int] | None:
        """!
        @brief 将画布坐标换算为原图坐标。
        @param event_x 画布 x 坐标。
        @param event_y 画布 y 坐标。
        @return 原图像素坐标，若超出图像区域则返回 None。
        """
        if self.image_size == (0, 0):
            return None
        offset_x, offset_y = self.image_offset
        width, height = self.display_size
        local_x = event_x - offset_x
        local_y = event_y - offset_y
        if local_x < 0 or local_y < 0 or local_x >= width or local_y >= height:
            return None
        return int(local_x / self.scale), int(local_y / self.scale)

    def image_to_canvas_point(self, x: float, y: float) -> tuple[float, float]:
        """!
        @brief 将原图坐标换算为画布坐标。
        @param x 原图 x 坐标。
        @param y 原图 y 坐标。
        @return 画布坐标。
        """
        offset_x, offset_y = self.image_offset
        return offset_x + x * self.scale, offset_y + y * self.scale

    def _on_canvas_configure(self, _event: tk.Event) -> None:
        """!
        @brief 处理画布尺寸变化事件。
        @param _event Tk 事件对象。
        """
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(60, self.redraw_callback)

    def _draw_base(self) -> None:
        """!
        @brief 按当前画布大小重绘底图。
        """
        self.canvas.delete("all")
        if self.base_image is None:
            self.photo = None
            self.image_size = (0, 0)
            self.display_size = (0.0, 0.0)
            return

        self.canvas.update_idletasks()
        canvas_w = max(int(self.canvas.winfo_width()), 1)
        canvas_h = max(int(self.canvas.winfo_height()), 1)

        width, height = self.base_image.size
        self.image_size = (width, height)
        scale = min(canvas_w / max(width, 1), canvas_h / max(height, 1), 4.0)
        scale = max(scale, 0.05)
        scaled_w = max(int(round(width * scale)), 1)
        scaled_h = max(int(round(height * scale)), 1)

        if scale != 1.0:
            render = self.base_image.resize((scaled_w, scaled_h), Image.Resampling.NEAREST)
        else:
            render = self.base_image

        self.photo = ImageTk.PhotoImage(render)
        offset_x = (canvas_w - scaled_w) / 2.0
        offset_y = (canvas_h - scaled_h) / 2.0
        self.canvas.create_image(offset_x, offset_y, anchor="nw", image=self.photo, tags=("base",))

        self.scale = scale
        self.display_size = (float(scaled_w), float(scaled_h))
        self.image_offset = (offset_x, offset_y)
        self.canvas.tag_raise("overlay")


class ScrollablePanel(ttk.Frame):
    """!
    @brief 可滚动参数面板。

    @details
    负责承载左侧所有参数控件，
    在控件数量增加时仍保持界面可维护和可访问。
    """

    def __init__(self, master: tk.Misc) -> None:
        """!
        @brief 初始化可滚动面板。
        @param master 父控件。
        """
        super().__init__(master, style="Card.TFrame")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            self,
            background=CARD_BG,
            highlightthickness=0,
            bd=0,
        )
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.content = ttk.Frame(self.canvas, style="Card.TFrame")

        self.content_window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")

        self.content.bind("<Configure>", self._on_content_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_content_configure(self, _event: tk.Event) -> None:
        """!
        @brief 根据内容大小刷新滚动区域。
        @param _event Tk 事件对象。
        """
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        """!
        @brief 让内部内容宽度跟随画布宽度。
        @param event Tk 事件对象。
        """
        self.canvas.itemconfigure(self.content_window, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> None:
        """!
        @brief 处理鼠标滚轮滚动。
        @param event Tk 事件对象。
        """
        if self.winfo_ismapped():
            self.canvas.yview_scroll(int(-event.delta / 120), "units")


class CalibrationApp:
    """!
    @brief 标定工具主控制器。

    @details
    统一协调显示层、缓冲层、功能层与核心计算层，
    是整个工具的运行入口与状态调度中心。
    """

    def __init__(self, root: tk.Tk, image_path: str | None = None) -> None:
        """!
        @brief 初始化应用程序。
        @param root Tk 根窗口。
        @param image_path 启动时可选的预载入图像路径。
        """
        self.root = root
        self.root.title("Perspective Matrix Calibrator")
        self.root.configure(bg=PANEL_BG)
        self.root.geometry("1680x960")
        self.root.minsize(1460, 860)
        self._window_icon: ImageTk.PhotoImage | None = None

        self.state = CalibrationState()
        self.service = CalibrationService()
        self.ordered_points: list[tuple[float, float]] = []
        self.current_preview: Image.Image | None = None
        self.point_value_vars: list[tk.StringVar] = []
        self._viewport_redraw_job: str | None = None
        self._syncing_ratio_value = False
        self._syncing_threshold_value = False
        self._syncing_bottom_margin_value = False
        self._syncing_horizontal_offset_value = False
        self._syncing_width_scale_value = False
        self._buffer_flush_job: str | None = None
        self._buffer_frame_interval_ms = 40
        self._kernel_busy = False
        self._kernel_ready = True
        self._pending_kernel_updates: dict[str, object] = {}
        self._tool_dir = Path(__file__).resolve().parent
        # Packaged onefile apps should write outputs next to the executable
        # instead of the temporary extraction directory.
        if getattr(sys, "frozen", False):
            self._runtime_root = Path(sys.executable).resolve().parent
        else:
            self._runtime_root = self._tool_dir / "runtime"
        self._picture_dir = self._runtime_root / "Picture"
        self._log_path = self._runtime_root / "logs" / "calibrator.log"
        self._log_max_bytes = 128 * 1024
        self.status_var = tk.StringVar(value="")

        self._configure_styles()
        self._configure_window_icon()
        self._build_layout()
        self._bind_shortcuts()
        self.root.report_callback_exception = self._report_callback_exception
        self._log_event("应用启动")

        if image_path:
            self.open_image(image_path)

    def _configure_window_icon(self) -> None:
        """!
        @brief 加载窗口图标。

        @details
        兼容源码运行与单文件打包运行，
        确保两种模式都能使用同一份 Logo 资源。
        """
        logo_path = resolve_resource_path("assets", "anan.jpg")
        if not logo_path.exists():
            return
        try:
            logo_image = Image.open(logo_path).convert("RGBA")
            logo_image.thumbnail((128, 128), Image.Resampling.LANCZOS)
            self._window_icon = ImageTk.PhotoImage(logo_image)
            self.root.iconphoto(True, self._window_icon)
        except Exception as exc:
            self._log_event(f"窗口图标加载失败: {exc}")

    def _configure_styles(self) -> None:
        """!
        @brief 配置全局 ttk 样式。
        """
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("App.TFrame", background=PANEL_BG)
        style.configure("Card.TFrame", background=CARD_BG)
        style.configure(
            "PanelTitle.TLabel",
            background=PANEL_BG,
            foreground=TEXT_DARK,
            font=("Microsoft YaHei UI", 12, "bold"),
        )
        style.configure(
            "CardTitle.TLabel",
            background=CARD_BG,
            foreground=TEXT_DARK,
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        style.configure(
            "Info.TLabel",
            background=CARD_BG,
            foreground=TEXT_DARK,
            font=("Consolas", 10),
        )
        style.configure(
            "Hint.TLabel",
            background=CARD_BG,
            foreground=TEXT_SOFT,
            font=("Microsoft YaHei UI", 9),
        )
        style.configure("TButton", font=("Microsoft YaHei UI", 10))
        style.configure(
            "TCheckbutton",
            background=CARD_BG,
            foreground=TEXT_DARK,
            font=("Microsoft YaHei UI", 10),
        )

    def _build_layout(self) -> None:
        """!
        @brief 搭建主界面布局。
        """
        container = ttk.Frame(self.root, style="App.TFrame", padding=14)
        container.pack(fill="both", expand=True)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(0, weight=1)

        self.control_panel = ScrollablePanel(container)
        self.control_panel.grid(row=0, column=0, sticky="nsw", padx=(0, 14))
        self.control_panel.configure(width=360)

        image_panel = ttk.Frame(container, style="App.TFrame")
        image_panel.grid(row=0, column=1, sticky="nsew")
        image_panel.columnconfigure(0, weight=1)
        image_panel.columnconfigure(1, weight=1)
        image_panel.rowconfigure(0, weight=1)

        self.input_view = ImageViewport(image_panel, "原图 / 二值辅助", self.schedule_viewport_refresh)
        self.input_view.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.preview_view = ImageViewport(image_panel, "全局逆透视预览", self.schedule_viewport_refresh)
        self.preview_view.grid(row=0, column=1, sticky="nsew")

        self._build_controls()

    def _build_controls(self) -> None:
        """!
        @brief 构建左侧控制区控件。

        @details
        包含图像导入、参数调节、点位信息、矩阵输出和功能按钮。
        """
        panel = self.control_panel.content

        ttk.Label(panel, text="标定控制台", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            panel,
            text="四点用于标定整张图的全局逆透视矩阵。紫色虚线框表示当前参与计算的虚拟矩形。",
            style="Hint.TLabel",
            wraplength=300,
            justify="left",
        ).pack(anchor="w", pady=(4, 12))

        row = ttk.Frame(panel, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Button(row, text="打开图像", command=self.choose_image).pack(side="left")
        ttk.Button(row, text="载入配置", command=self.load_session).pack(side="left", padx=6)
        ttk.Button(row, text="保存配置", command=self.save_session).pack(side="left")

        ttk.Separator(panel, orient="horizontal").pack(fill="x", pady=12)

        ttk.Label(panel, text="当前像素", style="CardTitle.TLabel").pack(anchor="w")
        self.hover_var = tk.StringVar(value="x: -, y: -")
        ttk.Label(panel, textvariable=self.hover_var, style="Info.TLabel").pack(anchor="w", pady=(4, 10))

        ttk.Label(panel, text="排序后点位", style="CardTitle.TLabel").pack(anchor="w")
        rows_frame = ttk.Frame(panel, style="Card.TFrame")
        rows_frame.pack(fill="x", pady=(4, 10))
        for style in POINT_STYLES:
            item = ttk.Frame(rows_frame, style="Card.TFrame")
            item.pack(fill="x", pady=2)
            swatch = tk.Canvas(item, width=16, height=16, bg=CARD_BG, highlightthickness=0, bd=0)
            swatch.pack(side="left")
            swatch.create_rectangle(1, 1, 15, 15, fill=style["color"], outline="")
            value_var = tk.StringVar(value=f'{style["label"]}: -')
            ttk.Label(item, textvariable=value_var, style="Info.TLabel").pack(side="left", padx=(6, 0))
            self.point_value_vars.append(value_var)

        ttk.Label(panel, text="点击顺序", style="CardTitle.TLabel").pack(anchor="w")
        self.raw_points_var = tk.StringVar(value="尚未选点")
        ttk.Label(
            panel,
            textvariable=self.raw_points_var,
            style="Info.TLabel",
            justify="left",
            wraplength=300,
        ).pack(anchor="w", pady=(4, 10))

        ttk.Label(panel, text="矩形约束", style="CardTitle.TLabel").pack(anchor="w")
        ratio_frame = ttk.Frame(panel, style="Card.TFrame")
        ratio_frame.pack(fill="x", pady=(4, 10))

        self.ratio_var = tk.DoubleVar(value=self.state.rect_height_ratio / max(self.state.rect_width_ratio, 1e-6))
        self.ratio_entry_var = tk.StringVar(value=f"{self.ratio_var.get():.2f}")
        ratio_row = ttk.Frame(ratio_frame, style="Card.TFrame")
        ratio_row.pack(fill="x")
        self.ratio_scale = tk.Scale(
            ratio_row,
            from_=0.02,
            to=5.0,
            orient="horizontal",
            resolution=0.01,
            showvalue=False,
            variable=self.ratio_var,
            command=self.on_ratio_slider_changed,
            background=CARD_BG,
            foreground=TEXT_DARK,
            highlightthickness=0,
            troughcolor=ACCENT_SOFT,
            activebackground=ACCENT,
            length=230,
        )
        self.ratio_scale.pack(side="left", fill="x", expand=True)
        self.ratio_scale.bind("<ButtonRelease-1>", lambda _event: self.on_ratio_slider_released())
        self.ratio_entry = ttk.Entry(ratio_row, textvariable=self.ratio_entry_var, width=8)
        self.ratio_entry.pack(side="left", padx=(8, 0))
        self.ratio_entry.bind("<Return>", lambda _event: self.on_ratio_entry_changed())
        self.ratio_entry.bind("<FocusOut>", lambda _event: self.on_ratio_entry_changed())

        self.aspect_var = tk.StringVar()
        self.virtual_rect_var = tk.StringVar(value="虚拟矩形: -")
        ttk.Label(panel, textvariable=self.aspect_var, style="Info.TLabel").pack(anchor="w")
        ttk.Label(panel, textvariable=self.virtual_rect_var, style="Info.TLabel").pack(anchor="w")

        self.binary_var = tk.BooleanVar(value=self.state.binary_view_enabled)
        ttk.Checkbutton(
            panel,
            text="标点时显示二值图",
            variable=self.binary_var,
            command=self.on_binary_toggle,
        ).pack(anchor="w", pady=(10, 6))

        ttk.Label(panel, text="二值化阈值", style="CardTitle.TLabel").pack(anchor="w")
        self.threshold_var = tk.IntVar(value=self.state.threshold)
        self.threshold_entry_var = tk.StringVar(value=str(self.state.threshold))
        threshold_row = ttk.Frame(panel, style="Card.TFrame")
        threshold_row.pack(fill="x")
        self.threshold_scale = tk.Scale(
            threshold_row,
            from_=0,
            to=255,
            orient="horizontal",
            resolution=1,
            showvalue=False,
            variable=self.threshold_var,
            command=self.on_threshold_slider_changed,
            background=CARD_BG,
            foreground=TEXT_DARK,
            highlightthickness=0,
            troughcolor=ACCENT_SOFT,
            activebackground=ACCENT,
            length=230,
        )
        self.threshold_scale.pack(side="left", fill="x", expand=True)
        self.threshold_scale.bind("<ButtonRelease-1>", lambda _event: self.on_threshold_slider_released())
        self.threshold_entry = ttk.Entry(threshold_row, textvariable=self.threshold_entry_var, width=8)
        self.threshold_entry.pack(side="left", padx=(8, 0))
        self.threshold_entry.bind("<Return>", lambda _event: self.on_threshold_entry_changed())
        self.threshold_entry.bind("<FocusOut>", lambda _event: self.on_threshold_entry_changed())

        ttk.Label(panel, text="虚拟底边距图像底部", style="CardTitle.TLabel").pack(anchor="w", pady=(10, 0))
        self.bottom_margin_var = tk.IntVar(value=self.state.virtual_bottom_margin)
        self.bottom_margin_entry_var = tk.StringVar(value=str(self.state.virtual_bottom_margin))
        bottom_row = ttk.Frame(panel, style="Card.TFrame")
        bottom_row.pack(fill="x")
        self.bottom_margin_scale = tk.Scale(
            bottom_row,
            from_=0,
            to=120,
            orient="horizontal",
            resolution=1,
            showvalue=False,
            variable=self.bottom_margin_var,
            command=self.on_bottom_margin_slider_changed,
            background=CARD_BG,
            foreground=TEXT_DARK,
            highlightthickness=0,
            troughcolor=ACCENT_SOFT,
            activebackground=ACCENT,
            length=230,
        )
        self.bottom_margin_scale.pack(side="left", fill="x", expand=True)
        self.bottom_margin_scale.bind("<ButtonRelease-1>", lambda _event: self.on_bottom_margin_slider_released())
        self.bottom_margin_entry = ttk.Entry(bottom_row, textvariable=self.bottom_margin_entry_var, width=8)
        self.bottom_margin_entry.pack(side="left", padx=(8, 0))
        self.bottom_margin_entry.bind("<Return>", lambda _event: self.on_bottom_margin_entry_changed())
        self.bottom_margin_entry.bind("<FocusOut>", lambda _event: self.on_bottom_margin_entry_changed())

        ttk.Label(panel, text="虚拟矩形水平偏移", style="CardTitle.TLabel").pack(anchor="w", pady=(10, 0))
        self.horizontal_offset_var = tk.IntVar(value=self.state.virtual_horizontal_offset)
        self.horizontal_offset_entry_var = tk.StringVar(value=str(self.state.virtual_horizontal_offset))
        horizontal_row = ttk.Frame(panel, style="Card.TFrame")
        horizontal_row.pack(fill="x")
        self.horizontal_offset_scale = tk.Scale(
            horizontal_row,
            from_=-120,
            to=120,
            orient="horizontal",
            resolution=1,
            showvalue=False,
            variable=self.horizontal_offset_var,
            command=self.on_horizontal_offset_slider_changed,
            background=CARD_BG,
            foreground=TEXT_DARK,
            highlightthickness=0,
            troughcolor=ACCENT_SOFT,
            activebackground=ACCENT,
            length=230,
        )
        self.horizontal_offset_scale.pack(side="left", fill="x", expand=True)
        self.horizontal_offset_scale.bind("<ButtonRelease-1>", lambda _event: self.on_horizontal_offset_slider_released())
        self.horizontal_offset_entry = ttk.Entry(horizontal_row, textvariable=self.horizontal_offset_entry_var, width=8)
        self.horizontal_offset_entry.pack(side="left", padx=(8, 0))
        self.horizontal_offset_entry.bind("<Return>", lambda _event: self.on_horizontal_offset_entry_changed())
        self.horizontal_offset_entry.bind("<FocusOut>", lambda _event: self.on_horizontal_offset_entry_changed())

        ttk.Label(panel, text="底面边长度缩放", style="CardTitle.TLabel").pack(anchor="w", pady=(10, 0))
        self.width_scale_var = tk.DoubleVar(value=self.state.ground_width_scale)
        self.width_scale_entry_var = tk.StringVar(value=f"{self.state.ground_width_scale:.2f}")
        width_scale_row = ttk.Frame(panel, style="Card.TFrame")
        width_scale_row.pack(fill="x")
        self.width_scale_scale = tk.Scale(
            width_scale_row,
            from_=0.5,
            to=2.0,
            orient="horizontal",
            resolution=0.01,
            showvalue=False,
            variable=self.width_scale_var,
            command=self.on_width_scale_slider_changed,
            background=CARD_BG,
            foreground=TEXT_DARK,
            highlightthickness=0,
            troughcolor=ACCENT_SOFT,
            activebackground=ACCENT,
            length=230,
        )
        self.width_scale_scale.pack(side="left", fill="x", expand=True)
        self.width_scale_scale.bind("<ButtonRelease-1>", lambda _event: self.on_width_scale_slider_released())
        self.width_scale_entry = ttk.Entry(width_scale_row, textvariable=self.width_scale_entry_var, width=8)
        self.width_scale_entry.pack(side="left", padx=(8, 0))
        self.width_scale_entry.bind("<Return>", lambda _event: self.on_width_scale_entry_changed())
        self.width_scale_entry.bind("<FocusOut>", lambda _event: self.on_width_scale_entry_changed())

        ttk.Label(panel, text="底边实际物理距离(m)", style="CardTitle.TLabel").pack(anchor="w", pady=(10, 0))
        self.physical_width_var = tk.StringVar(value=f"{self.state.physical_ground_width_m:.3f}")
        self.physical_width_entry = ttk.Entry(panel, textvariable=self.physical_width_var, width=18)
        self.physical_width_entry.pack(anchor="w", pady=(4, 0))
        self.physical_width_entry.bind("<Return>", lambda _event: self.on_physical_width_changed())
        self.physical_width_entry.bind("<FocusOut>", lambda _event: self.on_physical_width_changed())

        self.m2pix_var = tk.StringVar(value="M2PIX: -")
        ttk.Label(panel, textvariable=self.m2pix_var, style="Info.TLabel").pack(anchor="w", pady=(4, 0))

        action_row = ttk.Frame(panel, style="Card.TFrame")
        action_row.pack(fill="x", pady=(12, 10))
        ttk.Button(action_row, text="撤销一点", command=self.undo_point).pack(side="left")
        ttk.Button(action_row, text="清空四点", command=self.clear_points).pack(side="left")

        ttk.Label(
            panel,
            text="快捷键: Ctrl+Z 撤销, Esc 清空, Ctrl+S 保存配置, Ctrl+O 打开图像",
            style="Hint.TLabel",
            wraplength=300,
            justify="left",
        ).pack(anchor="w")

        ttk.Separator(panel, orient="horizontal").pack(fill="x", pady=12)

        ttk.Label(panel, text="工程矩阵输出", style="CardTitle.TLabel").pack(anchor="w")
        self.matrix_text = tk.Text(
            panel,
            width=36,
            height=20,
            wrap="word",
            font=("Consolas", 10),
            bg="#251f1b",
            fg="#f7efe7",
            insertbackground="#ffffff",
        )
        self.matrix_text.pack(fill="both", expand=True, pady=(6, 8))

        bottom_row = ttk.Frame(panel, style="Card.TFrame")
        bottom_row.pack(fill="x", pady=(0, 8))
        ttk.Button(bottom_row, text="复制输出", command=self.copy_matrix).pack(side="left")
        ttk.Button(bottom_row, text="保存预览图", command=self.request_save_preview).pack(side="left", padx=(8, 0))

        self.input_view.canvas.bind("<Motion>", self.on_mouse_move)
        self.input_view.canvas.bind("<Leave>", self.on_mouse_leave)
        self.input_view.canvas.bind("<Button-1>", self.on_canvas_click)

        self._update_ratio_info()

    def _bind_shortcuts(self) -> None:
        """!
        @brief 绑定常用键盘快捷键。
        """
        self.root.bind("<Control-o>", lambda _event: self.choose_image())
        self.root.bind("<Control-s>", lambda _event: self.save_session())
        self.root.bind("<Control-z>", lambda _event: self.undo_point())
        self.root.bind("<Escape>", lambda _event: self.clear_points())

    def choose_image(self) -> None:
        """!
        @brief 打开文件选择框并载入图像。
        """
        path = filedialog.askopenfilename(
            title="选择标定图像",
            filetypes=[("Image Files", "*.png *.jpg *.jpeg *.bmp"), ("All Files", "*.*")],
        )
        if path:
            self.open_image(path)

    def open_image(self, path: str) -> None:
        """!
        @brief 打开指定图像并重置标定现场。
        @param path 图像路径。
        """
        try:
            if self._buffer_flush_job is not None:
                self.root.after_cancel(self._buffer_flush_job)
                self._buffer_flush_job = None
            self._pending_kernel_updates.clear()
            self.state.image_path = path
            self.state.clear_points()
            self.ordered_points = []
            self.current_preview = None
            self.service.load_image(path, self.state.threshold)
            self._sync_image_controls()
            self._update_output_text()
            self.refresh_all()
            self._set_status(f"已载入: {Path(path).name}", log=True)
        except Exception as exc:
            self._log_event(f"打开失败: {exc}")
            messagebox.showerror("打开失败", str(exc))

    def save_session(self) -> None:
        """!
        @brief 保存当前标定会话。
        """
        path = filedialog.asksaveasfilename(
            title="保存标定配置",
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json")],
        )
        if not path:
            return
        try:
            self.state.save(path)
            self._set_status(f"配置已保存: {Path(path).name}", log=True)
        except Exception as exc:
            self._log_event(f"保存失败: {exc}")
            messagebox.showerror("保存失败", str(exc))

    def load_session(self) -> None:
        """!
        @brief 载入历史标定会话。
        """
        path = filedialog.askopenfilename(
            title="载入标定配置",
            filetypes=[("JSON Files", "*.json")],
        )
        if not path:
            return
        try:
            if self._buffer_flush_job is not None:
                self.root.after_cancel(self._buffer_flush_job)
                self._buffer_flush_job = None
            self._pending_kernel_updates.clear()
            self.state = CalibrationState.from_file(path)
            self.threshold_var.set(self.state.threshold)
            self.threshold_entry_var.set(str(self.state.threshold))
            self.binary_var.set(self.state.binary_view_enabled)
            self._set_ratio_value(
                self.state.rect_height_ratio / max(self.state.rect_width_ratio, 1e-6),
                recompute=False,
            )
            self.bottom_margin_var.set(self.state.virtual_bottom_margin)
            self.bottom_margin_entry_var.set(str(self.state.virtual_bottom_margin))
            self.horizontal_offset_var.set(self.state.virtual_horizontal_offset)
            self.horizontal_offset_entry_var.set(str(self.state.virtual_horizontal_offset))
            self.width_scale_var.set(self.state.ground_width_scale)
            self.width_scale_entry_var.set(f"{self.state.ground_width_scale:.2f}")
            self.physical_width_var.set(f"{self.state.physical_ground_width_m:.3f}")
            self._update_ratio_info()

            if self.state.image_path:
                self.service.load_image(self.state.image_path, self.state.threshold)
                self._sync_image_controls()
            self.compute_preview(silent=True)
            self.refresh_all()
            self._set_status(f"配置已载入: {Path(path).name}", log=True)
        except Exception as exc:
            self._log_event(f"载入失败: {exc}")
            messagebox.showerror("载入失败", str(exc))

    def on_ratio_slider_changed(self, value: str) -> None:
        """!
        @brief 处理长宽比滑条拖动。
        @param value 滑条当前值。
        """
        if self._syncing_ratio_value:
            return
        value = self._clamp_float(float(value), 0.02, 5.0)
        self.ratio_entry_var.set(f"{value:.2f}")
        self._queue_kernel_update("ratio", value, immediate=False)

    def on_ratio_slider_released(self) -> None:
        """!
        @brief 在长宽比滑条释放时提交缓冲值。
        """
        value = self._parse_and_clamp_float(self.ratio_entry_var.get(), 0.02, 5.0, self.ratio_var.get())
        self.ratio_entry_var.set(f"{value:.2f}")
        self._queue_kernel_update("ratio", value, immediate=True)

    def on_ratio_entry_changed(self) -> None:
        """!
        @brief 处理长宽比输入框提交。
        """
        value = self._parse_and_clamp_float(self.ratio_entry_var.get(), 0.02, 5.0, self.ratio_var.get())
        self.ratio_entry_var.set(f"{value:.2f}")
        self._queue_kernel_update("ratio", value, immediate=True)

    def _update_ratio_info(self) -> None:
        """!
        @brief 刷新界面中的长宽比说明文字。
        """
        ratio = self.state.rect_height_ratio / max(self.state.rect_width_ratio, 1e-6)
        self.aspect_var.set(
            f"矩形高宽比(h/w): {ratio:.2f}    矩形宽高比(w/h): {1.0 / max(ratio, 1e-6):.3f}"
        )

    def _sync_image_controls(self) -> None:
        """!
        @brief 根据当前图像尺寸同步参数控件范围。
        """
        if self.service.current_bundle is None:
            return
        image_width = int(self.service.current_bundle.rgb.shape[1])
        image_height = int(self.service.current_bundle.rgb.shape[0])
        max_margin = max(image_height - 1, 0)
        max_horizontal_offset = max(image_width, 1)
        self.state.virtual_bottom_margin = min(max(self.state.virtual_bottom_margin, 0), max_margin)
        self.state.virtual_horizontal_offset = min(
            max(self.state.virtual_horizontal_offset, -max_horizontal_offset),
            max_horizontal_offset,
        )
        self.bottom_margin_scale.configure(to=max_margin)
        self.horizontal_offset_scale.configure(from_=-max_horizontal_offset, to=max_horizontal_offset)
        self.bottom_margin_var.set(self.state.virtual_bottom_margin)
        self.bottom_margin_entry_var.set(str(self.state.virtual_bottom_margin))
        self.horizontal_offset_var.set(self.state.virtual_horizontal_offset)
        self.horizontal_offset_entry_var.set(str(self.state.virtual_horizontal_offset))

    def on_binary_toggle(self) -> None:
        """!
        @brief 切换左侧显示原图或二值辅助图。
        """
        self._queue_kernel_update("binary_view_enabled", self.binary_var.get(), immediate=True)

    def on_threshold_slider_changed(self, value: str) -> None:
        """!
        @brief 处理二值阈值滑条拖动。
        @param value 滑条当前值。
        """
        if self._syncing_threshold_value:
            return
        value = self._clamp_int(int(float(value)), 0, 255)
        self.threshold_entry_var.set(str(value))
        self._queue_kernel_update("threshold", value, immediate=False)

    def on_threshold_slider_released(self) -> None:
        """!
        @brief 在阈值滑条释放时提交最终值。
        """
        value = self._parse_and_clamp_int(self.threshold_entry_var.get(), 0, 255, self.threshold_var.get())
        self.threshold_entry_var.set(str(value))
        self._queue_kernel_update("threshold", value, immediate=True)

    def on_threshold_entry_changed(self) -> None:
        """!
        @brief 处理阈值输入框提交。
        """
        value = self._parse_and_clamp_int(self.threshold_entry_var.get(), 0, 255, self.state.threshold)
        self.threshold_entry_var.set(str(value))
        self._queue_kernel_update("threshold", value, immediate=True)

    def on_bottom_margin_slider_changed(self, value: str) -> None:
        """!
        @brief 处理虚拟矩形底边距底部滑条拖动。
        @param value 滑条当前值。
        """
        if self._syncing_bottom_margin_value:
            return
        max_margin = int(self.bottom_margin_scale.cget("to"))
        value = self._clamp_int(int(float(value)), 0, max_margin)
        self.bottom_margin_entry_var.set(str(value))
        self._queue_kernel_update("bottom_margin", value, immediate=False)

    def on_bottom_margin_slider_released(self) -> None:
        """!
        @brief 在底边距离滑条释放时提交最终值。
        """
        value = self._parse_and_clamp_int(
            self.bottom_margin_entry_var.get(),
            0,
            int(self.bottom_margin_scale.cget("to")),
            self.bottom_margin_var.get(),
        )
        self.bottom_margin_entry_var.set(str(value))
        self._queue_kernel_update("bottom_margin", value, immediate=True)

    def on_bottom_margin_entry_changed(self) -> None:
        """!
        @brief 处理底边距离输入框提交。
        """
        max_margin = int(self.bottom_margin_scale.cget("to"))
        value = self._parse_and_clamp_int(self.bottom_margin_entry_var.get(), 0, max_margin, self.state.virtual_bottom_margin)
        self.bottom_margin_entry_var.set(str(value))
        self._queue_kernel_update("bottom_margin", value, immediate=True)

    def on_horizontal_offset_slider_changed(self, value: str) -> None:
        """!
        @brief 处理虚拟矩形水平偏移滑条拖动。
        @param value 滑条当前值。
        """
        if self._syncing_horizontal_offset_value:
            return
        min_offset = int(float(self.horizontal_offset_scale.cget("from")))
        max_offset = int(float(self.horizontal_offset_scale.cget("to")))
        value = self._clamp_int(int(float(value)), min_offset, max_offset)
        self.horizontal_offset_entry_var.set(str(value))
        self._queue_kernel_update("horizontal_offset", value, immediate=False)

    def on_horizontal_offset_slider_released(self) -> None:
        """!
        @brief 在水平偏移滑条释放时提交最终值。
        """
        value = self._parse_and_clamp_int(
            self.horizontal_offset_entry_var.get(),
            int(float(self.horizontal_offset_scale.cget("from"))),
            int(float(self.horizontal_offset_scale.cget("to"))),
            self.horizontal_offset_var.get(),
        )
        self.horizontal_offset_entry_var.set(str(value))
        self._queue_kernel_update("horizontal_offset", value, immediate=True)

    def on_horizontal_offset_entry_changed(self) -> None:
        """!
        @brief 处理水平偏移输入框提交。
        """
        min_offset = int(float(self.horizontal_offset_scale.cget("from")))
        max_offset = int(float(self.horizontal_offset_scale.cget("to")))
        value = self._parse_and_clamp_int(self.horizontal_offset_entry_var.get(), min_offset, max_offset, self.state.virtual_horizontal_offset)
        self.horizontal_offset_entry_var.set(str(value))
        self._queue_kernel_update("horizontal_offset", value, immediate=True)

    def on_width_scale_slider_changed(self, value: str) -> None:
        """!
        @brief 处理底面边长度缩放滑条拖动。
        @param value 滑条当前值。
        """
        if self._syncing_width_scale_value:
            return
        value = self._clamp_float(float(value), 0.5, 2.0)
        self.width_scale_entry_var.set(f"{value:.2f}")
        self._queue_kernel_update("width_scale", value, immediate=False)

    def on_width_scale_slider_released(self) -> None:
        """!
        @brief 在底面边长度缩放滑条释放时提交最终值。
        """
        value = self._parse_and_clamp_float(self.width_scale_entry_var.get(), 0.5, 2.0, self.width_scale_var.get())
        self.width_scale_entry_var.set(f"{value:.2f}")
        self._queue_kernel_update("width_scale", value, immediate=True)

    def on_width_scale_entry_changed(self) -> None:
        """!
        @brief 处理底面边长度缩放输入框提交。
        """
        value = self._parse_and_clamp_float(self.width_scale_entry_var.get(), 0.5, 2.0, self.state.ground_width_scale)
        self.width_scale_entry_var.set(f"{value:.2f}")
        self._queue_kernel_update("width_scale", value, immediate=True)

    def _set_threshold_value(self, value: int, recompute: bool, refresh_image: bool) -> None:
        """!
        @brief 将阈值写回状态并同步界面。
        @param value 阈值。
        @param recompute 是否在写入后重算预览。
        @param refresh_image 是否刷新左侧显示图。
        """
        self.state.threshold = self._clamp_int(value, 0, 255)
        self._syncing_threshold_value = True
        try:
            self.threshold_var.set(self.state.threshold)
            self.threshold_entry_var.set(str(self.state.threshold))
        finally:
            self._syncing_threshold_value = False
        if self.service.original_rgb is None:
            return
        if refresh_image:
            self.service.update_threshold(self.state.threshold)
            self.refresh_input_view()
        if recompute:
            self.recompute_if_ready()

    def _set_bottom_margin_value(self, value: int, recompute: bool) -> None:
        """!
        @brief 将虚拟矩形底边距底部参数写回状态。
        @param value 新值。
        @param recompute 是否重算预览。
        """
        max_margin = int(self.bottom_margin_scale.cget("to"))
        self.state.virtual_bottom_margin = self._clamp_int(value, 0, max_margin)
        self._syncing_bottom_margin_value = True
        try:
            self.bottom_margin_var.set(self.state.virtual_bottom_margin)
            self.bottom_margin_entry_var.set(str(self.state.virtual_bottom_margin))
        finally:
            self._syncing_bottom_margin_value = False
        if recompute:
            self.recompute_if_ready()

    def _set_horizontal_offset_value(self, value: int, recompute: bool) -> None:
        """!
        @brief 将虚拟矩形水平偏移写回状态。
        @param value 新值。
        @param recompute 是否重算预览。
        """
        min_offset = int(float(self.horizontal_offset_scale.cget("from")))
        max_offset = int(float(self.horizontal_offset_scale.cget("to")))
        self.state.virtual_horizontal_offset = self._clamp_int(value, min_offset, max_offset)
        self._syncing_horizontal_offset_value = True
        try:
            self.horizontal_offset_var.set(self.state.virtual_horizontal_offset)
            self.horizontal_offset_entry_var.set(str(self.state.virtual_horizontal_offset))
        finally:
            self._syncing_horizontal_offset_value = False
        if recompute:
            self.recompute_if_ready()

    def _set_width_scale_value(self, value: float, recompute: bool) -> None:
        """!
        @brief 将底面边长度缩放写回状态。
        @param value 新值。
        @param recompute 是否重算预览。
        """
        self.state.ground_width_scale = self._clamp_float(value, 0.5, 2.0)
        self._syncing_width_scale_value = True
        try:
            self.width_scale_var.set(self.state.ground_width_scale)
            self.width_scale_entry_var.set(f"{self.state.ground_width_scale:.2f}")
        finally:
            self._syncing_width_scale_value = False
        if recompute:
            self.recompute_if_ready()

    def _set_ratio_value(self, value: float, recompute: bool) -> None:
        """!
        @brief 将矩形高宽比写回状态。
        @param value 新的 h/w 比值。
        @param recompute 是否重算预览。
        """
        ratio = self._clamp_float(value, 0.02, 5.0)
        self.state.rect_width_ratio = 1.0
        self.state.rect_height_ratio = ratio
        self._syncing_ratio_value = True
        try:
            self.ratio_var.set(ratio)
            self.ratio_entry_var.set(f"{ratio:.2f}")
        finally:
            self._syncing_ratio_value = False
        self._update_ratio_info()
        if recompute:
            self.recompute_if_ready()

    def on_physical_width_changed(self) -> None:
        """!
        @brief 处理底面边实际物理长度输入。
        """
        value = self._parse_and_clamp_float(
            self.physical_width_var.get(),
            0.001,
            100.0,
            self.state.physical_ground_width_m,
        )
        self.physical_width_var.set(f"{value:.3f}")
        self._queue_kernel_update("physical_width_m", value, immediate=True)

    @staticmethod
    def _clamp_int(value: int, minimum: int, maximum: int) -> int:
        """!
        @brief 对整数值做区间夹紧。
        @param value 输入值。
        @param minimum 下限。
        @param maximum 上限。
        @return 合法区间内的整数值。
        """
        return max(minimum, min(int(value), maximum))

    @staticmethod
    def _clamp_float(value: float, minimum: float, maximum: float) -> float:
        """!
        @brief 对浮点值做区间夹紧。
        @param value 输入值。
        @param minimum 下限。
        @param maximum 上限。
        @return 合法区间内的浮点值。
        """
        return max(minimum, min(float(value), maximum))

    def _parse_and_clamp_int(self, raw: str, minimum: int, maximum: int, fallback: int) -> int:
        """!
        @brief 解析并夹紧整数输入。
        @param raw 原始字符串。
        @param minimum 下限。
        @param maximum 上限。
        @param fallback 解析失败时的回退值。
        @return 处理后的整数值。
        """
        try:
            value = int(float(raw.strip()))
        except (ValueError, TypeError):
            value = fallback
        return self._clamp_int(value, minimum, maximum)

    def _parse_and_clamp_float(self, raw: str, minimum: float, maximum: float, fallback: float) -> float:
        """!
        @brief 解析并夹紧浮点输入。
        @param raw 原始字符串。
        @param minimum 下限。
        @param maximum 上限。
        @param fallback 解析失败时的回退值。
        @return 处理后的浮点值。
        """
        try:
            value = float(raw.strip())
        except (ValueError, TypeError):
            value = fallback
        return self._clamp_float(value, minimum, maximum)

    def _set_status(self, message: str, *, log: bool = False) -> None:
        """!
        @brief 更新状态文本。
        @param message 状态内容。
        @param log 是否同步写入日志。
        """
        self.status_var.set(message)
        if log:
            self._log_event(message)

    def _log_event(self, message: str) -> None:
        """!
        @brief 追加一条日志到滚动日志文件。
        @param message 日志内容。
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"[{timestamp}] {message}\n"
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(line)
            self._trim_log_file()
        except OSError:
            pass

    def _trim_log_file(self) -> None:
        """!
        @brief 截断日志文件，只保留最近一段内容。
        """
        try:
            if not self._log_path.exists() or self._log_path.stat().st_size <= self._log_max_bytes:
                return
            data = self._log_path.read_bytes()
            tail = data[-self._log_max_bytes :]
            newline_pos = tail.find(b"\n")
            if newline_pos != -1 and newline_pos + 1 < len(tail):
                tail = tail[newline_pos + 1 :]
            self._log_path.write_bytes(tail)
        except OSError:
            pass

    def _report_callback_exception(self, exc: type[BaseException], val: BaseException, tb) -> None:
        """!
        @brief 记录 Tk 回调中的未捕获异常。
        @param exc 异常类型。
        @param val 异常对象。
        @param tb Traceback 对象。
        """
        error_text = "".join(traceback.format_exception(exc, val, tb))
        self._log_event("UNHANDLED_EXCEPTION\n" + error_text)
        traceback.print_exception(exc, val, tb)

    def request_save_preview(self) -> None:
        """!
        @brief 请求保存当前逆透视预览图。
        """
        self._queue_kernel_update("save_preview", True, immediate=True)

    def _save_preview_image(self) -> None:
        """!
        @brief 将当前预览图保存到 Picture 目录。
        """
        if self.current_preview is None:
            self._log_event("保存预览图失败: 当前没有可保存的逆透视结果")
            messagebox.showinfo("提示", "当前没有可保存的逆透视预览图。")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        output_path = self._picture_dir / f"{timestamp}.png"

        try:
            self.service.save_preview_image(self.current_preview, output_path)
            self._set_status(f"预览图已保存: {output_path.name}", log=True)
            messagebox.showinfo("保存成功", f"预览图已保存到:\n{output_path}")
        except Exception as exc:
            self._log_event(f"保存预览图失败: {exc}")
            messagebox.showerror("保存失败", str(exc))

    def _queue_kernel_update(self, key: str, value: object, *, immediate: bool = False) -> None:
        """!
        @brief 向缓冲层写入一条待处理更新。
        @param key 更新键名。
        @param value 更新值。
        @param immediate 是否立即触发一次缓冲提交。
        """
        self._pending_kernel_updates[key] = value
        self._schedule_kernel_flush(immediate=immediate)

    def _schedule_kernel_flush(self, *, immediate: bool = False) -> None:
        """!
        @brief 以固定节奏调度缓冲层向内核提交。
        @param immediate 是否立即调度。
        """
        if immediate:
            if self._buffer_flush_job is not None:
                self.root.after_cancel(self._buffer_flush_job)
            self._buffer_flush_job = self.root.after(0, self._flush_kernel_buffer)
            return
        if self._buffer_flush_job is None:
            self._buffer_flush_job = self.root.after(self._buffer_frame_interval_ms, self._flush_kernel_buffer)

    def _set_kernel_busy(self, busy: bool, message: str | None = None) -> None:
        """!
        @brief 设置内核忙闲标记。
        @param busy 是否繁忙。
        @param message 可选状态提示文字。
        """
        self._kernel_busy = busy
        self._kernel_ready = not busy
        if message:
            self._set_status(message, log=False)

    def _flush_kernel_buffer(self) -> None:
        """!
        @brief 将缓冲层中的最新参数批量提交给内核。
        """
        self._buffer_flush_job = None
        if self._kernel_busy or not self._pending_kernel_updates:
            if self._pending_kernel_updates:
                self._schedule_kernel_flush()
            return

        updates = dict(self._pending_kernel_updates)
        self._pending_kernel_updates.clear()
        self._set_status("缓冲层提交参数中...", log=False)
        try:
            self._apply_kernel_updates(updates)
        finally:
            if self._pending_kernel_updates:
                self._schedule_kernel_flush(immediate=True)
            elif not self._kernel_busy:
                self._set_status("内核就绪", log=False)

    def _apply_kernel_updates(self, updates: dict[str, object]) -> None:
        """!
        @brief 应用一批缓冲层合并后的更新命令。
        @param updates 待处理的命令字典。
        """
        if not updates:
            return

        threshold_changed = False
        geometry_changed = False
        display_changed = False
        info_only_changed = False
        save_preview_requested = bool(updates.get("save_preview", False))

        if "binary_view_enabled" in updates:
            self.state.binary_view_enabled = bool(updates["binary_view_enabled"])
            self.binary_var.set(self.state.binary_view_enabled)
            display_changed = True

        if "threshold" in updates:
            threshold = self._clamp_int(int(updates["threshold"]), 0, 255)
            self.state.threshold = threshold
            self._syncing_threshold_value = True
            try:
                self.threshold_var.set(threshold)
                self.threshold_entry_var.set(str(threshold))
            finally:
                self._syncing_threshold_value = False
            threshold_changed = True
            display_changed = True

        if "ratio" in updates:
            ratio = self._clamp_float(float(updates["ratio"]), 0.02, 5.0)
            self.state.rect_width_ratio = 1.0
            self.state.rect_height_ratio = ratio
            self._syncing_ratio_value = True
            try:
                self.ratio_var.set(ratio)
                self.ratio_entry_var.set(f"{ratio:.2f}")
            finally:
                self._syncing_ratio_value = False
            self._update_ratio_info()
            geometry_changed = True

        if "bottom_margin" in updates:
            max_margin = int(self.bottom_margin_scale.cget("to"))
            margin = self._clamp_int(int(updates["bottom_margin"]), 0, max_margin)
            self.state.virtual_bottom_margin = margin
            self._syncing_bottom_margin_value = True
            try:
                self.bottom_margin_var.set(margin)
                self.bottom_margin_entry_var.set(str(margin))
            finally:
                self._syncing_bottom_margin_value = False
            geometry_changed = True

        if "horizontal_offset" in updates:
            min_offset = int(float(self.horizontal_offset_scale.cget("from")))
            max_offset = int(float(self.horizontal_offset_scale.cget("to")))
            offset = self._clamp_int(int(updates["horizontal_offset"]), min_offset, max_offset)
            self.state.virtual_horizontal_offset = offset
            self._syncing_horizontal_offset_value = True
            try:
                self.horizontal_offset_var.set(offset)
                self.horizontal_offset_entry_var.set(str(offset))
            finally:
                self._syncing_horizontal_offset_value = False
            geometry_changed = True

        if "width_scale" in updates:
            width_scale = self._clamp_float(float(updates["width_scale"]), 0.5, 2.0)
            self.state.ground_width_scale = width_scale
            self._syncing_width_scale_value = True
            try:
                self.width_scale_var.set(width_scale)
                self.width_scale_entry_var.set(f"{width_scale:.2f}")
            finally:
                self._syncing_width_scale_value = False
            geometry_changed = True

        if "physical_width_m" in updates:
            width_m = self._clamp_float(float(updates["physical_width_m"]), 0.001, 100.0)
            self.state.physical_ground_width_m = width_m
            self.physical_width_var.set(f"{width_m:.3f}")
            info_only_changed = True

        if self.service.original_rgb is not None and threshold_changed:
            self.service.update_threshold(self.state.threshold)

        if self.service.original_rgb is not None and display_changed:
            self.refresh_input_view()

        should_recompute = geometry_changed or ("binary_view_enabled" in updates)
        if self.state.binary_view_enabled and threshold_changed:
            should_recompute = True

        if should_recompute:
            self.recompute_if_ready()
        else:
            self.refresh_aux_info()
            if info_only_changed:
                self._update_output_text()

        if save_preview_requested:
            self._save_preview_image()

    def on_mouse_move(self, event: tk.Event) -> None:
        """!
        @brief 处理鼠标在原图上的移动。
        @param event Tk 事件对象。
        """
        pos = self.input_view.canvas_to_image(event.x, event.y)
        if pos is None:
            self.state.hover.visible = False
            self.hover_var.set("x: -, y: -")
        else:
            self.state.hover.x, self.state.hover.y = pos
            self.state.hover.visible = True
            self.hover_var.set(f"x: {pos[0]}, y: {pos[1]}")
        self.draw_input_overlay()

    def on_mouse_leave(self, _event: tk.Event) -> None:
        """!
        @brief 处理鼠标离开原图区域。
        @param _event Tk 事件对象。
        """
        self.state.hover.visible = False
        self.hover_var.set("x: -, y: -")
        self.draw_input_overlay()

    def on_canvas_click(self, event: tk.Event) -> None:
        """!
        @brief 处理原图点击选点。
        @param event Tk 事件对象。
        """
        pos = self.input_view.canvas_to_image(event.x, event.y)
        if pos is None:
            return
        self.state.add_point((float(pos[0]), float(pos[1])))
        self.ordered_points = self._get_sorted_points()
        self._set_status(f"已选择 {len(self.state.points)}/4 个点", log=True)
        self.recompute_if_ready()
        self.refresh_all()

    def undo_point(self) -> None:
        """!
        @brief 撤销最后一个选点。
        """
        self.state.undo_last_point()
        self.current_preview = None
        self.ordered_points = self._get_sorted_points()
        self._update_output_text()
        self._set_status("已撤销最后一个点", log=True)
        self.refresh_all()

    def clear_points(self) -> None:
        """!
        @brief 清空当前全部选点。
        """
        self.state.clear_points()
        self.current_preview = None
        self.ordered_points = []
        self._update_output_text()
        self._set_status("已清空四点", log=True)
        self.refresh_all()

    def compute_preview(self, silent: bool = False) -> None:
        """!
        @brief 基于当前稳定状态执行一次完整预览计算。
        @param silent 是否静默处理提示框。
        """
        if self._kernel_busy:
            self._schedule_kernel_flush()
            return
        if self.service.current_bundle is None:
            if not silent:
                self._log_event("计算提示: 未打开图像")
                messagebox.showinfo("提示", "请先打开一张图像。")
            return
        if not self.state.has_complete_selection:
            if not silent:
                self._log_event("计算提示: 未选择四个点")
                messagebox.showinfo("提示", "请先选择四个点。")
            return
        self._set_kernel_busy(True, "内核计算中...")
        try:
            preview_array, ordered = self.service.warp_preview(self.state)
            self.current_preview = Image.fromarray(preview_array) if preview_array is not None else None
            self.ordered_points = ordered
            self._update_output_text()
            self._set_status("全局逆透视矩阵计算完成", log=False)
            self.refresh_all()
        except Exception as exc:
            self._log_event(f"计算失败: {exc}")
            if not silent:
                messagebox.showerror("计算失败", str(exc))
        finally:
            self._set_kernel_busy(False, "内核就绪")
            if self._pending_kernel_updates:
                self._schedule_kernel_flush(immediate=True)

    def recompute_if_ready(self) -> None:
        """!
        @brief 在条件满足时触发重算，否则仅刷新辅助信息。
        """
        if self._kernel_busy:
            self._schedule_kernel_flush()
            return
        if self.state.has_complete_selection and self.service.current_bundle is not None:
            self.compute_preview(silent=True)
        else:
            self._update_output_text()
            self.refresh_aux_info()
            self.draw_input_overlay()

    def schedule_viewport_refresh(self) -> None:
        """!
        @brief 延迟调度一次视口刷新。
        """
        if self._viewport_redraw_job is not None:
            self.root.after_cancel(self._viewport_redraw_job)
        self._viewport_redraw_job = self.root.after(50, self.refresh_all)

    def copy_matrix(self) -> None:
        """!
        @brief 复制当前矩阵输出文本到剪贴板。
        """
        content = self.matrix_text.get("1.0", "end").strip()
        if not content:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self._set_status("输出已复制到剪贴板", log=True)

    def refresh_all(self) -> None:
        """!
        @brief 刷新整个界面显示。
        """
        self.refresh_input_view()
        self.refresh_preview_view()
        self.refresh_points_panel()
        self.refresh_aux_info()

    def refresh_input_view(self) -> None:
        """!
        @brief 刷新左侧原图或二值辅助图。
        """
        if self.service.current_bundle is None:
            self.input_view.set_image(None)
            return
        display = self.service.get_display_image(self.state)
        self.input_view.set_image(Image.fromarray(display))
        self.draw_input_overlay()

    def refresh_preview_view(self) -> None:
        """!
        @brief 刷新右侧逆透视预览图。
        """
        self.preview_view.set_image(self.current_preview)
        self.draw_preview_overlay()

    def refresh_points_panel(self) -> None:
        """!
        @brief 刷新左侧点位信息面板。
        """
        ordered_rows = []
        if self.state.has_complete_selection:
            ordered_rows = ordered_point_rows(self.state.points)

        for idx, style in enumerate(POINT_STYLES):
            if idx < len(ordered_rows):
                label, (x, y) = ordered_rows[idx]
                self.point_value_vars[idx].set(f"{label}: ({x:.1f}, {y:.1f})")
            else:
                self.point_value_vars[idx].set(f'{style["label"]}: -')

        if not self.state.points:
            self.raw_points_var.set("尚未选点")
            return
        raw_lines = [f"P{i + 1}: ({int(x)}, {int(y)})" for i, (x, y) in enumerate(self.state.points)]
        self.raw_points_var.set("\n".join(raw_lines))

    def refresh_aux_info(self) -> None:
        """!
        @brief 刷新虚拟矩形和 M2PIX 等辅助信息。
        """
        if self.state.virtual_rectangle is not None:
            vr = self.state.virtual_rectangle
            self.virtual_rect_var.set(
                f"虚拟矩形: 宽 {vr.width:.1f}px, 高 {vr.height:.1f}px, 底距 {self.state.virtual_bottom_margin}px, 横移 {self.state.virtual_horizontal_offset}px"
            )
        else:
            self.virtual_rect_var.set("虚拟矩形: -")

        m2pix = calculate_m2pix(self.state.virtual_rectangle, self.state.physical_ground_width_m)
        if m2pix is None:
            self.m2pix_var.set("M2PIX: -")
        else:
            self.m2pix_var.set(
                f"M2PIX: {m2pix:.3f} px/m   底边实际长度: {self.state.physical_ground_width_m:.3f} m"
            )

    def draw_input_overlay(self) -> None:
        """!
        @brief 重绘左侧输入图上的叠加层。
        """
        self._draw_selection_overlay(self.input_view)

    def _draw_selection_overlay(self, view: ImageViewport) -> None:
        """!
        @brief 在指定视口上绘制选点、多边形与虚拟矩形。
        @param view 目标视口。
        """
        canvas = view.canvas
        canvas.delete("overlay")

        points = self.state.points
        if len(points) >= 2:
            coords = []
            for x, y in points:
                cx, cy = view.image_to_canvas_point(x, y)
                coords.extend((cx, cy))
            canvas.create_line(*coords, fill="#c19a80", width=2, tags="overlay")

        sorted_points = self._get_sorted_points()
        if len(sorted_points) == 4:
            polygon = []
            for x, y in sorted_points:
                cx, cy = view.image_to_canvas_point(x, y)
                polygon.extend((cx, cy))
            canvas.create_polygon(*polygon, outline="#876954", fill="", width=2, tags="overlay")

            if self.state.virtual_rectangle is not None:
                rect_coords = []
                for x, y in self.state.virtual_rectangle.points:
                    cx, cy = view.image_to_canvas_point(x, y)
                    rect_coords.extend((cx, cy))
                canvas.create_polygon(
                    *rect_coords,
                    outline="#8b3fd1",
                    fill="",
                    width=2,
                    dash=(6, 4),
                    tags="overlay",
                )

            for point, style in zip(sorted_points, POINT_STYLES):
                cx, cy = view.image_to_canvas_point(point[0], point[1])
                self._draw_point_marker(canvas, cx, cy, style["label"], style["color"])

        if self.state.hover.visible:
            cx, cy = view.image_to_canvas_point(self.state.hover.x, self.state.hover.y)
            self._draw_hover_marker(canvas, cx, cy)

    def draw_preview_overlay(self) -> None:
        """!
        @brief 绘制右侧预览图的边框和信息浮层。
        """
        canvas = self.preview_view.canvas
        canvas.delete("overlay")
        width, height = self.preview_view.display_size
        if width <= 0 or height <= 0:
            return

        x0, y0 = self.preview_view.image_offset
        canvas.create_rectangle(
            x0,
            y0,
            x0 + width,
            y0 + height,
            outline="#cdbbab",
            width=2,
            tags="overlay",
        )

        if self.state.virtual_rectangle is not None:
            vr = self.state.virtual_rectangle
            mode_text = (
                f"全局逆透视 {self.preview_view.image_size[0]} x {self.preview_view.image_size[1]}\n"
                f"虚拟矩形 {vr.width:.1f} x {vr.height:.1f} | 底距 {self.state.virtual_bottom_margin}px"
            )
            canvas.create_rectangle(
                x0 + 12,
                y0 + 12,
                x0 + 280,
                y0 + 58,
                fill="#231b16",
                outline="",
                tags="overlay",
            )
            canvas.create_text(
                x0 + 20,
                y0 + 22,
                text=mode_text,
                fill="#f8eee3",
                anchor="nw",
                font=("Microsoft YaHei UI", 9, "bold"),
                tags="overlay",
            )

    def _get_sorted_points(self) -> list[tuple[float, float]]:
        """!
        @brief 获取当前标准排序后的四点。
        @return 排序成功时返回四点，否则返回空列表。
        """
        if not self.state.has_complete_selection:
            return []
        try:
            return sort_quad_points(self.state.points)
        except Exception:
            return []

    def _update_output_text(self) -> None:
        """!
        @brief 根据当前矩阵状态刷新输出文本框。
        """
        self.matrix_text.delete("1.0", "end")
        if self.state.homography is None or self.state.inverse_homography is None:
            return
        content = format_output_block(
            self.state.homography,
            self.state.inverse_homography,
            self.state.virtual_rectangle,
            self.state.physical_ground_width_m,
        )
        self.matrix_text.insert("1.0", content)

    @staticmethod
    def _draw_point_marker(canvas: tk.Canvas, x: float, y: float, label: str, color: str) -> None:
        """!
        @brief 绘制一个彩色点位标记。
        @param canvas 目标画布。
        @param x 画布 x 坐标。
        @param y 画布 y 坐标。
        @param label 点位标签。
        @param color 标记颜色。
        """
        canvas.create_oval(
            x - 8,
            y - 8,
            x + 8,
            y + 8,
            fill=color,
            outline="#fff7f0",
            width=2,
            tags="overlay",
        )
        canvas.create_text(
            x,
            y - 16,
            text=label,
            fill=color,
            font=("Microsoft YaHei UI", 9, "bold"),
            tags="overlay",
        )

    @staticmethod
    def _draw_hover_marker(canvas: tk.Canvas, x: float, y: float) -> None:
        """!
        @brief 绘制鼠标悬停十字准星。
        @param canvas 目标画布。
        @param x 画布 x 坐标。
        @param y 画布 y 坐标。
        """
        canvas.create_oval(
            x - 7,
            y - 7,
            x + 7,
            y + 7,
            outline="#ff5445",
            width=2,
            tags="overlay",
        )
        canvas.create_line(x - 12, y, x + 12, y, fill="#ff5445", width=1, tags="overlay")
        canvas.create_line(x, y - 12, x, y + 12, fill="#ff5445", width=1, tags="overlay")
        canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill="#ff5445", outline="", tags="overlay")


def main() -> None:
    """!
    @brief 启动标定工具图形界面。
    """
    parser = argparse.ArgumentParser(description="Perspective matrix calibration tool.")
    parser.add_argument("--image", type=str, help="Optional image path to open on startup.")
    args = parser.parse_args()

    root = tk.Tk()
    CalibrationApp(root, image_path=args.image)
    root.mainloop()


if __name__ == "__main__":
    main()
