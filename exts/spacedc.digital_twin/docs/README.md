# SpaceDC Digital Twin — NVIDIA Omniverse Extension

> **ORBITAL DC-1** · 1MW-class Space Data Center · Digital Twin Simulator

将 SpaceDC Web 模拟器完整迁移到 NVIDIA Omniverse 平台，利用 RTX 光线追踪和 USD 场景描述实现物理级真实的太空数据中心数字孪生。

---

## 项目结构

```
exts/spacedc.digital_twin/
├── config/
│   └── extension.toml              ← Omniverse Extension 配置清单
├── spacedc/digital_twin/
│   ├── __init__.py
│   ├── extension.py                ← 🚀 主入口 (on_startup / on_shutdown)
│   ├── simulation_engine.py        ← ⚙️  主仿真循环 (tick-based)
│   │
│   ├── physics/                    ← 🔬 物理模型层 (纯 Python，无 USD 依赖)
│   │   ├── __init__.py
│   │   ├── constants.py            ← 轨道常数、电池技术库、冷却剂库、负载库
│   │   ├── state.py                ← SimState 数据模型 + SolarWing / RadiatorPanel
│   │   ├── orbital_mechanics.py    ← 轨道角度、Eclipse 检测、RAAN、Beta 角
│   │   ├── solar_array_model.py    ← 太阳能发电模型 (P = n·A·G·η·f(T))
│   │   ├── thermal_model.py        ← Stefan-Boltzmann 辐射散热 + GPU 温度
│   │   ├── battery_model.py        ← 电池 SOC 充放电模型
│   │   ├── workload_model.py       ← GPU 计算负载 (7 种 Workload)
│   │   └── telemetry.py            ← 遥测日志系统
│   │
│   ├── scene/                      ← 🌍 USD 场景构建 (需要 pxr + Omniverse)
│   │   ├── __init__.py
│   │   ├── earth_builder.py        ← 地球 + 大气层 + 太阳 + 星空 + 轨道环
│   │   ├── satellite_builder.py    ← 参数化卫星模型 (太阳翼/散热板/天线/推进器)
│   │   └── environment.py          ← 光照系统 + Eclipse 光影切换
│   │
│   └── ui/                         ← 🖥️  omni.ui 界面层
│       ├── __init__.py
│       ├── dt_panel.py             ← Digital Twin 控制面板 (7 项参数)
│       ├── telemetry_panel.py      ← 遥测日志窗口 + HUD 状态覆盖
│       └── trend_chart.py          ← 4 通道实时趋势图
│
└── docs/
    └── README.md                   ← 本文件
```

---

## 🔄 JS → Python 模块映射

| 原始 JS 文件 | Omniverse Python 模块 | 功能 |
|---|---|---|
| `constants.js` | `physics/constants.py` | 轨道参数、电池技术库、冷却剂库、Workload 数据库 |
| `state.js` | `physics/state.py` | SimState 数据类、SolarWing/RadiatorPanel 数据模型 |
| `canvas.js` | `physics/orbital_mechanics.py` | `get_angle()`, `is_eclipse()` |
| `orbit.js` / `orbit3d.js` | `scene/earth_builder.py` | 3D 地球场景 → USD Sphere + DistantLight |
| `satellite.js` / `satellite3d.js` | `scene/satellite_builder.py` | 3D 卫星模型 → 参数化 USD prims |
| `solar-array.js` | `physics/solar_array_model.py` | 太阳能发电物理模型 |
| `radiator.js` | `physics/thermal_model.py` | 热辐射模型 (Stefan-Boltzmann) |
| `simulation.js` | `simulation_engine.py` + `physics/battery_model.py` | 主循环 + 电池 SOC |
| `dt-controls.js` | `ui/dt_panel.py` | Digital Twin UI 控制面板 |
| `telemetry.js` | `physics/telemetry.py` + `ui/telemetry_panel.py` | 日志系统 |
| `trend-chart.js` | `ui/trend_chart.py` | 实时趋势图 |
| `starfield.js` | `scene/earth_builder.py` (Stars prim) | 星空 → USD Points |

---

## 🚀 快速开始

### 前置要求

- **NVIDIA Omniverse Kit** ≥ 105.1 (或 Code / Create / Isaac Sim)
- **RTX GPU**: GeForce RTX 3070+ / RTX A4000+ 推荐
- **Python 3.10+** (Kit 内置)

### 安装步骤

1. **Clone 项目**
   ```bash
   git clone https://github.com/Markliu225/SpaceDC.git
   ```

2. **注册 Extension 搜索路径**

   在 Omniverse Kit 中：
   - 打开 `Edit → Preferences → Extensions`
   - 添加搜索路径: `<your-clone-path>/SpaceDC/exts`
   - 或者在 Kit `.kit` 文件中添加:
     ```toml
     [settings.exts]
     "exts/directories/spacedc" = "C:/Workspace/SpaceDC/exts"
     ```

3. **启用 Extension**

   在 Extensions 窗口搜索 "SpaceDC" 并启用。

4. **即刻运行**

   Extension 会自动：
   - 构建 USD 地球 + 卫星场景
   - 打开 Digital Twin 控制面板
   - 启动仿真循环

---

## 🎛️ Digital Twin 控制参数

| # | 参数 | 范围 | 默认值 | 影响 |
|---|------|------|--------|------|
| 1 | Solar Wing Count | 2 ~ 12 | 8 | 发电量、卫星外观 |
| 2 | Wing Area | 50 ~ 500 m² | 350 m² | 发电量、翼板尺寸 |
| 3 | Cell Technology | TJ / 4J-IMM / Perovskite / Si | TJ InGaP | 转换效率 η |
| 4 | Radiator Panels | 2 ~ 10 | 6 | 散热容量 |
| 5 | Panel Area | 50 ~ 300 m² | 143.3 m² | 散热容量 |
| 6 | Emissivity ε | 0.50 ~ 0.99 | 0.92 | 辐射散热效率 |
| 7 | Coolant | NH₃ / Propylene / R-134a | NH₃ 2-phase | 热容系数 |
| 8 | Workload | 7 种 AI 训练/推理负载 | LLaMA-3 70B Train | 功耗、热负荷 |

---

## 📐 物理模型

### 太阳能发电
$$P_{solar} = n_{wings} \times A_{wing} \times G \times \eta \times (1 - \alpha \cdot \Delta T)$$

- $G = 1367 \text{ W/m²}$ (太阳常数)
- $\eta$ = 电池 BOL 效率
- $\alpha$ = 温度系数

### 辐射散热 (Stefan-Boltzmann)
$$Q_{rad} = \varepsilon \cdot \sigma \cdot A \cdot F \cdot (T_{surf}^4 - T_{space}^4)$$

- $\sigma = 5.67 \times 10^{-8}$ W/m²K⁴
- $T_{space} = 2.7$ K (CMB)
- $F$ = 视角因子 (~0.9)

### 电池 SOC
- **Eclipse**: $SOC -= \frac{P_{compute}}{1400} \times 0.85 \times \Delta t$
- **Sunlit**: $SOC += 1.25 \times \Delta t$ (if surplus solar)

---

## 🏗️ 架构特色

### 三层解耦

```
┌──────────────────────────────────────┐
│  UI Layer (omni.ui)                  │  dt_panel, hud, telemetry, trend
├──────────────────────────────────────┤
│  Scene Layer (USD / pxr)             │  earth, satellite, environment
├──────────────────────────────────────┤
│  Physics Layer (pure Python)         │  orbital, solar, thermal, battery
└──────────────────────────────────────┘
```

- **Physics 层** 完全不依赖 USD / omni.ui，可独立测试
- **Scene 层** 仅依赖 pxr (OpenUSD)
- **UI 层** 仅依赖 omni.ui

### 单一状态源 (SimState)

所有可变状态集中在 `SimState` dataclass 中，取代 JS 版的全局 `let` 变量。

---

## 🔮 未来增强 (Phase 2+)

- [ ] MDL 材质 (金箔 MLI、太阳能电池、散热器涂层)
- [ ] HDRI 星空环境球
- [ ] 体积大气散射
- [ ] OmniGraph 数据流节点
- [ ] Isaac Sim GNC (姿态控制) 集成
- [ ] VR/AR 沉浸式视图
- [ ] Omniverse Nucleus 多人协作
- [ ] Omniverse Cloud Streaming
