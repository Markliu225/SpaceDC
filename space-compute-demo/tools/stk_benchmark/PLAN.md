# STK 11 对标规划 · 轨道 / 电源 / 热控三模块

> 目标：以本机 **STK 11.6（Engine 无头 COM 自动化，含 SEET）** 为真值，对我方仿真引擎
> （`space-compute-demo/backend`）的 **轨道、电源、热控** 三个模块做数值对标；
> 凡同功能下我方结果不达标的，修正引擎物理，复跑对比直至收敛。
> 测试方法与验收阈值对齐 `C:\Workspace\SpaceDC\Orbit\2. Test Report...docx`
> （NTU SDCTwin 轨道动力学模块测试报告，其判据均为 "The STK results are taken as the true value"）。

## 0. 环境结论（已验证）

| 项 | 结论 |
| --- | --- |
| STK 版本 | STK 11.6.0 x64，安装于 `D:\Program Files\AGI\STK 11\` |
| 无头引擎 | `STKX11.Application` + `AgStkObjects11.AgStkObjectRoot` COM，许可证有效，可建场景/卫星/地面站 |
| TLE 加载 | Connect `SetState ... TLE ... TimePeriod ...`（必须显式给 TimePeriod，否则星历只从 TLE 历元开始） |
| 数据提供器 | Cartesian Position/Velocity（TEMEOfDate）、LLA State（WGS84 大地 + 地心纬度）、Lighting Times（本影/半影）、Solar Intensity、Beta Angle、Sun Vector、Access AER |
| SEET 热 | **有许可证**。`SEET Vehicle Temperature`：单节点等温稳态平衡（太阳直射+地球反照+地球红外+内部耗散）；参数经 Connect `SEET ... VehTemperature` 配置（α、ε、反照率、横截面积、耗散功率、球/板模型） |
| COM 绑定 | 需 `makepy "AGI STK Objects 11"` 完整生成 + `CastTo`（接口名带 `_` 前缀，如 `_IAgScenario`） |

## 1. 统一场景

- **时间轴**：2024-08-22 12:00:00 UTC（= 引擎 `DEMO_JD0`）起 24 h，采样 60 s；
  接入分析事件沿我方侧以 1 s 密采求根。
- **TLE 用例**（与引擎 `services/orbit_catalog.py` CATALOG 完全同源，喂给 STK 前仅修正校验位）：
  `leo_iss`（51.6°/420 km）、`sso_landsat`（98.2°/705 km）、`geo_goes`（GEO）。
- **地面站**：Singapore 1.3521°N / 103.8198°E / 0 m，仰角掩模 0° / 5° / 10° / 20°（对齐 NTU AC-001 + 波段掩模）。
- **电/热参数**（双侧配平）：η=0.32(GaAs)、A_solar=30.07 m²（baseline 4 簇/侧）、S₀=1361 W/m²；
  电池 8000 Wh / 充电效率 0.95、负载 = 2400 W(载荷)+600 W(平台)；
  热：球模型 A_cross=10 m²、α=0.25 / ε=0.85（白漆）、耗散 2850 W（=3000×0.95）、C_th=160 kJ/K。

## 2. 对标矩阵（用例 → NTU 判据 → 预期）

| # | 模块 | 对标量 | STK 真值来源 | NTU 用例/阈值 | 我方现状（代码调研结论） | 预期 |
| --- | --- | --- | --- | --- | --- | --- |
| B1 | 轨道 | TEME 位置/速度 | Cartesian Position/Velocity·TEMEOfDate | OD-003：≤0.001 km / 1e-6 km/s | 同为 Vallado SGP4（`sgp4` 2.25） | ✅ 应过 |
| B2 | 轨道 | 星下点 lat/lon/alt | LLA State·Fixed | CV-003 精神；门限 lat/lon ≤0.02°、alt ≤1 km | 球体+地心纬度+GMST(0)=0 线性近似 | ❌ 经度常差~160°、纬度~0.19°、alt~21 km |
| B3 | 轨道 | 太阳方向角差 / β 角 | Sun Vector·TEMEOfDate / Beta Angle | SE-001 ≤0.5° / SE-003 ≤0.01° | 太阳=硬编码固定向量，无历表 | ❌ 随季节漂移可达数十度 |
| B4 | 轨道 | 本影进出时刻/蚀弧占比 | Lighting Times·Umbra/Penumbra | 事件时刻 ≤15 s、占比差 ≤1% | 半球判据：恒 50% 蚀率 | ❌ LEO 真值~37%；GEO 全错 |
| B5 | 轨道 | 接入窗口(掩模 0/5/10/20°) | Access + AER Data | AC-001：起止 ≤1.0 s、时长 ≤2.0 s、边界仰角 ≤0.01° | 球面余弦仰角、混用地心/大地纬度、无站高 | ❌ 窗口边沿偏移预计数十秒 |
| B6 | 电 | 光照因子/太阳强度 | Solar Intensity | SE-004：强度 0.1%、因子 0/1 正确 | sunlit 由 B4 驱动 | ❌ 随 B4 |
| B7 | 电 | P_solar(t)（对日/对地姿态） | 由 STK 光照×几何合成 η·A·S·illum·cosθ | SE-005：0.5% | 公式同构但输入几何错 | ❌ 能量/轨差异大 |
| B8 | 电 | SOC 轨迹/地影 DoD | 我方积分器灌 STK 真值功率 vs 灌我方功率 | 派生指标：DoD 相对差 | 记账正确、驱动错 | ❌ 随 B7 |
| B9 | 热 | 在轨温度序列（光照/地影稳态） | SEET Vehicle Temperature（同参数球模型） | 光照/地影段均值差目标 ≤10 K | Q_in 无太阳/反照/地球红外，无 α；T_bg=250 K 常数 | ❌ 光照段严重偏低 |
| B10 | 热 | 三项环境热流 | SEET Solar Flux 通道 + 解析公式 | 各项 ≤5% | 全部缺失 | ❌ |

## 3. 管线（本目录）

```
cases.py          用例与参数唯一权威源（TLE、时间轴、地面站、电热参数）
stk_ref.py        STK COM 驱动：建场景→逐用例导出真值 CSV（out/stk/）
ours_ref.py       用 backend .venv 解释器 import 引擎模块，同时间轴导出同 schema CSV（out/ours/）
compare_report.py 对齐两侧 CSV，算误差统计与 PASS/FAIL，生成 out/REPORT.md
```

约定：两侧 CSV 首列均为 `t`（自场景起点的秒），角度 deg、距离 km、温度 K、功率 W。

## 4. 修正阶段（按对比结果逐项，改一项复跑一轮）

预定修正清单（全部在 `backend/`，公式参考 `Orbit/src/ntu_space_dynamics` 与 Vallado）：

1. **太阳历**：解析平根数太阳位置（MOD→TEME 足够，0.01° 级），替换固定 `SUN_DIR_ECI`；
2. **地影**：圆柱→圆锥本影/半影蚀分数（NTU `solar.py:eclipse_fraction` 同式），替换半球判据；
3. **星下点**：GMST 用 IAU-82 多项式 + 真实历元，WGS84 椭球迭代大地纬度/高度；
4. **仰角/接入**：ECEF 向量法（站大地坐标→ECEF，视线与站法向夹角），替换球面余弦近似；
5. **热**：Q_in 增加 α·S·A_abs·illum（太阳）+ 反照 + 地球红外（视因子随高度），
   材料表补 α 列，去掉 T_bg=250 K 魔数；
6. 复跑 `tools/validate_*.py` 全部既有验证器 + 本对标管线，两侧全绿才算收敛。

不修正（与对标无关的既有设计决策）：TIME_SCALE=60 演示加速、1 Hz tick、集总单节点热容、EPS/LLM 模型。
