# ORBITAL DC-1 · Space Data Center Simulator — 详尽技术文档

> **入口文件**: `index.html`  
> **版本**: 模块化重构版  
> **类型**: 模块化 Web 应用（HTML + CSS + 12 个 JavaScript 模块，含 Canvas 2D 实时渲染 + Digital Twin）  
> **用途**: 模拟一个部署在太阳同步轨道 (SSO) 550km 高度的 1MW 级太空数据中心的运行状态

---

## 目录

1. [项目概述](#1-项目概述)
2. [文件结构总览](#2-文件结构总览)
3. [HTML 结构详解](#3-html-结构详解)
   - 3.1 [文档头部 `<head>`](#31-文档头部-head)
   - 3.2 [星空背景画布 `#starfield`](#32-星空背景画布-starfield)
   - 3.3 [顶部导航栏 `.header`](#33-顶部导航栏-header)
   - 3.4 [主布局 `.outer`](#34-主布局-outer)
   - 3.5 [左侧内容区 `.left-main`](#35-左侧内容区-left-main)
   - 3.6 [右侧边栏 `.rsidebar`](#36-右侧边栏-rsidebar)
   - 3.7 [底部状态栏 `.botbar`](#37-底部状态栏-botbar)
4. [CSS 样式系统详解](#4-css-样式系统详解)
   - 4.1 [CSS 变量 (Design Tokens)](#41-css-变量-design-tokens)
   - 4.2 [字体系统](#42-字体系统)
   - 4.3 [布局系统](#43-布局系统)
   - 4.4 [组件样式](#44-组件样式)
   - 4.5 [动画](#45-动画)
5. [JavaScript 逻辑详解](#5-javascript-逻辑详解)
   - 5.1 [全局状态变量](#51-全局状态变量)
   - 5.2 [数据模型 (Wings & Radiator Panels)](#52-数据模型-wings--radiator-panels)
   - 5.3 [星空渲染 (Starfield)](#53-星空渲染-starfield)
   - 5.4 [Canvas 引用与初始化](#54-canvas-引用与初始化)
   - 5.5 [轨道判断工具函数](#55-轨道判断工具函数)
   - 5.6 [轨道视图绘制 `drawOrbit()`](#56-轨道视图绘制-draworbit)
   - 5.7 [卫星图标绘制 `drawSatIcon()`](#57-卫星图标绘制-drawsaticon)
   - 5.8 [航天器详情视图 `drawDetail()`](#58-航天器详情视图-drawdetail)
   - 5.9 [太阳能阵列视图 `drawSolarArray()`](#59-太阳能阵列视图-drawsolararray)
   - 5.10 [辐射散热器视图 `drawRadiator()`](#510-辐射散热器视图-drawradiator)
   - 5.11 [表格数据更新](#511-表格数据更新)
   - 5.12 [遥测日志系统](#512-遥测日志系统)
   - 5.13 [主更新循环 `update()`](#513-主更新循环-update)
   - 5.14 [时间加速控制 `setSpeed()`](#514-时间加速控制-setspeed)
   - 5.15 [动画主循环 `animate()`](#515-动画主循环-animate)
   - 5.16 [趋势图 `drawTrend()`](#516-趋势图-drawtrend)
   - 5.17 [Digital Twin 控件 `setupDTControls()`](#517-digital-twin-控件-setupdtcontrols)
6. [物理模型与公式](#6-物理模型与公式)
7. [模拟参数一览表](#7-模拟参数一览表)
8. [交互功能说明](#8-交互功能说明)
9. [Digital Twin 功能总览](#9-digital-twin-功能总览)
10. [散热器材料编辑器](#10-功能-1散热器材料编辑器-radiator-material-editor)
11. [太阳能翼数量/面积调节](#11-功能-2太阳能翼数量面积调节-solar-wing-configuration)
12. [太阳能电池技术选择](#12-功能-3太阳能电池技术选择-cell-technology-selection)
13. [散热器面板数量/面积调节](#13-功能-4散热器面板数量面积调节-radiator-panel-configuration)
14. [实时趋势图](#14-功能-5实时趋势图-real-time-trend-chart)
15. [Digital Twin 控制面板交互总览](#15-digital-twin-控制面板交互总览)
16. [物理模型补充](#16-物理模型补充digital-twin-扩展)
17. [完整参数交叉影响矩阵](#17-完整参数交叉影响矩阵)
18. [卫星模型动态跟随参数变化](#18-功能-6卫星3d模型动态跟随参数变化-satellite-visual-follows-dt-parameters)
19. [Workload 负载选择](#19-功能-7workload-负载选择-compute-workload-configuration)
   - 19.1 [功能描述](#191-功能描述)
   - 19.2 [Workload 数据模型](#192-workload-数据模型)
   - 19.3 [预设负载一览](#193-预设负载一览)
   - 19.4 [散热可行性判断](#194-散热可行性判断)
   - 19.5 [对仿真引擎的影响](#195-对仿真引擎的影响)
20. [模块化架构说明](#20-模块化架构说明)
   - 20.1 [设计目标](#201-设计目标)
   - 20.2 [文件清单与职责](#202-文件清单与职责)
   - 20.3 [加载顺序与依赖](#203-加载顺序与依赖)
   - 20.4 [模块间通信方式](#204-模块间通信方式)
   - 20.5 [扩展指南](#205-扩展指南)

---

## 1. 项目概述

本项目是一个**纯前端模块化 Web 模拟器**，使用 HTML5 Canvas 2D API 实时渲染一个虚构的太空数据中心——**ORBITAL DC-1** 的运行全貌，并提供 Digital Twin 数字孪生交互调参功能。

### 核心模拟场景

| 维度 | 描述 |
|------|------|
| **轨道** | 太阳同步轨道 (SSO)，高度 550km，轨道倾角 97.6° |
| **周期** | 95.7 分钟/圈，其中 64% 为日照段，36% 为食 (Eclipse) 段 |
| **电力** | 2~12 组可配置太阳能电池翼（4 种电池技术），峰值可达 ~2500kW |
| **散热** | 2~10 块可配置辐射散热板（3 种冷却剂），可变热导热管 (VCHP) |
| **计算** | 5120 块 NVIDIA H100 GPU，~12.8 ExaFLOPS |
| **储能** | 1.4 MWh 锂电池组 |
| **数字孪生** | 7 项实时可调参数 + 实时趋势图 + 卫星外观动态跟随 |

### 技术栈

- **HTML5**: 页面结构 (`index.html`)
- **CSS3**: 独立样式文件 (`css/styles.css`)，暗色太空主题 UI、CSS Grid/Flexbox 布局、CSS 变量
- **JavaScript (ES6+)**: 12 个功能模块 (`js/*.js`)，模拟逻辑、Canvas 2D 绘制、requestAnimationFrame 动画循环
- **外部字体**: Google Fonts (Orbitron, Share Tech Mono, Exo 2)

---

## 2. 文件结构总览

项目采用模块化架构，主入口为 `index.html`，样式和逻辑分别拆分到独立文件：

```
SpaceDC/
├── index.html                          — 主入口 HTML（纯结构，不含 CSS/JS 代码）
├── css/
│   └── styles.css                      — 全部 CSS 样式（~190 行）
├── js/
│   ├── constants.js                    — 轨道常数、电池技术库、冷却剂数据库
│   ├── state.js                        — 仿真状态变量、动态数据模型、趋势缓冲区
│   ├── telemetry.js                    — 遥测日志系统（LOGS, addLog, p2）
│   ├── starfield.js                    — 星空背景层（initStars, drawStars）
│   ├── canvas.js                       — Canvas 引用、resizeAll、角度/食判断工具
│   ├── satellite.js                    — 卫星图标 drawSatIcon() + 详情标注 drawDetail()
│   ├── orbit.js                        — 地球轨道视图 drawOrbit()
│   ├── solar-array.js                  — 太阳能阵列 Canvas + 翼板状态表
│   ├── radiator.js                     — 散热器 Canvas + 面板状态表
│   ├── trend-chart.js                  — 实时趋势图 drawTrend()
│   ├── dt-controls.js                  — Digital Twin 控制面板事件处理
│   └── simulation.js                   — 主循环 update()、setSpeed()、animate()、初始化
└── SpaceDC_Simulator_Documentation.md  — 本文档
```

### 模块加载顺序

`index.html` 底部按依赖顺序引入 12 个 JS 模块：

```html
<script src="js/constants.js"></script>     <!-- 1. 常量（无依赖） -->
<script src="js/state.js"></script>         <!-- 2. 状态（依赖 constants） -->
<script src="js/telemetry.js"></script>     <!-- 3. 日志（依赖 state） -->
<script src="js/starfield.js"></script>     <!-- 4. 星空（独立） -->
<script src="js/canvas.js"></script>        <!-- 5. Canvas 工具（依赖 constants） -->
<script src="js/satellite.js"></script>     <!-- 6. 卫星绘制（依赖 state, canvas） -->
<script src="js/orbit.js"></script>         <!-- 7. 轨道视图（依赖 satellite, canvas, state） -->
<script src="js/solar-array.js"></script>   <!-- 8. 太阳能（依赖 state, canvas, constants） -->
<script src="js/radiator.js"></script>      <!-- 9. 散热器（依赖 state, canvas, constants） -->
<script src="js/trend-chart.js"></script>   <!-- 10. 趋势图（依赖 state, canvas, constants） -->
<script src="js/dt-controls.js"></script>   <!-- 11. DT控制（依赖 state, constants, telemetry） -->
<script src="js/simulation.js"></script>    <!-- 12. 主循环（依赖以上所有模块） -->
```

所有模块通过全局作用域共享状态，无需打包工具。

---

## 3. HTML 结构详解

### 3.1 文档头部 `<head>`

```html
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ORBITAL DC-1 · Space Data Center Simulator · Digital Twin</title>
<link rel="stylesheet" href="css/styles.css">
```

- **字符编码**: UTF-8，支持希腊字母 (ε, σ, Δ) 等特殊字符
- **视口设置**: `width=device-width, initial-scale=1.0`，确保在不同屏幕尺寸下正确渲染
- **标题**: 显示在浏览器标签页
- **样式**: 通过外部 CSS 文件引入 (`css/styles.css`)

**外部字体引入** (在 `css/styles.css` 内):
```css
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@400;700;900&family=Exo+2:wght@300;400;600&display=swap');
```
引入三种 Google 字体，用于营造太空科幻界面风格。

---

### 3.2 星空背景画布 `#starfield`

```html
<canvas id="starfield"></canvas>
```

一个全屏 `<canvas>` 元素，通过 CSS 固定在页面底层 (`position:fixed; z-index:0`)，用 JavaScript 绘制 400 颗闪烁的星星作为动态背景，营造太空氛围。`pointer-events:none` 确保它不拦截任何鼠标事件。

---

### 3.3 顶部导航栏 `.header`

```
┌──────────────────────────────────────────────────────────────┐
│ ORBITAL·DC·1  1MW SPACE DATA CENTER...  │ MET │ Orbit │ ... │
└──────────────────────────────────────────────────────────────┘
```

**左侧**: 系统标识 Logo `ORBITAL·DC·1` 及描述信息  
**右侧**: 一行关键指标 (`hdr-stats`)，包含:

| 指标ID | 标签 | 含义 | 初始值 |
|--------|------|------|--------|
| `#met` | MET | Mission Elapsed Time，任务已运行时间 | `T+000:00:00` |
| `#orbitNum` | Orbit | 当前第几圈轨道 | `1` |
| `#hSolar` | Solar | 太阳能阵列当前输出功率 | `1400kW` |
| `#hRad` | Radiator | 辐射散热器当前散热功率 | `400kW` |
| `#hBat` | Bat SOC | 电池荷电状态 (State of Charge) | `87%` |
| `#hGpuT` | GPU Temp | GPU 平均温度 | `84°C` |
| `#sysStatus` | Status | 系统状态指示 (带闪烁动画) | `● NOMINAL` |

`#sysStatus` 使用 CSS `blink` 动画，每 1.2 秒闪烁一次。

---

### 3.4 主布局 `.outer`

```css
.outer { display: flex; height: calc(100vh - 46px); }
```

顶层采用 **Flexbox** 布局，左侧 `.left-main` 自适应填满（`flex:1`），右侧 `.rsidebar` 固定宽度 270px。

---

### 3.5 左侧内容区 `.left-main`

```css
.left-main { display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr 160px; }
```

使用 **CSS Grid** 将左侧分为 3 行：上方 2×2 四象限 + 底部趋势图（跨两列，160px 高）：

#### Q1: 轨道模拟 (左上)

```html
<div class="quad">
  <div class="qlabel">SUN-SYNCHRONOUS ORBIT · 550 km · i=97.6°</div>
  <canvas id="orbitCanvas"></canvas>
</div>
```

- **功能**: 用 Canvas 实时绘制地球、太阳、轨道路径、卫星位置、食影区域
- **标签**: 浮动在左上角，显示轨道类型和参数
- Canvas 通过 CSS `position:absolute` 填满整个象限

#### Q2: 航天器详情 (右上)

```html
<div class="quad">
  <div class="qlabel">SPACECRAFT DETAIL · SOLAR PANELS + RADIATORS</div>
  <canvas id="detailCanvas"></canvas>
</div>
```

- **功能**: 放大展示航天器结构，标注太阳能翼、散热器、机体等部件的详细参数
- 展示方式随日照/食模式切换

#### Q3: 太阳能阵列 (左下)

```html
<div class="quad">
  <div class="pane-bar">...</div>           <!-- 顶部信息条 -->
  <div class="solar-canvas-wrap">
    <canvas id="solarArrayCanvas"></canvas>  <!-- 阵列可视化 -->
  </div>
  <div class="spec-panel">...</div>          <!-- 右侧规格面板 -->
</div>
```

**三部分组成**:

1. **顶部信息条** (`.pane-bar`):
   | 字段ID | 含义 |
   |--------|------|
   | `#phSolarOut` | 当前总输出功率 |
   | `#phIrr` | 太阳辐照度 (W/m²) |
   | `#phArrTemp` | 阵列温度 |
   | `#phEff` | 电池效率 |

2. **Canvas 区域** (`.solar-canvas-wrap`): 绘制 8 个太阳能翼 (4×2 网格)，每翼含模拟的太阳能电池格子

3. **规格面板** (`.spec-panel`):
   - `#wingTable`: 8 翼实时状态表 (翼名、功率kW、温度°C、状态)
   - 电池技术参数表:

     | 参数 | 值 |
     |------|------|
     | Type | TJ InGaP/GaAs/Ge (三结砷化镓) |
     | BOL Eff | 32.0% (寿命初期效率) |
     | EOL Eff | 28.8% (寿命末期效率) |
     | Voc | 2.67V/cell (开路电压) |
     | T-coef | -0.20%/°C (温度系数) |
     | RadTol | 1e15 e/cm² (辐射耐受) |
     | Total A | 2800 m² (总面积) |

#### Q4: 辐射散热器 (右下)

```html
<div class="quad">
  <div class="pane-bar">...</div>           <!-- 顶部信息条 -->
  <div class="rad-canvas-wrap">
    <canvas id="radiatorCanvas"></canvas>    <!-- 散热器可视化 -->
  </div>
  <div class="spec-panel">...</div>          <!-- 右侧规格面板 -->
</div>
```

**三部分组成**:

1. **顶部信息条** (`.pane-bar`):
   | 字段ID | 含义 |
   |--------|------|
   | `#phQrad` | 散热功率 (kW) |
   | `#phTsurf` | 平均表面温度 |
   | `#phDeltaT` | 进出口温差 |
   | ε=0.92 | 发射率 (固定标签) |

2. **Canvas 区域**: 绘制 6 块散热板，含热管可视化和红外辐射效果

3. **规格面板**:
   - `#radPanelTable`: 6 板实时状态表
   - 冷却架构参数表:

     | 参数 | 值 |
     |------|------|
     | Fluid | NH₃ 2-phase (氨两相流) |
     | Type | VCHP (可变热导热管) |
     | Area | 860 m² |
     | Flow | 4.2 kg/s |
     | T_in / T_out | 85°C / 45°C (动态更新) |
     | TIM | Liq.Metal (液态金属导热介质) |
     | T_sink | 2.7 K (深空温度) |
     | Law | Q=ε·σ·A·T⁴ (Stefan-Boltzmann 定律) |

---

### 3.6 右侧边栏 `.rsidebar`

右侧固定 250px 宽度的信息面板，由多个 `.psec` 节区组成：

#### 3.6.1 轨道阶段 (Orbital Phase)

```html
<div id="phaseBox" class="phase-box phase-sunlit">
  <div class="ph-icon" id="phIcon">☀️</div>
  <div>
    <div class="ph-name" id="phName">SUNLIT PASS</div>
    <div class="ph-desc" id="phDesc">Solar arrays 1400 kW</div>
  </div>
</div>
```

- **日照段**: 黄色主题框 `phase-sunlit`，显示 ☀️ 图标
- **食段**: 蓝色主题框 `phase-eclipse`，显示 🌑 图标
- **日照/食比例条**: 硬编码 64%:36% 的彩色条，分别为暖黄色和深蓝色
- **计时器** (`#phTimer`): 显示当前阶段已持续时间（MM:SS 格式）

#### 3.6.2 电力系统 (Power System)

**2×2 指标网格** (`.mgrid`):

| 指标 | 元素ID | 含义 | 进度条颜色 |
|------|--------|------|------------|
| Solar | `#rSolar` / `#rSolarBar` | 太阳能功率 (kW) | 黄→橙渐变 |
| Bat SOC | `#rBat` / `#rBatBar` | 电池荷电状态 (%) | 绿→青渐变 (低电量时红→橙) |
| Radiator | `#rRadP` / `#rRadBar` | 散热功率 (kW) | 红→橙渐变 |
| PUE | — | 能源使用效率，固定 1.08 | 绿色 |

**能量流列表** (`.frow`):

| 行 | CSS 类 | 元素ID | 含义 |
|----|--------|--------|------|
| ☀ Solar Arrays | `.sol` | `#ffSolar` | 太阳能输入 (+1400kW 或 0kW) |
| ⚡ Battery 1.4MWh | `.bat` | `#ffBat` | 电池充/放电状态 |
| 🖥 H100 × 5120 | `.cmp` | — | GPU 计算耗电 (固定 −1000 kW) |
| 🌡 Radiator Panels | `.rad2` | `#ffRad` | 散热消耗 |

#### 3.6.3 计算系统 (Compute)

**2×2 指标网格**:

| 指标 | 元素ID | 含义 |
|------|--------|------|
| FLOPS | `#rFlops` / `#rFlopsBar` | 浮点运算性能 (ExaFLOPS) |
| GPU Util | `#rGpu` / `#rGpuBar` | GPU 利用率 (%) |
| GPU Temp | `#rGpuT` / `#rGpuTBar` | GPU 温度 (°C) |
| Downlink | — | 下行数据带宽 (固定 12 Gbps) |

#### 3.6.4 模拟控制 (Simulation Control)

```html
<div class="spctrl">
  <button class="spbtn" onclick="setSpeed(1)">1×</button>
  <button class="spbtn active" onclick="setSpeed(60)">60×</button>
  <button class="spbtn" onclick="setSpeed(300)">300×</button>
  <button class="spbtn" onclick="setSpeed(600)">600×</button>
</div>
```

4 个按钮控制模拟时间加速倍率:
- **1×**: 实时
- **60×**: 默认，1 秒 ≈ 1 分钟
- **300×**: 1 秒 ≈ 5 分钟
- **600×**: 1 秒 ≈ 10 分钟

#### 3.6.5 任务成本 (Mission Cost)

静态表格，列出各子系统成本：

| 组件 | 成本 |
|------|------|
| 🚀 Launch (Starship) | $120M |
| 🛰 Spacecraft Bus | $85M |
| ☀ Solar Arrays TJ | $65M |
| ⚡ Battery 1.4MWh | $42M |
| 🌡 Radiator+VCHP | $28M |
| 🖥 H100×5120 | $256M |
| 📡 Optical Downlink | $38M |
| 🔧 Ground Segment | $22M |
| 🛠 AIT | $45M |
| 📋 Insurance | $80M |
| **TOTAL CAPEX** | **$781M** |
| OPEX/yr | $38M |
| Revenue | ~$420M/yr |
| **Break-even** | **~4.2 yrs** |

#### 3.6.6 遥测日志 (Telemetry Log)

```html
<div class="tlog" id="telemLog">
  <div class="ok">[BOOT] ORBITAL DC-1 nominal.</div>
  ...
</div>
```

- 一个可滚动的日志区域，最大保留 60 条记录
- 日志条目有三种样式: `.ok` (绿色)、`.info` (青色)、`.warn` (黄色)
- 启动时显示 5 条初始日志
- 运行中每 ~85 秒模拟时间自动添加预设的遥测消息

---

### 3.7 底部状态栏 `.botbar`

```
┌──────────────────────────────────────────────────────────────────────┐
│ VEL 7.61km/s │ ALT 550km │ PERIOD 95.7min │ INCL 97.6° │ RAAN │...│
└──────────────────────────────────────────────────────────────────────┘
```

固定在页面底部 (`position:fixed`)，显示轨道力学参数：

| 参数 | 元素ID | 含义 | 动态/静态 |
|------|--------|------|-----------|
| VEL | — | 轨道速度 7.61 km/s | 静态 |
| ALT | — | 轨道高度 550 km | 静态 |
| PERIOD | — | 轨道周期 95.7 min | 静态 |
| INCL | — | 轨道倾角 97.6° | 静态 |
| RAAN | `#bbRaan` | 升交点赤经 | 动态 (每日进动 0.9856°) |
| TA | `#bbTa` | 真近点角 | 动态 |
| SUN β | `#bbSun` | 太阳 β 角 | 动态 (微小振荡) |
| ENERGY | `#bbEnergy` | 电池存储能量 (kWh) | 动态 |
| ORBIT | `#bbOrbit` | 当前轨道圈数 | 动态 |

---

## 4. CSS 样式系统详解

### 4.1 CSS 变量 (Design Tokens)

```css
:root {
  --void:   #020408;   /* 最深背景色 (几乎纯黑) */
  --deep:   #050d1a;   /* 深色面板背景 */
  --panel:  #080f1e;   /* 面板/卡片背景 */
  --border: #0d2040;   /* 边框颜色 (深蓝灰) */
  --accent: #00d4ff;   /* 主强调色 (亮青) */
  --accent2:#ff6b00;   /* 第二强调色 (橙) */
  --accent3:#39ff14;   /* 第三强调色 (亮绿) */
  --warn:   #ffcc00;   /* 警告色 (黄) */
  --danger: #ff2244;   /* 危险色 (红) */
  --text:   #a8d8f0;   /* 主文本颜色 (浅蓝) */
  --dim:    #3a5a7a;   /* 次要文本/标签色 (暗蓝灰) */
  --solar:  #ffe066;   /* 太阳能主题色 (暖黄) */
  --rad:    #ff4400;   /* 辐射散热主题色 (橙红) */
}
```

整套配色方案模拟航天任务控制中心的暗色 UI 风格。

### 4.2 字体系统

| 字体 | 用途 | 风格 |
|------|------|------|
| **Orbitron** | 标题、标签、系统名称 | 几何无衬线，科幻感 |
| **Share Tech Mono** | 数据、数值、遥测信息 | 等宽字体，技术感 |
| **Exo 2** | 正文默认字体 | 现代几何无衬线 |

### 4.3 布局系统

整体布局层级:

```
body (overflow:hidden, 100vh)
├── #starfield (fixed, z-index:0) — 星空 Canvas
├── .header (z-index:10, 46px高) — 顶栏
│   └── flex 布局: logo ←→ hdr-stats
├── .outer (z-index:5, calc(100vh-46px))
│   └── flex 布局:
│       ├── .left-main (flex:1, Grid 2col × 3row)
│       │   ├── 4个 .quad (position:relative) — 2×2 象限
│       │   └── .trend-pane (grid-column:1/3) — 趋势图
│       └── .rsidebar (width:270px, flex列)
└── .botbar (fixed, z-index:20) — 底栏
```

关键布局特性:
- **全屏无滚动**: `body { overflow:hidden; height:100vh }`
- **2×2 象限 + 趋势行**: CSS Grid `1fr 1fr / 1fr 1fr 160px`，间距为 0
- **趋势图**: `.trend-pane` 使用 `grid-column: 1/3` 跨两列
- **太阳能/散热器象限**: 特殊三栏布局 — 顶部条(26px) + 左Canvas + 右面板(160px)

### 4.4 组件样式

#### 指标卡片 `.mg`

```css
.mg { background: var(--panel); border: 1px solid var(--border); border-radius: 3px; padding: 5px; }
```

每个卡片包含:
- `.mg-l`: 标签 (7px, 暗灰, 大写)
- `.mg-v`: 数值 (12px, 粗体, 亮青)
- `.mg-u`: 单位 (7px, 暗灰)
- `.mbar` / `.mfill`: 进度条 (2px 高, 带颜色渐变和过渡动画)

#### 能量流行 `.frow`

```css
.frow { border-left: 2px solid var(--dim); }
.frow.sol { border-left-color: var(--solar); }    /* 太阳能 — 暖黄 */
.frow.bat { border-left-color: var(--accent2); }   /* 电池 — 橙 */
.frow.cmp { border-left-color: var(--accent); }    /* 计算 — 青 */
.frow.rad2{ border-left-color: var(--rad); }        /* 散热 — 红 */
```

左侧色带用于视觉区分不同能量流向。

#### 数据表格 `.ctab` & `.cell-t`

两种表格样式:
- `.ctab`: 成本表格，较宽松的 padding
- `.cell-t`: 电池/散热板状态表格，紧凑型 (6-7px 字体)

#### 阶段指示框 `.phase-box`

```css
.phase-sunlit { background: rgba(255,224,0,0.04); border-color: rgba(255,224,0,0.2); }
.phase-eclipse { background: rgba(0,80,180,0.08); border-color: rgba(0,80,180,0.25); }
```

根据日照/食状态动态切换背景和边框颜色。

### 4.5 动画

```css
@keyframes blink {
  0%, 100% { opacity: 1 }
  50%      { opacity: 0.3 }
}
.blink { animation: blink 1.2s infinite; }
```

唯一的 CSS 动画，用于系统状态指示灯的闪烁效果。其余所有动画效果均通过 JavaScript + Canvas 实现。

---

## 5. JavaScript 逻辑详解

> **模块化架构**: JavaScript 代码已从单个 `<script>` 块拆分为 12 个独立模块文件 (`js/*.js`)。以下各节按功能描述逻辑，并标注对应的源文件。完整的模块依赖关系和加载顺序见 [Section 20](#20-模块化架构说明)。

### 5.1 全局状态变量

> **源文件**: `js/state.js`

```javascript
let simTime    = 0;      // 模拟总时间 (秒)，持续累加
let speed      = 60;     // 时间加速倍率，默认 60×
let metSeconds = 0;      // MET 秒数 (Mission Elapsed Time)
let orbitCount = 1;      // 当前轨道圈数
let batSOC     = 87;     // 电池荷电状态 (%)，初始 87%
let phaseTime  = 0;      // 当前阶段 (日照/食) 已持续时间
let lastTime   = null;   // 上一帧时间戳 (performance.now)
let logIdx     = 0;      // 遥测日志索引
let logTimer   = 0;      // 日志定时器计数器
```

**常量**:

```javascript
const ORBIT_PERIOD  = 95.7 * 60;                           // 轨道周期 = 5742 秒
const ECLIPSE_FRAC  = 0.36;                                 // 食占比 36%
const ECLIPSE_START = Math.PI * (1 - ECLIPSE_FRAC);         // 食起始角 ≈ 2.011 弧度 (≈115.2°)
const SIGMA         = 5.67e-8;                               // Stefan-Boltzmann 常数 (W/m²·K⁴)
```

**食的角度范围**:  
食起始角 = $\pi \times (1 - 0.36) = \pi \times 0.64 \approx 2.011$ rad  
食结束角 = 食起始角 + $0.36 \times 2\pi \approx 2.011 + 2.262 \approx 4.273$ rad

---

### 5.2 数据模型 (Wings & Radiator Panels)

> **源文件**: `js/state.js` — `rebuildWings()` / `rebuildRadPanels()`

#### 太阳能翼 `wings`

```javascript
const wings = Array.from({length:8}, (_, i) => ({
  id:         i + 1,                              // 翼编号 1~8
  name:       `W${String.fromCharCode(65 + i)}`,  // 翼名: WA, WB, WC, ... WH
  cells:      240,                                 // 每翼电池数量
  area:       350,                                 // 每翼面积 (m²)
  temp:       65 + Math.random() * 10,             // 初始温度 65~75°C (随机)
  efficiency: 0.295 + (Math.random()-0.5) * 0.005, // 初始效率 29.25~29.75%
  output:     0                                    // 当前输出功率 (kW)，运行时计算
}));
```

- 8 翼总面积: 8 × 350 = 2800 m²
- 8 翼总电池: 8 × 240 = 1920 cells
- 命名规则: WA ~ WH

#### 散热板 `radPanels`

```javascript
const radPanels = Array.from({length:6}, (_, i) => ({
  id:         i + 1,                         // 板编号 1~6
  area:       143.3,                         // 每板面积 (m²)，6板总计 ≈ 860 m²
  surfTemp:   55 + Math.random() * 8,        // 初始表面温度 55~63°C
  emissivity: 0.92,                          // 发射率
  viewFactor: 0.85 + Math.random() * 0.1,    // 视角因子 0.85~0.95
  qRad:       0                              // 当前散热功率 (kW)，运行时计算
}));
```

- 6 板总面积: 6 × 143.3 ≈ 860 m²
- 视角因子 (View Factor) 模拟散热板对深空的可视比例

---

### 5.3 星空渲染 (Starfield)

> **源文件**: `js/starfield.js`

#### `initStars()`

```javascript
function initStars() {
  sfC.width  = window.innerWidth;
  sfC.height = window.innerHeight;
  stars = Array.from({length: 400}, () => ({
    x:  Math.random() * sfC.width,    // X 位置 (随机)
    y:  Math.random() * sfC.height,   // Y 位置 (随机)
    r:  Math.random() * 1.2,          // 半径 0~1.2px
    a:  Math.random(),                // 动画相位 (初始随机)
    sp: Math.random() * 0.25 + 0.05   // 闪烁速度
  }));
}
```

- 生成 400 颗星星，位置和大小随机分布
- 窗口 resize 时会重新生成

#### `drawStars()`

```javascript
function drawStars() {
  sfX.clearRect(0, 0, sfC.width, sfC.height);
  stars.forEach(s => {
    s.a += s.sp * 0.008;  // 相位递增 → 闪烁
    sfX.beginPath();
    sfX.arc(s.x, s.y, s.r, 0, Math.PI * 2);
    sfX.fillStyle = `rgba(180,220,255,${0.25 + 0.6 * Math.abs(Math.sin(s.a))})`;
    sfX.fill();
  });
}
```

- 每帧更新每颗星星的透明度，通过 `sin(a)` 产生平滑的闪烁效果
- 透明度范围: 0.25 ~ 0.85 (从不完全消失)
- 颜色: 冷白蓝色 `rgba(180,220,255,...)`

---

### 5.4 Canvas 引用与初始化

> **源文件**: `js/canvas.js`

```javascript
const oC = document.getElementById('orbitCanvas'),   oX = oC.getContext('2d');  // 轨道
const dC = document.getElementById('detailCanvas'),  dX = dC.getContext('2d');  // 详情
const sC = document.getElementById('solarArrayCanvas'), sX = sC.getContext('2d');  // 太阳能
const rC = document.getElementById('radiatorCanvas'), rX = rC.getContext('2d');  // 散热
```

#### `resizeAll()`

```javascript
function resizeAll() {
  [oC, dC].forEach(c => {
    if (c.offsetWidth > 0 && c.offsetHeight > 0) {
      c.width  = c.offsetWidth;
      c.height = c.offsetHeight;
    }
  });
  [sC, rC].forEach(c => {
    if (c.offsetWidth > 0 && c.offsetHeight > 0) {
      c.width  = c.offsetWidth;
      c.height = c.offsetHeight;
    }
  });
}
```

- 每帧调用，确保 Canvas 内部分辨率匹配 CSS 布局尺寸
- 只在有实际尺寸时更新，避免 0×0 的情况

---

### 5.5 轨道判断工具函数

> **源文件**: `js/canvas.js` — `getAngle()` / `isEclipse()`

#### `getAngle(t)`

```javascript
function getAngle(t) {
  return (t / ORBIT_PERIOD) * Math.PI * 2;
}
```

将模拟时间 `t` (秒) 转换为轨道角度 (弧度)。  
公式: $\theta = \frac{t}{T_{orbit}} \times 2\pi$

#### `isEclipse(a)`

```javascript
function isEclipse(a) {
  const n = ((a % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);  // 归一化到 [0, 2π)
  return n > ECLIPSE_START && n < ECLIPSE_START + ECLIPSE_FRAC * Math.PI * 2;
}
```

判断给定轨道角度 `a` 是否处于地球阴影 (食) 中:
- 先将角度归一化到 $[0, 2\pi)$
- 食区间: $[\pi(1 - f_{eclipse}), \; \pi(1 - f_{eclipse}) + 2\pi \cdot f_{eclipse}]$
- 即 $[2.011, \; 4.273]$ 弧度

---

### 5.6 轨道视图绘制 `drawOrbit()`

> **源文件**: `js/orbit.js`

这是最复杂的绘制函数，逐步绘制以下元素：

#### 5.6.1 背景辉光

```javascript
const bg = oX.createRadialGradient(cx, cy, 0, cx, cy, W * 0.7);
bg.addColorStop(0, 'rgba(0,18,50,0.35)');
bg.addColorStop(1, 'rgba(0,0,0,0)');
```

以地球中心为原点的径向渐变，模拟微弱的太空环境光。

#### 5.6.2 太阳

- **位置**: 轨道左上方 (`cx - orbitR*1.85`, `cy - orbitR*0.65`)
- **辉光**: 四层径向渐变 (白→黄→橙→透明)
- **核心**: 22px 半径的黄白色实心圆
- **光芒**: 14 条旋转射线 (长度随时间 `sin(simTime)` 脉动)

#### 5.6.3 太阳光线 (日照时)

在非食期间，从太阳方向到卫星位置绘制 5 条平行虚线，表示太阳辐照：

```javascript
for (let j = 0; j < 5; j++) {
  // 平行偏移虚线
  oX.setLineDash([3, 5]);
  // 从太阳 23% 处画到 73% 处
}
```

#### 5.6.4 地球阴影锥

```javascript
const shAng = Math.atan2(cy - sunY, cx - sunX);
// 绘制扇形阴影 + 径向渐变 (深蓝→透明)
```

以太阳→地球方向计算阴影角度，绘制梯度阴影锥。

#### 5.6.5 轨道路径

```javascript
oX.arc(cx, cy, orbitR, 0, Math.PI * 2);
oX.setLineDash([5, 7]);
```

蓝色虚线圆环，表示圆轨道。

#### 5.6.6 地球

三层渲染:
1. **地球球体**: 径向渐变 (绿→蓝→深蓝→黑)
2. **大气层**: 额外的蓝色辉光环
3. **文字标签**: "EARTH" 居中

#### 5.6.7 地面轨迹尾迹

```javascript
for (let i = 1; i <= 3; i++) {
  const ta = getAngle(simTime - i * ORBIT_PERIOD * 0.07);
  oX.arc(cx, cy, orbitR, ta, ta + 0.22, false);
}
```

绘制卫星过去位置的 3 段淡蓝弧线，制造运动拖尾效果。

#### 5.6.8 卫星

- **辉光** (日照时): 35px 半径的青色径向辉光
- **图标**: 调用 `drawSatIcon()` (详见 5.7)
- **下行链路光束**: 随机概率绘制卫星→地面站的绿色虚线

#### 5.6.9 标签

- 卫星旁边显示 "● ECLIPSE" 或 "☀ SUNLIT"
- 轨道旁显示 "SSO 550km T=95.7min"
- 地球下方显示 "ORBIT #N"

---

### 5.7 卫星图标绘制 `drawSatIcon()`

> **源文件**: `js/satellite.js`

```javascript
function drawSatIcon(ctx, x, y, angle, eclipse, s) { ... }
```

**参数**:
- `ctx`: Canvas 2D 上下文
- `x, y`: 绘制中心位置
- `angle`: 旋转角度 (卫星始终面向运动方向)
- `eclipse`: 是否在食中
- `s`: 缩放比例

**绘制内容** (从外到内):

1. **太阳能翼** (两侧对称):
   - 矩形翼面 (`wingW × wingH`)，缩放后尺寸 = `52s × 14s`
   - 8×2 太阳能电池格子
   - 日照时: 深蓝绿色 + 随机亮度模拟光伏效应
   - 食时: 深灰蓝色
   - 连接臂: `#334455` 灰色矩形

2. **主体 (Bus)**:
   - 矩形 (`12s × 14s`)
   - 日照时: 金色 + 青色发光
   - 食时: 深蓝灰色
   - 内部网格线模拟多层隔热结构

3. **散热器** (两侧对称，位于主体旁):
   - 矩形 (`8s × 20s`)
   - 日照时: 红→橙→深红渐变 (热辐射视觉)
   - 食时: 暗红色
   - 6 条水平线模拟热管
   - 4 条散热射线 (虚线，脉动透明度)

4. **天线**:
   - 灰色小圆 + 竖杆

---

### 5.8 航天器详情视图 `drawDetail()`

> **源文件**: `js/satellite.js`

```javascript
function drawDetail(eclipse) { ... }
```

在 `detailCanvas` 上以放大比例展示航天器，附带注释和标注线。

**绘制内容**:

1. **背景**: 深蓝径向渐变
2. **标题**: "SPACECRAFT DETAIL · ORBITAL DC-1" + 状态描述
3. **放大卫星图标**: 调用 `drawSatIcon()`，缩放因子 `sc = min(W,H) * 0.0035`
4. **左侧太阳翼标注** (WING-A):
   - 技术参数: InGaP/GaAs/Ge TJ
   - 面积: 350m², 240 cells
   - 输出: ~175 kW (日照) 或 0 kW (食)
   - 虚线连接到翼面
5. **右侧太阳翼标注** (WING-B): 与左侧对称
6. **散热器标注**:
   - 冷却介质: NH₃ 2-phase VCHP
   - 发射率: ε=0.92
   - 散热公式: Q = ε·σ·A·(T⁴−T_space⁴)
7. **底部机体标注**: 5120×H100, MLI blanket, GPU温度
8. **太阳辐照箭头** (日照时): 双向指向太阳翼的虚线箭头 + "1367 W/m²" 标签
9. **红外辐射箭头**: 从散热器向外的脉动红色箭头

---

### 5.9 太阳能阵列视图 `drawSolarArray()`

> **源文件**: `js/solar-array.js`

```javascript
function drawSolarArray(eclipse) { ... }
```

在 `solarArrayCanvas` 上绘制 8 翼太阳能阵列的详细视图。

**布局**: 4列×2行 网格

**每翼绘制**:

1. **翼面背景**: 渐变色，亮度随输出功率标准化值变化
2. **电池格子**: 6列×4行 = 24 个可视电池单元
   - 日照时: 绿色系 + 随机抖动模拟光伏闪烁
   - 食时: 极暗色
   - 顶部行有微弱的高光线模拟反射
3. **翼边框**: 日照时有黄色发光阴影
4. **翼名标签**: 左下角 (WA~WH)
5. **功率标签**: 左下角 (如 "175kW")
6. **温度指示点**: 右上角彩色圆点
   - 颜色从绿(冷)到红(热)连续变化

**底部功率总条**: 显示总发电量占 1400kW 的比例，彩色渐变 (绿→黄→红)。

---

### 5.10 辐射散热器视图 `drawRadiator()`

> **源文件**: `js/radiator.js`

```javascript
function drawRadiator(eclipse) { ... }
```

在 `radiatorCanvas` 上绘制 6 块散热板的详细视图。

**布局**: 6 块并排排列

**每板绘制**:

1. **板面背景**: 垂直渐变 (红→橙→深红→暗红)
2. **热管线条**: 10 条水平线
   - 颜色强度从上到下递减 (模拟热流方向)
   - 每隔一条有向下的小三角箭头指示热流方向
3. **红外辐射线** (日照时): 左侧 3 层虚线，透明度递减，模拟向深空辐射
4. **板边框**: 橙红色 + 发光阴影
5. **面板编号**: 顶部 (P1~P6)
6. **温度**: 底部显示 `XX°C`
7. **功率**: 最底部显示 `XXkW`

**底部标注**:
- 左侧: "← IR to deep space (2.7K)"
- 右侧: "NH₃: 85°C in → 45°C out"

---

### 5.11 表格数据更新

> **源文件**: `js/solar-array.js` (`updateWingTable`) + `js/radiator.js` (`updateRadTable`)

#### `updateWingTable(eclipse)`

每帧更新 `#wingTable`，计算每翼:

**输出功率**:
$$P_{wing} = \frac{A \times G_{sc} \times \eta}{1000} \times [1 - (T - 25) \times 0.002]$$

其中:
- $A$ = 350 m² (翼面积)
- $G_{sc}$ = 1367 W/m² (太阳常数)
- $\eta$ ≈ 0.295 (转换效率)
- $T$ = 翼温度 (°C)
- 0.002 = 温度降额系数 (%/°C)

食期间: $P_{wing} = 0$

**温度变化**:
- 食期间: $T \leftarrow \max(-65, T - 1.4)$（逐步降至 -65°C）
- 日照期间: $T \leftarrow \min(84, T + 0.35)$（逐步升至 84°C）

**状态指示**:
- 温度 > 80°C: 红色 (`.ht`)
- 温度 > 70°C: 黄色 (`.wn`)
- 其他: 绿色 (`.ok`)
- 运行模式: `ACT` (日照) / `STB` (食，待机)

#### `updateRadTable(eclipse)`

每帧更新 `#radPanelTable`，计算每板:

**表面温度变化**:
- 食期间: $T_{surf} \leftarrow \max(14, T_{surf} - 0.5)$
- 日照期间: $T_{surf} = 54 + \text{random}(0, 7)$°C

**散热功率** (Stefan-Boltzmann 定律):
$$Q_{rad} = \frac{\varepsilon \cdot \sigma \cdot A \cdot F_v \cdot (T^4 - T_{space}^4)}{1000}$$

其中:
- $\varepsilon$ = 0.92 (发射率)
- $\sigma$ = 5.67×10⁻⁸ W/m²·K⁴
- $A$ = 143.3 m²
- $F_v$ = 视角因子 (0.85~0.95)
- $T$ = 表面温度 (K) = $T_{surf}$ + 273.15
- $T_{space}$ = 2.7 K (宇宙微波背景辐射温度)

---

### 5.12 遥测日志系统

> **源文件**: `js/telemetry.js`

#### 预设日志列表 `LOGS`

```javascript
const LOGS = [
  ['ok',   'Solar tracking nominal. Sun angle <3°.'],
  ['info', 'Station-keeping ΔV=0.2m/s done.'],
  ['ok',   'GPU T=84°C. Cold plate ΔT=8°C.'],
  ['info', 'Downlink: Tokyo→Svalbard. 12Gbps.'],
  ['warn', 'Cosmic ray DIMM-07. ECC corrected.'],
  ['ok',   'BMS: 480 cells balanced. SOH=99.8%.'],
  ['info', 'LLM batch queued. 847 jobs pending.'],
  ['ok',   'ADCS 0.01° off-nadir. RWA OK.'],
  ['info', 'SSO dawn-dusk geometry. β=2.3°.'],
  ['ok',   'Laser: 12Gbps Tenerife. BER=1e-12.'],
  ['ok',   'VCHP conductance adj. post-eclipse.'],
  ['warn', 'Wing-D 82°C. Within TML.'],
  ['ok',   'Radiator P3 NH₃ 4.2kg/s nominal.'],
  ['info', 'Orbit decay +0.1km cold-gas thrust.'],
];
```

14 条预设遥测消息，循环播放。

#### `addLog(type, msg)`

```javascript
function addLog(type, msg) {
  // 创建带时间戳的日志条目
  // 格式: [HHH:MM:SS] 消息内容
  // 保留最多 60 条，自动滚动到底部
}
```

#### `p2(n)` — 辅助函数

```javascript
function p2(n) { return String(Math.floor(n)).padStart(2, '0'); }
```

将数字格式化为 2 位补零字符串 (如 `5` → `"05"`)。

---

### 5.13 主更新循环 `update()`

> **源文件**: `js/simulation.js`

这是模拟器的核心逻辑函数，每帧调用一次。

#### 5.13.1 时间推进

```javascript
if (!lastTime) lastTime = ts;
const dt = Math.min((ts - lastTime) / 1000, 0.1);  // 帧间隔 (秒)，最大 0.1s
lastTime = ts;

simTime    += dt * speed;   // 模拟时间 += 真实帧时间 × 加速倍率
metSeconds += dt * speed;   // MET 同步
phaseTime  += dt * speed;   // 阶段计时
```

- `dt` 被限制在 0.1 秒以内，防止浏览器标签页不活跃时突然跳跃
- 实际推进的模拟时间 = `dt × speed`

#### 5.13.2 轨道阶段判断

```javascript
const angle      = getAngle(simTime);
const eclipse    = isEclipse(angle);
const prevEclipse = isEclipse(getAngle(simTime - dt * speed));
```

同时计算当前帧和上一帧的食状态，用于检测阶段切换。

#### 5.13.3 轨道圈数和阶段切换

```javascript
const newOrbit = Math.floor(simTime / ORBIT_PERIOD) + 1;
if (newOrbit !== orbitCount) {
  orbitCount = newOrbit;
  addLog('info', `Orbit #${orbitCount} commenced.`);
}

if (eclipse !== prevEclipse) {
  phaseTime = 0;  // 阶段切换时重置计时器
  eclipse
    ? addLog('warn', 'Entering umbra. Battery discharge.')
    : addLog('ok', 'Exiting eclipse. Solar online.');
}
```

#### 5.13.4 电池 SOC 计算

```javascript
batSOC = eclipse
  ? Math.max(10,  batSOC - 0.85 * dt * speed / 60)   // 放电: 每分钟降 0.85%
  : Math.min(100, batSOC + 1.25 * dt * speed / 60);   // 充电: 每分钟升 1.25%
```

- **放电速率**: 0.85%/min，最低 10%
- **充电速率**: 1.25%/min，最高 100%

#### 5.13.5 自动遥测日志

```javascript
logTimer += dt * speed;
if (logTimer > 85) {  // 每 85 秒模拟时间
  logTimer = 0;
  const [t, m] = LOGS[logIdx % LOGS.length];
  addLog(t, m);
  logIdx++;
}
```

#### 5.13.6 传感器数据计算

```javascript
const solarPwr = eclipse ? 0 : 1400 * (0.97 + Math.random() * 0.03);
// 日照时 1358~1400 kW，添加 ±3% 随机波动

const radPwr = radPanels.reduce((a, p) => a + (eclipse ? p.qRad * 0.5 : p.qRad), 0);
// 总散热功率，食期间减半

const flops = eclipse ? 12.8 * (batSOC / 100) : 12.8 * (0.87 + Math.random() * 0.13);
// 算力随电池电量或随机波动

const gpu = eclipse ? Math.floor(72 * batSOC / 100) : Math.floor(88 + Math.random() * 10);
// GPU 利用率 (%)

const gpuTemp = eclipse ? 65 + batSOC * 0.18 : 76 + Math.random() * 9;
// GPU 温度 (°C)

const arrTemp = eclipse ? -55 + Math.random() * 5 : 62 + Math.random() * 16;
// 太阳能阵列温度

const radSurfT = radPanels.reduce((a, p) => a + p.surfTemp, 0) / radPanels.length;
// 散热板平均表面温度
```

#### 5.13.7 DOM 更新

函数随后更新所有 DOM 元素的文本/样式:

**阶段指示框**:
- CSS 类: `phase-sunlit` / `phase-eclipse`
- 图标: ☀️ / 🌑
- 名称: "SUNLIT PASS" / "ECLIPSE PASS"
- 描述: "Solar arrays 1400 kW" / "Bat XX% SOC — discharge"

**电力仪表**:
- 太阳能功率 + 进度条宽度
- 电池 SOC + 进度条 (低于 25% 变红)
- 散热功率 + 进度条

**能量流文本**:
- 太阳能: "+1400 kW" / "0 kW"
- 电池: "CHG +XXXkW" / "DIS −1000kW (XX%)"
- 散热: "−XXX kW"

**计算仪表**: FLOPS、GPU 利用率、GPU 温度

**面板头部**: 太阳能/散热器面板的输出数据

**顶部栏**: MET、轨道号、所有关键指标

**系统状态**:
```javascript
if (batSOC < 20)     → "▲ LOW BATTERY" (红色)
else if (eclipse)    → "◉ ECLIPSE MODE" (蓝色)
else                 → "● NOMINAL" (绿色)
```

**底部轨道参数**:
- **RAAN** (升交点赤经): $RAAN = (156.3 + \frac{t}{86400} \times 0.9856) \bmod 360$°
  - 每天进动约 0.9856°，模拟 SSO 的升交点进动
- **TA** (真近点角): $TA = (\theta \times 180 / \pi) \bmod 360$°
- **SUN β**: $\beta = 2.3 + 0.5 \times \sin(t \times 0.0001)$° (微小振荡)
- **ENERGY**: $E = SOC \times 14$ kWh (1.4 MWh 电池 × SOC%)

#### 5.13.8 Canvas 绘制

```javascript
drawOrbit(eclipse);
drawDetail(eclipse);
drawSolarArray(eclipse);
drawRadiator(eclipse);
```

每帧重绘所有四个 Canvas。

---

### 5.14 时间加速控制 `setSpeed()`

> **源文件**: `js/simulation.js`

```javascript
function setSpeed(s) {
  speed = s;
  document.querySelectorAll('.spbtn').forEach(b =>
    b.classList.toggle('active', b.textContent === s + '×')
  );
}
```

- 设置全局 `speed` 变量
- 更新按钮的 `.active` 样式

---

### 5.15 动画主循环 `animate()`

> **源文件**: `js/simulation.js`

```javascript
function animate(ts) {
  resizeAll();    // 更新 Canvas 尺寸
  drawStars();    // 绘制星空
  update(ts);     // 主逻辑 + 绘制四象限
  requestAnimationFrame(animate);  // 递归调度下一帧
}

window.addEventListener('resize', () => {
  initStars();   // 窗口大小变化时重新生成星空
  resizeAll();
});

initStars();                       // 初始化星空
resizeAll();                       // 初始化 Canvas 尺寸
requestAnimationFrame(animate);    // 启动动画循环
```

典型的 `requestAnimationFrame` 循环，通常以 60fps 运行。

---

### 5.16 趋势图 `drawTrend()`

> **源文件**: `js/trend-chart.js`

在底部 `trendCanvas` 上绘制四通道实时曲线（Solar / Battery / Radiator / GPU），详见 [Section 14](#14-功能-5实时趋势图-real-time-trend-chart)。

### 5.17 Digital Twin 控件 `setupDTControls()`

> **源文件**: `js/dt-controls.js`

在页面加载时绑定右侧边栏所有 DT 控件的事件监听器（滑块 `input`、下拉 `change`），并提供实时摘要更新 `updateDTSummary()`。详见 [Section 15](#15-digital-twin-控制面板交互总览)。

---

## 6. 物理模型与公式

### 6.1 轨道力学

| 参数 | 公式/值 |
|------|---------|
| 轨道类型 | 太阳同步轨道 (SSO) |
| 高度 | 550 km |
| 倾角 | 97.6° |
| 周期 | 95.7 min = 5742 s |
| 速度 | 7.61 km/s |
| 日照比 | 64% |
| 食比 | 36% |
| RAAN 进动 | ~0.9856°/day |
| 轨道角度 | $\theta(t) = \frac{2\pi t}{T_{orbit}}$ |
| 食判断 | $\theta \in [\pi(1-f_e), \; \pi(1-f_e) + 2\pi f_e]$ |

### 6.2 太阳能发电

$$P_{wing} = \frac{A \cdot G_{sc} \cdot \eta}{1000} \cdot [1 - (T - 25) \cdot \alpha_T]$$

| 符号 | 含义 | 值 |
|------|------|------|
| $A$ | 翼面积 | 350 m² |
| $G_{sc}$ | 太阳常数 | 1367 W/m² |
| $\eta$ | 转换效率 | ~29.5% |
| $T$ | 翼温度 | 可变 (°C) |
| $\alpha_T$ | 温度系数 | 0.002 /°C (即 0.2%/°C) |

### 6.3 辐射散热 (Stefan-Boltzmann)

$$Q_{rad} = \varepsilon \cdot \sigma \cdot A \cdot F_v \cdot (T_{surf}^4 - T_{space}^4)$$

| 符号 | 含义 | 值 |
|------|------|------|
| $\varepsilon$ | 发射率 | 0.92 |
| $\sigma$ | Stefan-Boltzmann 常数 | 5.67×10⁻⁸ W/m²·K⁴ |
| $A$ | 每板面积 | 143.3 m² |
| $F_v$ | 视角因子 | 0.85~0.95 |
| $T_{surf}$ | 表面温度 | ~55-63°C → 328-336 K |
| $T_{space}$ | 深空温度 | 2.7 K |

### 6.4 电池充放电

$$SOC_{new} = \begin{cases} \max(10, \; SOC - 0.85 \cdot \Delta t / 60) & \text{食期间 (放电)} \\ \min(100, \; SOC + 1.25 \cdot \Delta t / 60) & \text{日照期间 (充电)} \end{cases}$$

- 电池容量: 1.4 MWh
- 存储能量: $E = SOC \times 14$ kWh

---

## 7. 模拟参数一览表

### 航天器参数

| 参数 | 值 |
|------|------|
| 太阳能翼数量 | 8 翼 (WA~WH) |
| 每翼面积 | 350 m² |
| 每翼电池数 | 240 cells |
| 总太阳能面积 | 2800 m² |
| 电池类型 | InGaP/GaAs/Ge 三结 |
| BOL 效率 | 32.0% |
| EOL 效率 | 28.8% |
| 峰值发电 | ~1400 kW |
| 散热板数量 | 6 |
| 每板面积 | 143.3 m² |
| 总散热面积 | ~860 m² |
| 冷却剂 | 氨 (NH₃) 两相流 |
| 热管类型 | VCHP |
| 峰值散热 | ~400 kW |
| GPU 类型 | NVIDIA H100 |
| GPU 数量 | 5120 |
| 峰值算力 | 12.8 ExaFLOPS |
| 电池容量 | 1.4 MWh |
| 下行带宽 | 12 Gbps (激光通信) |
| PUE | 1.08 |

### 轨道参数

| 参数 | 值 |
|------|------|
| 轨道类型 | 太阳同步轨道 (SSO) |
| 高度 | 550 km |
| 倾角 | 97.6° |
| 周期 | 95.7 min |
| 轨道速度 | 7.61 km/s |
| 日照比 | 64% |
| 食比 | 36% |
| β 角 | ~2.3° |
| 初始 RAAN | 156.3° |

---

## 8. 交互功能说明

### 8.1 时间加速按钮

用户可点击右侧边栏的 4 个加速按钮:

| 按钮 | 倍率 | 体验效果 |
|------|------|----------|
| 1× | 实时 | 1 秒真实时间 = 1 秒模拟时间 |
| **60×** (默认) | 60倍 | 1 秒 ≈ 1 分钟，约 96 秒完成一圈 |
| 300× | 300倍 | 1 秒 ≈ 5 分钟，约 19 秒完成一圈 |
| 600× | 600倍 | 1 秒 ≈ 10 分钟，约 9.6 秒完成一圈 |

### 8.2 自动状态切换

模拟器会自动在**日照段**和**食段**之间切换，无需用户操作:

- **日照段进入时**: 太阳能阵列恢复发电、电池充电、GPU 满载运行、散热器满功率
- **食段进入时**: 太阳能归零、电池放电、GPU 降频、散热器降功率
- 所有 Canvas 视觉效果自动切换 (明/暗配色)

### 8.3 自动遥测日志

每 ~85 秒模拟时间自动添加一条遥测日志，用户可在右侧 "Telemetry Log" 区域滚动查看历史记录。

### 8.4 窗口自适应

浏览器窗口大小变化时:
- Canvas 自动重新调整分辨率
- 星空背景重新生成
- 所有布局元素通过 CSS Grid/Flexbox 自适应

---

## 9. Digital Twin 功能总览

> **源文件**: `js/dt-controls.js` (控件绑定) + `js/state.js` (数据模型) + `js/simulation.js` (计算逻辑)

模拟器内置 **7 项数字孪生核心功能**，将静态演示升级为可交互调参的工程仿真平台：

| # | 功能名称 | 控制方式 | 影响范围 |
|---|----------|----------|----------|
| 1 | 散热器材料编辑器 | ε 滑块 + 冷却剂下拉 | 散热功率、GPU 温度、能量平衡 |
| 2 | 太阳能翼数量/面积调节 | 翼数滑块 + 面积滑块 | 发电功率、电池充电速率、Canvas 布局 |
| 3 | 太阳能电池技术选择 | 下拉菜单 (4 种技术) | 发电效率、温度系数、成本 |
| 4 | 散热器面板数量/面积调节 | 面板数滑块 + 面积滑块 | 散热能力、GPU 温度、Canvas 布局 |
| 5 | 实时趋势图 | 自动绘制，底部全宽 | Solar/Bat/Rad/GPU 四通道时序 |
| 6 | 卫星模型动态跟随 | 自动 (参数变化时) | Canvas 卫星几何、标注 |
| 7 | **Workload 负载选择** | **下拉菜单 (6 种负载)** | **GPU功耗、废热、FLOPS、散热可行性、电池充放电** |

---

## 10. 功能 1：散热器材料编辑器 (Radiator Material Editor)

### 10.1 功能描述

用户可在右侧 "Digital Twin Controls" 面板中调整：
- **发射率 ε (Emissivity)**：通过滑块在 0.50 ~ 0.98 之间调节
- **冷却剂类型**：通过下拉菜单选择 NH₃ / Propylene / R-134a

### 10.2 实现原理

#### 10.2.1 Stefan-Boltzmann 辐射定律

散热器的辐射散热功率由 Stefan-Boltzmann 定律决定：

$$Q_{rad} = \varepsilon \cdot \sigma \cdot A \cdot F_v \cdot (T_{surf}^4 - T_{space}^4)$$

其中：
- $\varepsilon$ — 表面发射率 (用户可调，0.50~0.98)
- $\sigma = 5.67 \times 10^{-8} \text{ W/m²·K⁴}$ — Stefan-Boltzmann 常数
- $A$ — 散热面板面积 (m²)
- $F_v$ — 视角因子 (view factor)，取 0.85~0.95
- $T_{surf}$ — 面板表面温度 (K)
- $T_{space} = 2.7 \text{ K}$ — 深空背景温度 (宇宙微波背景辐射)

当用户调高 ε 时，$Q_{rad}$ 直接线性增大，散热能力增强 → GPU 温度降低。

#### 10.2.2 冷却剂热容因子

不同冷却剂通过 `heatCapFactor` 系数影响有效散热功率：

| 冷却剂 | 名称 | 流量 (kg/s) | 入口温度 (°C) | 出口温度 (°C) | 热容因子 |
|--------|------|-------------|---------------|---------------|----------|
| NH₃ | 氨 (两相) | 4.2 | 85 | 45 | 1.00 |
| Propylene | 丙烯 (单相) | 5.8 | 80 | 50 | 0.72 |
| R-134a | R-134a (两相) | 6.1 | 78 | 48 | 0.85 |

有效散热功率 = $Q_{rad} \times \text{heatCapFactor}$

NH₃ 两相循环因利用蒸发潜热具有最高热传递效率；丙烯作为单相流体依赖显热传递，效率较低。

### 10.3 代码实现

```javascript
// 冷却剂数据库
const COOLANTS={
  nh3:       {name:'NH₃ 2-phase', flow:4.2, tIn:85, tOut:45, heatCapFactor:1.0},
  propylene: {name:'Propylene 1-phase', flow:5.8, tIn:80, tOut:50, heatCapFactor:0.72},
  r134a:     {name:'R-134a 2-phase', flow:6.1, tIn:78, tOut:48, heatCapFactor:0.85},
};

// ε 滑块事件
slEps.addEventListener('input', () => {
  radEpsilon = parseInt(slEps.value) / 100;
  radPanels.forEach(p => p.emissivity = radEpsilon);
});

// 实际散热计算 (updateRadTable)
p.qRad = (p.emissivity * SIGMA * p.area * p.viewFactor * (T**4 - 2.7**4)) / 1000 * cool.heatCapFactor;
```

### 10.4 对系统的影响

- **ε 增大** → 散热功率增大 → GPU 温度降低 → 系统更健康
- **ε 降低** → 散热不足 → GPU 温度升高 → 可能触发 "GPU OVERHEAT" 告警
- **切换冷却剂** → 改变入/出口温度差、流量、以及有效散热比例

---

## 11. 功能 2：太阳能翼数量/面积调节 (Solar Wing Configuration)

### 11.1 功能描述

- **翼数量 (Wing Count)**：滑块调节 2~12 片翼
- **单翼面积 (Area per Wing)**：滑块调节 100~500 m²

### 11.2 实现原理

#### 11.2.1 太阳能发电功率模型

每片翼的输出功率为：

$$P_{wing} = A_{wing} \times G_{SC} \times \eta_{cell} \times [1 - \alpha_T \cdot (T_{cell} - 25)]$$

其中：
- $A_{wing}$ — 单翼面积 (m²)，用户可调
- $G_{SC} = 1367 \text{ W/m²}$ — 太阳常数 (AM0)
- $\eta_{cell}$ — 电池片效率 (由电池技术决定)
- $\alpha_T$ — 温度功率系数 (°C⁻¹)
- $T_{cell}$ — 电池工作温度 (°C)
- 25°C — 标准测试条件 (STC) 参考温度

总发电功率 = $\sum_{i=1}^{N} P_{wing,i}$，其中 $N$ 为翼数量。

#### 11.2.2 动态数组重建

调节翼数时，`rebuildWings()` 函数会销毁旧数组并创建新数组：

```javascript
function rebuildWings() {
  const tech = CELL_TECHS[currentCellTech];
  wings = Array.from({length: wingCount}, (_, i) => ({
    id: i+1, name: `W${String.fromCharCode(65+(i%26))}`,
    cells: 240, area: wingArea,
    temp: 65 + Math.random()*10,
    efficiency: tech.eff + (Math.random()-0.5)*0.005,
    output: 0
  }));
}
```

#### 11.2.3 自适应 Canvas 网格布局

太阳能阵列 Canvas 的网格布局根据翼数量动态计算：

```javascript
let cols = Math.ceil(Math.sqrt(n));  // n = wings.length
let rows = Math.ceil(n / cols);
const cellW = (W - 2*margin - (cols-1)*gap) / cols;
const cellH = (H - 2*margin - (rows-1)*gap) / rows;
```

| 翼数 | 列数 | 行数 | 布局 |
|------|------|------|------|
| 2 | 2 | 1 | 2×1 |
| 4 | 2 | 2 | 2×2 |
| 6 | 3 | 2 | 3×2 |
| 8 | 3 | 3 | 3×3 (最后行不满) |
| 12 | 4 | 3 | 4×3 |

### 11.3 对系统的影响

- **翼数增加** → 总面积增大 → 发电能力增强 → 电池充电更快
- **面积增大** → 单翼功率增大 → 但成本 ($23k/m²) 也线性增加
- 成本表中太阳能阵列成本自动更新：`costSolar = totalArea × 0.023` ($M)

---

## 12. 功能 3：太阳能电池技术选择 (Cell Technology Selection)

### 12.1 功能描述

通过下拉菜单在 4 种电池技术间切换：

| 技术 | 效率 η | BOL 效率 | EOL 效率 | Voc | 温度系数 | 辐射耐受 |
|------|--------|----------|----------|-----|----------|----------|
| **TJ InGaP/GaAs/Ge** (默认) | 29.5% | 32.0% | 28.8% | 2.67V | -0.20%/°C | 1×10¹⁵ e/cm² |
| **4J IMM** | 34.0% | 36.8% | 33.2% | 3.42V | -0.18%/°C | 8×10¹⁴ e/cm² |
| **Perovskite/Si Tandem** | 26.0% | 28.0% | 22.5% | 1.92V | -0.25%/°C | 5×10¹³ e/cm² |
| **Silicon PERC** | 22.0% | 24.0% | 21.2% | 0.72V | -0.30%/°C | 1×10¹⁴ e/cm² |

### 12.2 实现原理

#### 12.2.1 多结太阳能电池效率差异

- **三结 (TJ)**：InGaP (1.86eV) / GaAs (1.42eV) / Ge (0.67eV) 三层堆叠，各层吸收不同波段光谱
- **四结倒生长 (4J IMM)**：额外增加 InGaAsP 层覆盖 1.0eV 带隙，理论效率更高但辐射退化稍快
- **钙钛矿/硅叠层**：新兴技术，成本低但辐射耐受差，适合 LEO 短期任务
- **单晶硅 PERC**：最成熟最便宜，但空间效率低，温度系数最大

#### 12.2.2 温度功率去额系数 ($\alpha_T$)

温度去额公式为：

$$\text{Derating} = 1 - \alpha_T \cdot (T_{cell} - 25\text{°C})$$

当电池温度从 25°C 升至 75°C 时：
- TJ: 功率损失 = 0.002 × 50 = 10%
- 4J IMM: 功率损失 = 0.0018 × 50 = 9%
- Perovskite: 功率损失 = 0.0025 × 50 = 12.5%
- Si PERC: 功率损失 = 0.003 × 50 = 15%

这意味着 Si PERC 在轨道日照期（电池温度 ~75°C）的实际功率比 STC 标称低 15%。

### 12.3 代码实现

```javascript
const CELL_TECHS = {
  tj:    { name:'TJ InGaP/GaAs/Ge', eff:0.295, tcoef:0.002, ... },
  imm4j: { name:'4J IMM', eff:0.340, tcoef:0.0018, ... },
  perov: { name:'Perovskite/Si Tandem', eff:0.260, tcoef:0.0025, ... },
  si:    { name:'Silicon PERC', eff:0.220, tcoef:0.003, ... },
};

// 切换时重建所有翼
selCT.addEventListener('change', () => {
  currentCellTech = selCT.value;
  rebuildWings();
  updateCellTechDisplay(); // 更新右侧 Cell Tech 表格
  updateDTSummary();       // 更新 Impact Summary
});
```

### 12.4 对系统的影响

- **选择高效率电池** → 相同面积下发电更多 → 可以减少翼数以降低质量/成本
- **选择低温度系数电池** → 高温下功率损失更小 → 日照期更稳定
- **辐射耐受差的电池** (如 Perovskite) → EOL 效率退化严重 → 需要更大面积冗余

---

## 13. 功能 4：散热器面板数量/面积调节 (Radiator Panel Configuration)

### 13.1 功能描述

- **面板数量 (Panel Count)**：滑块调节 2~10 片
- **单面板面积 (Area per Panel)**：滑块调节 50~300 m²

### 13.2 实现原理

与功能 2 类似，`rebuildRadPanels()` 函数动态创建散热面板数组：

```javascript
function rebuildRadPanels() {
  radPanels = Array.from({length: radCount}, (_, i) => ({
    id: i+1, area: radArea,
    surfTemp: 55 + Math.random()*8,
    emissivity: radEpsilon,
    viewFactor: 0.85 + Math.random()*0.1,
    qRad: 0
  }));
}
```

散热器 Canvas 布局为 N 列并排，自动适应面板数量：

```javascript
const panelW = (W - 2*margin - (n-1)*gap) / n;  // n = radPanels.length
```

### 13.3 散热能力 vs 计算热负荷

系统设定计算热负荷为 ~1000 kW (5120 × H100 GPU)。GPU 温度模型：

$$T_{GPU} = T_{base} + (1 - \theta) \times 25°C$$

其中 $\theta = \min(1, \frac{Q_{rad,total}}{Q_{compute} \times 0.4})$ 为散热充裕度。

- 当散热功率足够时 ($\theta = 1$)：GPU 温度正常 (~80°C)
- 当散热不足时 ($\theta < 1$)：GPU 温度升高最多 25°C → 可达 105°C → 触发 OVERHEAT

### 13.4 对系统的影响

- **面板数减少** → 散热总面积减小 → GPU 温度上升 → 可能报警
- **面板面积增大** → 单面板散热更强 → 但成本 ($33k/m²) 增加
- 与功能 1 的 ε 和冷却剂联动：低 ε + 少面板 = 散热严重不足

---

## 14. 功能 5：实时趋势图 (Real-Time Trend Chart)

### 14.1 功能描述

在主视图区域底部新增一个全宽趋势图面板（跨两列，高度 160px），实时绘制 4 条时序曲线：

| 通道 | 颜色 | 单位 | 归一化方法 |
|------|------|------|------------|
| Solar Power | 🟡 #ffe066 | kW | solar/peakSolar × 100% |
| Battery SOC | 🟠 #ff6b00 | % | 原始值 (0-100%) |
| Radiator Power | 🔴 #ff4400 | kW | rad/peakRad × 100% |
| GPU Temperature | 🔵 #00d4ff | °C | (T-20)/(100-20) × 100% |

### 14.2 实现原理

#### 14.2.1 环形缓冲区 (Ring Buffer)

使用 4 个独立数组存储历史数据，最大长度 `TREND_MAX = 600` 个数据点：

```javascript
const trendData = { solar: [], bat: [], rad: [], gpuT: [] };

function pushTrend(solarPwr, radPwr, gpuTemp) {
  trendData.solar.push(solarPwr);
  trendData.bat.push(batSOC);
  trendData.rad.push(radPwr);
  trendData.gpuT.push(gpuTemp);
  // 超过最大长度时移除最老的数据点
  if (trendData.solar.length > TREND_MAX) {
    trendData.solar.shift(); trendData.bat.shift();
    trendData.rad.shift();   trendData.gpuT.shift();
  }
}
```

每 1 秒模拟时间采样一次 (`trendTimer` 累计)。

#### 14.2.2 归一化与绘制

所有 4 条曲线归一化到 0-100% 范围后绘制在同一坐标系中：

```javascript
const lines = [
  {data: trendData.solar, color: '#ffe066', norm: v => v/peakSolar*100},
  {data: trendData.bat,   color: '#ff6b00', norm: v => v},         // 已经是 %
  {data: trendData.rad,   color: '#ff4400', norm: v => v/peakRad*100},
  {data: trendData.gpuT,  color: '#00d4ff', norm: v => (v-20)/80*100},  // 20~100°C → 0~100%
];
```

每条曲线绘制为 Canvas 折线，同时绘制发光效果 (glow) 增强可读性。

#### 14.2.3 食段阴影

当 Solar Power ≈ 0 时，在趋势图背景绘制蓝色竖条标识食段：

```javascript
if (trendData.solar[i] < 1) {
  tX.fillStyle = 'rgba(0,20,80,0.15)';
  tX.fillRect(x-0.5, padT, 1.5, gH);
}
```

#### 14.2.4 布局调整

主视图采用 3 行布局（上两行为四象限，第三行为趋势图）：

```css
.left-main {
  grid-template-columns: 1fr 1fr;
  grid-template-rows: 1fr 1fr 160px;  /* 新增第3行 */
}

.trend-pane {
  grid-column: 1/3;  /* 跨两列 */
}
```

### 14.3 趋势图的观察价值

- **日照-食段交替**：清晰看到 Solar (黄) 方波切换 + Bat SOC (橙) 锯齿充放电
- **散热波动**：Rad (红) 在食段因面板温度下降而功率降低
- **GPU 温度响应**：调整散热参数后 GPU (蓝) 温度变化有滞后效应
- **参数对比**：切换电池技术后立即在趋势图中看到发电功率的变化

---

## 15. Digital Twin 控制面板交互总览

### 15.1 HTML 结构

所有控件集中在右侧边栏的 `"Digital Twin Controls"` 区段内，分两组：

```
psec (Digital Twin Controls)
├── dt-group (☀ SOLAR ARRAY CONFIG)
│   ├── dt-row: Wings slider (2-12)
│   ├── dt-row: Area/W slider (100-500 m²)
│   └── dt-row: Cell tech dropdown (TJ/4J/Perov/Si)
├── dt-group (🌡 RADIATOR CONFIG)
│   ├── dt-row: Panels slider (2-10)
│   ├── dt-row: Area/P slider (50-300 m²)
│   ├── dt-row: ε slider (0.50-0.98)
│   └── dt-row: Coolant dropdown (NH₃/Propylene/R-134a)
└── dt-summary (Impact Summary)
    ├── Total Solar Area + Peak Power
    ├── Total Rad Area + Peak Q
    └── Energy Balance (surplus/deficit)
```

### 15.2 CSS 样式

新增的 Digital Twin 专用样式类：

| 类名 | 用途 |
|------|------|
| `.dt-row` | 控件行布局 (label + slider + value) |
| `.dt-label` | 控件标签 (7px, uppercase) |
| `.dt-val` | 当前值显示 (9px, accent color) |
| `.dt-slider` | 自定义滑块 (3px 高，圆形拇指) |
| `.dt-slider.solar-s` | 太阳能色系拇指 (#ffe066) |
| `.dt-slider.rad-s` | 散热器色系拇指 (#ff4400) |
| `.dt-select` | 下拉选择框 (panel bg, accent text) |
| `.dt-group` | 控件分组容器 (带边框) |
| `.dt-summary` | 影响摘要面板 (淡蓝背景) |
| `.ptitle.dt` | Digital Twin 标题 (橙色圆点) |

### 15.3 事件绑定

`setupDTControls()` 在初始化时绑定所有滑块/下拉的 `input`/`change` 事件。每次参数变更会触发：

1. 更新对应的全局变量 (`wingCount`, `wingArea`, `radCount`, `radArea`, `radEpsilon`, etc.)
2. 调用 `rebuildWings()` 或 `rebuildRadPanels()` 重建数据模型
3. 调用 `updateDTSummary()` 更新影响摘要（含成本估算）
4. 调用 `updateCellTechDisplay()` / `updateCoolantDisplay()` 更新详情表格
5. 向遥测日志写入配置变更消息

### 15.4 成本动态更新

当用户调整面积时，Mission Cost 表格自动更新：

```javascript
const solarCost = Math.round(totalSolarArea * 0.023);  // $23k/m²
const radCost = Math.round(totalRadArea * 0.033);       // $33k/m²
const totalCost = 120 + 85 + solarCost + 42 + radCost + 256 + 38 + 22 + 45 + 80;
const breakeven = totalCost / (revenue - opex);
```

---

## 16. 物理模型补充（Digital Twin 扩展）

### 16.1 GPU 温度模型

Digital Twin 引入了散热充裕度对 GPU 温度的影响：

$$T_{GPU} = T_{base} + (1 - \theta) \times 25°C$$

$$\theta = \min\left(1, \frac{Q_{rad,total}}{Q_{compute} \times 0.4}\right)$$

其中：
- $T_{base}$ — 基础 GPU 温度 (日照 ~80°C, 食段根据 SOC 调节)
- $\theta$ — 散热充裕度因子 (0~1)
- $Q_{compute} = 1000 \text{ kW}$ — 计算热负荷
- 0.4 因子反映只有约 40% 计算热量需要通过辐射散出 (其余通过结构传导、MLI 等路径)

### 16.2 能量平衡判定

Impact Summary 面板显示能量平衡：

$$\Delta P = P_{solar,peak} - P_{compute}$$

- $\Delta P > 0$：系统有盈余，显示绿色 `+xxx kW surplus`
- $\Delta P \leq 0$：系统亏损，显示红色 `−xxx kW DEFICIT`

注意：此为日照期峰值估算。食段期间太阳能为零，完全依赖电池。

---

## 17. 完整参数交叉影响矩阵

| 调节参数 | 发电功率 | 散热功率 | GPU温度 | 电池SOC | 成本 | 卫星外观 |
|----------|----------|----------|---------|---------|------|----------|
| ↑ Wing Count | ↑↑ | — | — | ↑ | ↑ | 翼片堆叠层数增加 |
| ↑ Wing Area | ↑↑ | — | — | ↑ | ↑ | 翼片宽度增大 |
| Cell Tech (高效) | ↑ | — | — | ↑ | — | — |
| ↑ Rad Panel Count | — | ↑↑ | ↓↓ | — | ↑ | 散热面板堆叠层数增加 |
| ↑ Rad Panel Area | — | ↑↑ | ↓↓ | — | ↑ | 散热面板高度增大 |
| ↑ Emissivity ε | — | ↑ | ↓ | — | — | — |
| Coolant (高效) | — | ↑ | ↓ | — | — | — |

符号说明：↑↑ 强正相关 | ↑ 正相关 | ↓ 负相关 | ↓↓ 强负相关 | — 无直接影响

---

## 18. 功能 6：卫星3D模型动态跟随参数变化 (Satellite Visual Follows DT Parameters)

### 18.1 功能描述

当用户通过 Digital Twin Controls 调整太阳能翼数量/面积、散热器面板数量/面积时，**轨道视图和航天器详情视图中的卫星图标会实时跟随变化**：

| 参数变化 | 视觉反馈 |
|----------|----------|
| 翼数量增加 | 每侧翼片堆叠层数增加（左/右各 ceil(N/2) 层） |
| 翼面积增大 | 翼片宽度增大（100m²→短翼，500m²→宽翼） |
| 散热面板数量增加 | 每侧散热面板堆叠层数增加 |
| 散热面板面积增大 | 每个散热面板高度增大 |

### 18.2 实现原理

#### 18.2.1 动态几何参数计算

`drawSatIcon()` 函数不再使用硬编码尺寸，而是根据全局 DT 参数动态计算：

```javascript
// 翼宽度按面积缩放 (350m² 基线 = 52px)
const wingWBase = Math.max(28, Math.min(80, (wingArea/350)*52)) * s;

// 每侧翼片数 = ceil(总翼数 / 2)
const wingsPerSide = Math.ceil(wingCount / 2);

// 散热面板高度按面积缩放 (143m² 基线 = 20px)
const radHBase = Math.max(12, Math.min(32, (radArea/143)*20)) * s;

// 每侧散热面板数 = ceil(总面板数 / 2)
const radsPerSide = Math.ceil(radCount / 2);
```

#### 18.2.2 堆叠式翼/面板布局

翼和散热面板按左右两侧分配，每侧从上到下堆叠排列：

```
            [Wing 1]     |BODY|     [Wing 1]
            [Wing 2]     |    |     [Wing 2]
   左侧翼   [Wing 3] ---|    |---  [Wing 3]  右侧翼
            [Wing 4]     |    |     [Wing 4]
                         |RAD1|
                         |RAD2|
                         |RAD3|
```

- 翼片之间有 `2*s` 的间距 (`wingGap`)
- 散热面板之间有 `1.5*s` 的间距 (`radGap`)
- 翼通过 `armLen = 4*s` 的连杆与本体相连

左侧分配 `floor(N/2)` 片，右侧分配 `ceil(N/2)` 片，确保总数始终等于用户设置的翼数。

#### 18.2.3 详情视图标注跟随

`drawDetail()` 中的标注线和箭头位置基于实际卫星几何动态计算：

```javascript
// 翼尖到中心的距离
const wingTipOffset = bw/2 + armLen + wingWPx;

// 左翼尖在屏幕上的 x 坐标
const lwTipX = W/2 - wingTipOffset;

// 标注位置跟随翼尖
const annoLx = Math.max(10, lwTipX - 60);

// 太阳辐射箭头跨度从翼尖到翼尖
dX.beginPath();
dX.moveTo(lwTipX, arY);
dX.lineTo(W/2 - bw/2, arY);  // 到本体边缘

// IR 发射线从散热器外缘向外延伸
const emBaseX = W/2 + bw/2 + radWPx;
```

### 18.3 视觉效果对比

| 配置 | 卫星外观 |
|------|----------|
| 2 翼 100m² / 2 面板 50m² | 极简小型卫星：短小翼+小散热器 |
| 8 翼 350m² / 6 面板 143m² (默认) | 标准配置：中等对称结构 |
| 12 翼 500m² / 10 面板 300m² | 巨型卫星：宽大翼片层叠+高大散热阵列 |

### 18.4 太阳能电池格子数自适应

翼片内部的太阳能电池网格也随翼宽动态调整列数：

```javascript
const cellCols = Math.max(3, Math.min(10, Math.round(wingWBase/(6*s))));
```

窄翼 (100m²) 显示 3~4 列电池格，宽翼 (500m²) 显示 8~10 列，保持视觉比例协调。

---

## 19. 功能 7：Workload 负载选择 (Compute Workload Configuration)

### 19.1 功能描述

用户可在右侧 "Digital Twin Controls" 面板的 **WORKLOAD CONFIG** 区域切换计算负载类型，包括：

- **训练任务**: LLaMA-3 70B、LLaMA-3 405B、GPT-4 1.8T MoE
- **推理任务**: LLaMA-3 70B Inference、LLaMA-3 405B Inference、Stable Diffusion XL

切换后，模拟器自动更新：
1. GPU 数量与型号
2. 总计算功耗 (kW)
3. 废热负载 (kW) — 影响散热器是否足够
4. ExaFLOPS 峰值
5. GPU 利用率
6. 能量平衡 (Solar peak - Compute load)
7. **散热可行性判断** — 实时显示散热器能否满足当前负载产生的废热

### 19.2 Workload 数据模型

> **源文件**: `js/constants.js` — `WORKLOADS` 对象

每个 workload 条目的字段：

| 字段 | 说明 | 示例 |
|------|------|------|
| `name` | 显示名称 | `'LLaMA-3 70B Training'` |
| `type` | `'train'` 或 `'infer'` | `'train'` |
| `model` | 模型规模 | `'70B'` |
| `gpuCount` | GPU 数量 | `5120` |
| `gpuModel` | GPU 型号 | `'H100 80GB'` |
| `perGpuTDP` | 单卡 TDP (kW) | `0.700` |
| `gpuUtil` | 典型利用率 | `0.92` |
| `totalComputekW` | 总功耗 = gpuCount × TDP × util | `3297` |
| `heatFraction` | 废热占比 (→ 散热器) | `0.40` |
| `peakFLOPS` | 峰值 ExaFLOPS | `12.8` |

### 19.3 预设负载一览

| Workload | 类型 | GPU数 | 总功耗 | 废热 | FLOPS |
|----------|------|-------|--------|------|-------|
| LLaMA-3 70B Train | 训练 | 5120 | 3,297 kW | 1,319 kW | 12.8 EF |
| LLaMA-3 405B Train | 训练 | 5120 | 3,154 kW | 1,325 kW | 11.2 EF |
| GPT-4 1.8T MoE Train | 训练 | 5120 | 3,046 kW | 1,310 kW | 10.6 EF |
| LLaMA-3 70B Infer | 推理 | 2560 | 986 kW | 345 kW | 6.4 EF |
| LLaMA-3 405B Infer | 推理 | 5120 | 1,792 kW | 681 kW | 8.0 EF |
| SDXL Image Gen | 推理 | 1280 | 627 kW | 207 kW | 3.2 EF |

### 19.4 散热可行性判断

> **源文件**: `js/dt-controls.js` — `updateThermalStatus()`

系统实时计算散热容量与废热负载之比：

$$\rho = \frac{Q_{rad,peak}}{Q_{heat}} = \frac{Q_{rad,peak}}{P_{compute} \times f_{heat}}$$

判定规则：
- $\rho \geq 1.2$ → ✓ OK (绿色)
- $1.0 \leq \rho < 1.2$ → ⚠ Marginal (黄色)
- $\rho < 1.0$ → ✗ OVERHEAT (红色，显示热缺口 kW)

### 19.5 对仿真引擎的影响

> **源文件**: `js/simulation.js`

Workload 参数直接驱动主循环中的以下计算：

- **FLOPS**: `wl.peakFLOPS × gpuUtil` (日照时有随机扰动，食段按 SOC 比例降低)
- **GPU 利用率**: 基于 `wl.gpuUtil` + 随机波动
- **电池充放电**: 放电速率与 `computeLoad / 1400` 成正比；充电仅在 `solarPwr > computeLoad` 时进行
- **GPU 温度**: 受 `heatLoad` 与散热器容量之比影响，$T_{GPU} = T_{base} + (1 - \theta) \times 25°C$
- **系统状态**: 新增 `THERMAL DEFICIT` 告警 (散热不足 80%)

---

## 20. 模块化架构说明

### 20.1 设计目标

将原先 ~1300 行的单体 HTML 文件重构为 **1 个入口 HTML + 1 个 CSS + 12 个 JS 模块**，实现：

1. **关注点分离** — 每个文件只负责一个功能域
2. **可维护性** — 修改某一绘制逻辑无需搜索千行文件
3. **零依赖** — 不引入 ES Module bundler，保持双击即可运行的简洁性

### 20.2 文件清单与职责

| 文件 | 职责 | 主要导出 (全局函数/变量) |
|------|------|--------------------------|
| `index.html` | HTML 结构 + 脚本加载顺序 | — |
| `css/styles.css` | 全部 CSS 样式 | — |
| `js/constants.js` | 轨道常量、电池技术库、冷却剂库、负载库 | `ORBIT_PERIOD`, `ECLIPSE_FRAC`, `SIGMA`, `CELL_TECHS`, `COOLANTS`, `WORKLOADS` |
| `js/state.js` | 全局状态、数据模型、趋势缓冲 | `simTime`, `speed`, `wings`, `radPanels`, `currentWorkload`, `rebuildWings()`, `pushTrend()` |
| `js/telemetry.js` | 遥测日志系统 | `LOGS`, `addLog()`, `p2()` |
| `js/starfield.js` | 背景星空渲染 | `initStars()`, `drawStars()` |
| `js/canvas.js` | Canvas 引用、尺寸管理、工具函数 | `oC/oX`, `dC/dX`, `sC/sX`, `rC/rX`, `tC/tX`, `resizeAll()`, `getAngle()`, `isEclipse()` |
| `js/satellite.js` | 卫星图标 + 详情视图绘制 | `drawSatIcon()`, `drawDetail()` |
| `js/orbit.js` | 地球轨道视图 | `drawOrbit()` |
| `js/solar-array.js` | 太阳能阵列 Canvas + 翼表 | `drawSolarArray()`, `updateWingTable()` |
| `js/radiator.js` | 散热器 Canvas + 面板表 | `drawRadiator()`, `updateRadTable()` |
| `js/trend-chart.js` | 底部趋势图 | `drawTrend()` |
| `js/dt-controls.js` | Digital Twin 控件事件绑定 | `setupDTControls()`, `updateDTSummary()`, `updateWorkloadDisplay()`, `updateThermalStatus()` |
| `js/simulation.js` | 主循环、动画帧、初始化 | `update()`, `setSpeed()`, `animate()` |

### 20.3 加载顺序与依赖

脚本标签在 `index.html` 底部按严格顺序加载，确保被依赖模块先行注册到全局作用域：

```text
constants.js          ← 无依赖（纯数据）
      ↓
state.js              ← 依赖 constants（CELL_TECHS, COOLANTS）
      ↓
telemetry.js          ← 无依赖
      ↓
starfield.js          ← 无依赖
      ↓
canvas.js             ← 依赖 constants（ORBIT_PERIOD, ECLIPSE_FRAC, ECLIPSE_START）
      ↓
satellite.js          ← 依赖 canvas（dC, dX）+ state（wingCount, radPanelCount 等）
      ↓
orbit.js              ← 依赖 canvas + satellite + state
      ↓
solar-array.js        ← 依赖 canvas + state
      ↓
radiator.js           ← 依赖 canvas + state + constants
      ↓
trend-chart.js        ← 依赖 canvas（tC, tX）+ state（trendData）
      ↓
dt-controls.js        ← 依赖 state + constants + telemetry
      ↓
simulation.js         ← 依赖以上全部模块（调用所有 draw/update 函数）
```

### 20.4 模块间通信方式

所有模块通过 **全局作用域** 共享状态与函数，无 `import`/`export`：

```javascript
// js/state.js — 声明全局变量
let wingCount = 8;

// js/simulation.js — 直接读取
const totalPower = wings.slice(0, wingCount).reduce(…);

// js/dt-controls.js — 直接修改
document.getElementById('wingSlider').addEventListener('input', e => {
  wingCount = +e.target.value;
  rebuildWings();
});
```

**优势**: 零配置、无打包步骤、双击 `index.html` 即可运行  
**约束**: 脚本加载顺序必须正确，否则运行时会出现 `ReferenceError`

### 20.5 扩展指南

添加新功能模块时：

1. 在 `js/` 下创建新文件（如 `js/new-feature.js`）
2. 在 `index.html` 中按依赖关系插入 `<script>` 标签
3. 若需新的全局状态，在 `js/state.js` 中声明
4. 若需新的 UI 控件，在 `js/dt-controls.js` 的 `setupDTControls()` 中绑定
5. 在 `js/simulation.js` 的 `update()` 或 `animate()` 中调用新模块的渲染函数

---

> **文档更新时间**: 2025-02-26  
> **文档适用版本**: Space Data Center Simulator (模块化架构)  
> **项目结构**: `index.html` + `css/styles.css` + 12 个 JS 模块 (`js/*.js`)
