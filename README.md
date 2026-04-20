# calibration

一个用于逆透视矩阵标定的独立 GUI 工具，针对使用了逆透视技术需要标定逆矩阵的智能车视觉算法设计，主要能力包括：

- 加载原始图像并进行辅助显示
- 手动选择四个参考点
- 基于参考四边形构造虚拟目标矩形
- 实时计算 `M`、`M_Reverse` 和 `M2PIX`
- 生成全局逆透视预览图

适用场景包括：

- 车载视觉或俯视变换场景中的逆透视矩阵标定
- 需要从图像交互式调参与导出工程参数的场景

## 仓库结构

```text
calibration/
├─ README.md
├─ .gitignore
├─ LOGO/
└─ perspective_calibrator/
   ├─ app.py
   ├─ core.py
   ├─ services.py
   ├─ build_windows.py
   ├─ assets/
   └─ README.md
```

其中：

- `LOGO/` 用于存放仓库或工具相关的图形资源
- `perspective_calibrator/` 是当前主要工具目录
- `perspective_calibrator/app.py` 是源码启动入口
- `perspective_calibrator/build_windows.py` 是 Windows 打包脚本

## 快速开始

### 1. 运行源码版工具

在仓库根目录执行：

```bash
python perspective_calibrator/app.py
```

如果希望启动时直接加载一张图片：

```bash
python perspective_calibrator/app.py --image path/to/your_image.png
```

### 2. 打包 Windows 可执行文件

在仓库根目录执行：

```bash
python perspective_calibrator/build_windows.py
```

默认产物输出到：

```text
perspective_calibrator/dist/PerspectiveMatrixCalibrator.exe
```

## 工具设计思路

当前 `perspective_calibrator` 已经做了基础解耦，整体上分为几层职责：

- `app.py` 负责界面、交互、缓冲调度和输出触发
- `core.py` 负责纯几何和矩阵计算
- `services.py` 负责图像加载、缓存、预览生成和落盘
- `build_windows.py` 负责打包流程


## 输出结果

该仓库中的逆透视标定工具可输出：

- 工程可用的透视矩阵 `M`
- 逆透视矩阵 `M_Reverse`
- 像素与物理尺度换算参数 `M2PIX`
- 逆透视预览图
- 标定会话配置文件


如果你是第一次进入这个仓库，建议优先阅读 [perspective_calibrator/README.md](D:\python_project\calibration\perspective_calibrator\README.md) 了解当前核心工具的详细说明。
