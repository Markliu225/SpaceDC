# 物理模型

[English](physics.md) · **中文**

本文档说明驱动数字孪生的实时物理模型。全部逻辑位于 [`backend/state_engine.py`](../backend/state_engine.py)，运行在引擎的 tick 循环中；前端只负责展示广播出来的结果。

- **步进频率** —— `TICK_HZ = 1.0`（每个真实秒一步物理）。
- **时间加速** —— 电池与热学积分使用 `PHYS_TIME_SCALE = 60`，即 1 个真实秒推进 60 秒的相应动力学，便于演示时观察变化。轨道与负载按真实时间运行。
- **流程** —— 每个 tick 根据 (a) 轨道/太阳几何、(b) 可重配硬件载荷 `SatelliteConfig`（GPU、太阳能板/散热板**材料**）、(c) 可展开几何 `TwinGeometry`（太阳能板数量、散热板大小/比例）重新计算卫星状态，并以 5 Hz 通过 WebSocket 广播。

下文符号除特别说明外均为 SI 单位。

---

## 1. 常量

| 符号 | 取值 | 含义 |
|------|------|------|
| `S` | 1361 W/m² | 太阳常数（`_SOLAR_CONSTANT_W_M2`） |
| `σ` | 5.67×10⁻⁸ W/m²K⁴ | 斯特藩–玻尔兹曼常数 |
| `T_bg` | 250 K | 深空 + 地球红外的等效背景温度 |
| `IDLE_FRAC` | 0.15 | GPU 空闲下限（占 TDP 的比例） |
| `cards` | 8 | 每星 GPU 卡数（`_GPU_CARDS_PER_SAT`） |
| `P_platform` | 600 W | 平台 / 总线维持功耗 |
| `C_th` | 160 000 J/K | 集总热容（`THERMAL_MASS_J_PER_K`） |
| `E_batt` | 1500 Wh | 电池容量（默认；`battery_capacity_wh`） |
| `k_time` | 60 | 电池/热学时间加速（`PHYS_TIME_SCALE`） |

---

## 2. 几何 → 面积

面积由实时 `TwinGeometry` 推导，因此编辑可展开结构（功能 3）会立即改变物理量。其与 [`tools/gen_twin_satellite.py`](../tools/gen_twin_satellite.py) 中的常量一致（骨干米 → 舞台米的比例为 `1.8`）。

**太阳能板。** 一个「簇」是填满一块大面板足迹的 2×2 网格：

```
A_cluster = (0.981 · 1.45 · 1.8) · (0.777 · 1.05 · 1.8) ≈ 3.76 m²
A_solar   = 每侧簇数 · 2 · A_cluster
```

**散热板。** 两块专用 ±Z 面板，两面均散热：

```
long  = radiator_long · 1.8                       [m]
short = (radiator_long / radiator_ratio) · 1.8    [m]
A_rad = 2 板 · 2 面 · (long · short) = 4 · long · short
```

因此太阳能面积只随两侧数量增长（面板只能往两侧加），散热板面积则由其大小/比例独立决定。

---

## 3. 太阳功率（光照 → 发电）

太阳在惯性系中固定，单位方向 `ŝ = (0.648, −0.648, 0.398)`。设卫星位置为 `r`：

```
cos θ = (r · ŝ) / |r|
sunlit = cos θ > −0.05            （留出少量晨昏余量）
```

太阳翼装有对日跟踪机构（SADA），与真实在轨电源系统一致：光照期内电池片保持近法向入射：

```
incidence = 0.95  若 sunlit 否则 0     （指向/温度损耗）
incidence = 1.0   晨昏太阳同步轨道       （永不入影，恒定对日）
```

（早期版本误用 `max(0, cos θ)`——即**位置矢量**与太阳的夹角——作为板面入射率，轨道均值仅约 0.22，任何合理翼面积都无法闭合功率预算，电池长期钉死在 0%。）

`sun_factor = max(0, cos θ)` 仍导出用于驱动 Kit 主光。发电功率 = 效率 × 面积 × 辐照 × 入射率：

```
P_solar = η · A_solar · S · incidence
```

`η` 取决于所选电池材料：**Si 0.22 · GaAs 0.32 · 钙钛矿 0.38**。

---

## 4. 算力功耗（负载 → 设备功率）

GPU 利用率遵循一份确定性作业表 `_JOB_SCHEDULE`（推理 / 训练 / 下行预处理任务的固定队列，循环往复），**不是**正弦——这样用户看到的唯一变量就是自己的配置改动。日食且电量低时 GPU 降到省电下限：

```
util = schedule(t mod cycle)
若 (非 sunlit) 且 (SOC < 0.40)：util = min(util, 0.20)
```

单卡功率有空闲下限，并线性升到 TDP：

```
P_card    = TDP · (IDLE_FRAC + (1 − IDLE_FRAC) · util)
P_payload = P_card · cards
P_load    = P_payload + P_platform
```

`TDP` 与算力取自 GPU 型号：**H100 0.98 PF / 700 W · H200 1.50 / 700 · B200 2.50 / 1000 · MI300X 1.30 / 750**。

---

## 5. 电池（Wh 积分）

太阳盈余给电池充电，亏缺则放电：

```
P_net = P_solar − P_load                          (battery_charge_w)
ΔSOC  = P_net · dt · k_time / (E_batt · 3600)
SOC   = clamp(SOC + ΔSOC, 0, 1)
```

---

## 6. 热学（斯特藩–玻尔兹曼散热）

入热为耗散的电功率（约 95%，其余以射频离开）；出热为散热板面积的灰体辐射：

```
Q_in  = (P_payload + P_platform) · 0.95
Q_out = ε · σ · A_rad · (T⁴ − T_bg⁴)              (radiator_power_w, ≥ 0)
dT/dt = (Q_in − Q_out) / C_th
T     = clamp(T + dT/dt · dt · k_time, −80 °C, 95 °C)
```

`ε` 为散热涂层：**裸铝 0.10 · 白漆 0.85 · OSR 0.92 · 石墨 0.96**（裸铝是故意做差的散热面——选个涂层才能真正排热）。

---

## 7. 下行链路

简化的过境可见性模型：

```
visible = sin(t / 30) > 0.4
downlink = 可见时 120 Mbps，否则 0
```

---

## 8. 设计裕度检查

面板中展示的稳态选型检查，使用作业表的**时长加权平均**负载 `ū`：

```
P_demand_avg = [TDP · (IDLE_FRAC + (1−IDLE_FRAC) · ū) · cards] + P_platform
P_supply_avg = 0.95 · 0.5 · (η · A_solar · S)     （跟踪损耗 × 光照占比；电池需跨越夜面）
P_supply_avg = 1.0 · (η · A_solar · S)            （晨昏太阳同步轨道 — 永不入影）

Q_peak_demand = (TDP · cards + P_platform) · 0.95            （持续 100% 利用率）
Q_max_emit    = ε · σ · A_rad · (T_ceil⁴ − T_bg⁴),  T_ceil = 60 °C
```

`裕度 = 供给 − 需求`（太阳）与 `Q_max_emit − Q_peak_demand`（热）决定绿/红状态。

---

## 9. 告警

| 告警 | 条件 |
|------|------|
| `low_battery` | SOC < 0.20 |
| `overtemp` | T > 70 °C |
| `undertemp` | T < −40 °C |
| `eclipse_deficit` | 日食 **且** SOC < 0.35 **且** P_net < 0 |
| `radiator_undersized` | Q_max_emit < 0.9 · Q_peak_demand |
| `solar_undersized` | P_supply_avg < P_demand_avg |

---

## 10. 真实 vs. 简化

- **真实：** η·A·辐照·cos 的太阳发电、带空闲下限的 GPU 功率曲线、Wh 电池积分、带集总热容的斯特藩–玻尔兹曼辐射，以及几何驱动的面积——都会随配置/几何改动正确响应。
- **为可读性而简化：** 固定的惯性系太阳方向（无季节/进动）、脚本化负载轨迹（非真实调度器）、单节点集总热容（无温度梯度）、电池/热学的 60× 时间加速、以及正弦化的过境模型。数值具有代表性，但非飞行级。

---

## 11. 源码索引

| 内容 | 位置 |
|------|------|
| 全部物理 | `backend/state_engine.py` → `StateEngine` 更新 + `_solar_area_m2` / `_radiator_area_m2` / `_gpu_workload_util` |
| 硬件表 | `_GPU_TABLE`、`_SOLAR_MAT_TABLE`、`_RAD_MAT_TABLE`（state_engine.py） |
| 状态字段 | `backend/models.py` → `SatelliteState`、`TwinGeometry` |
| 配置 / 几何 API | `backend/app.py` → `/satellite_config`、`/twin_geometry` |
| 展示 | `web/src/components/twin/`（面板、`SubsystemHealthRow`、`TimeSeriesStrip`） |
