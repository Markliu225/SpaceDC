# STK 11 对标管线 · 轨道 / 电源 / 热控

以本机 **STK 11.6**（Engine 无头 COM，含 SEET）为真值，对 `backend/` 仿真引擎的
轨道、电源、热控三模块做数值对标。测试用例与验收阈值对齐
`C:\Workspace\SpaceDC\Orbit\2. Test Report...docx`（NTU SDCTwin 轨道动力学模块
测试报告——其判据为 "The STK results are taken as the true value"）。
详细规划见 [PLAN.md](PLAN.md)。

> 📊 图文版对标报告（前后对比曲线 + NTU 集成路线）：`out/report.html`
> （由 `gen_plot_data.py` 提取图表数据后生成）

## 结果（2026-08-24）

| 轮次 | 通过 | 说明 |
| --- | --- | --- |
| 基线（修正前） | **5 / 52** | 仅 SGP4 传播本身达标（与 STK 机器精度一致） |
| 修正后 | **51 / 51** | 三模块全部达标 |

基线病灶与修正（全部落在 `backend/`，新增 `services/geodyn.py`）：

| 病灶 | 基线误差 | 修正 | 修正后 |
| --- | --- | --- | --- |
| GMST(0)=0 线性近似 + 球体地心纬度 | 经度差 151°、纬度 0.18°、高度 21 km | IAU-82 GMST + WGS-84 椭球迭代 | ≤1×10⁻⁷ ° / ≤5×10⁻⁹ km |
| 太阳=写死场景灯光向量 | 方向差 141° | Vallado 解析平根数太阳历 | ≤0.02°（β 角 ≤0.003°） |
| 地影=半球判据（恒 50% 蚀率） | LEO 差 12 pp、GEO 全错 | 圆锥本影/半影视圆盘遮挡分数 | 占比差 ≤0.08 pp、事件时刻 ≤4.8 s |
| 球面余弦仰角、纬度混用 | 接入窗口零配对 | WGS-84 ECEF/ENU 仰角 | 窗口起止差 ≤1.0 s、零漏报误报 |
| 太阳能固定 1361 无日地距/蚀分数 | 24h 能量差 16–47% | S₀/d²·入射·蚀分数 | ≤0.4% |
| 热模型无太阳/反照/地球红外（T_bg=250 K 魔数） | 地影段温差 40 K | α·S·A/4 + 反照 + 地球红外（球-地视因子），材料表补 α 列 | SEET 分段均温差 ≤0.4 K |
| 下行可见性 = sin(t/30) 占位 | 非几何 | 真实仰角掩模判据（默认新加坡/X 波段） | 与 Coverage 分析同源 |

## 用法

```powershell
# 1. STK 真值导出（系统 Python + pywin32；首次需 makepy 生成类型库）
python -m win32com.client.makepy "AGI STK Objects 11"   # 一次性
python stk_ref.py                                        # → out/stk/

# 2. 我方引擎同场景导出（backend venv）
..\..\backend\.venv\Scripts\python.exe ours_ref.py       # → out/ours/

# 3. 对齐、判分、出报告
..\..\backend\.venv\Scripts\python.exe compare_report.py # → out/REPORT.md + summary.json
```

场景与参数唯一权威源是 `cases.py`（TLE 与引擎目录同源、时间轴 = 引擎 DEMO 历元、
新加坡站、0/5/10/20° 掩模、SEET 同参数球模型）。改引擎物理后只需重跑 2、3 步
（STK 真值不变）。基线证据保留在 `out/REPORT_baseline.md`。

## 对标矩阵 → NTU 用例映射

B1→OD-003(SGP4)，B2→CV-003(ECI2ECEF)，B3→SE-001/003(太阳/β)，B4/B6→SE-004(蚀/强度)，
B7→SE-005(功率)，B5→AC-001(接入)，B8 电池、B9/B10 热（SEET）为本管线扩展项。

## 已知边界（记录在案，不影响判定）

- 地影用球形地球（无扁率）：SSO 高纬蚀边沿差 ~4-5 s（STK 用椭球阴影）；
  NTU 参考实现同样用球形赤道半径。
- 仰角无大气折射修正（STK 默认也关闭折射时口径一致）。
- `dawn_dusk_sso` 预设仍强制永久日照（产品演示叙事，非物理路径）。
- STK "SEET Vehicle Temperature" 是稳态平衡模型；我方引擎带 160 kJ/K 热容瞬态,
  对标时比较的是我方公式的逐时平衡温度（同一热流项）。
