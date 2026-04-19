# calibration

`calibration` 是一个面向视觉标定与几何变换场景的工具仓库，用来沉淀和管理与图像校准、透视关系处理、参数生成相关的独立工具。

当前仓库的核心内容是一个用于计算全局逆透视矩阵的桌面标定工具 `perspective_calibrator`。它提供图形界面，支持从原始图像中选择参考四边形，构造目标矩形，实时生成逆透视矩阵与预览结果，并输出可直接用于工程集成的矩阵文本。

## 仓库目标

- 沉淀与标定相关的独立工具，而不是把所有逻辑直接散落在业务工程中
- 让算法验证、参数调试、可视化预览和工程输出分离开来
- 支持把工具目录整体复制到其他环境中单独运行
- 为后续扩展更多标定类工具预留统一的仓库结构

## 当前包含的工具

### `perspective_calibrator`

一个用于逆透视矩阵标定的独立 GUI 工具，主要能力包括：

- 加载原始图像并进行辅助显示
- 手动选择四个参考点
- 基于参考四边形构造虚拟目标矩形
- 实时计算 `M`、`M_Reverse` 和 `M2PIX`
- 生成全局逆透视预览图
- 保存预览图与会话配置
- 打包为 Windows 单文件 `exe`

适用场景包括：

- 车载视觉或俯视变换场景中的逆透视矩阵标定
- 需要从图像交互式调参与导出工程参数的场景
- 希望把标定工具从主工程中解耦、独立维护的场景

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

这种结构的目标是让高频 UI 交互、图像处理和核心数学逻辑彼此独立，降低后续维护和扩展成本。

## 输出结果

该仓库中的逆透视标定工具可输出：

- 工程可用的透视矩阵 `M`
- 逆透视矩阵 `M_Reverse`
- 像素与物理尺度换算参数 `M2PIX`
- 逆透视预览图
- 标定会话配置文件

## 后续规划

这个仓库可以继续扩展更多与标定相关的工具，例如：

- 相机内外参辅助标定工具
- 畸变校正参数调试工具
- 鸟瞰图拼接或投影关系分析工具
- 标定结果批量验证与导出工具

## 说明

- 仓库当前以 Windows + Python 工具链为主
- 打包流程依赖 `PyInstaller`
- 部分运行产物和打包产物已通过根目录 `.gitignore` 过滤

如果你是第一次进入这个仓库，建议优先阅读 [perspective_calibrator/README.md](D:\python_project\calibration\perspective_calibrator\README.md) 了解当前核心工具的详细说明。
