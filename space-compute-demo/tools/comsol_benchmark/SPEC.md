# COMSOL 热对比规格

目的是用 COMSOL Multiphysics 传热模块的 Orbital Thermal Loads 接口作为第二个独立参照，检验我方热模型两件事。第一，环境热流与单节点温度是否与商业软件一致，这一层 STK SEET 已经通过，COMSOL 再给一个独立参照。第二，集总假设的误差有多大，即带传导的辐射板上热点与板均温相差多少，这一层此前没有参照。

需要 COMSOL 6.1 或更高版本，含 Heat Transfer Module。建议先打开应用库里的两个模板熟悉接口，Heat Transfer Module 下的 Orbit Thermal Loads 与 Spacecraft Thermal Analysis。

## 一、公共设置

| 项 | 值 | 说明 |
| --- | --- | --- |
| 历元 | 2024-08-22 12:00:00 UTC | 与 STK 基准同一时间轴 |
| 时长与输出步长 | 86400 s，每 60 s 输出 | 与参考序列对齐 |
| 轨道 | 见 out/ref/orbit_elements.json | 历元密切根数，a 6801.4 km，e 0.00169，i 51.660°，RAAN 100.000°，ω 59.921°，ν 299.911° |
| 太阳常数 | 1361 W/m² 于 1 AU | COMSOL 默认可能是 1367，改为 1361。若软件按日期自算日地距离，保持自算 |
| 地球反照率 | 0.30，均匀 | 关闭随经纬度变化 |
| 地球红外 | 237 W/m²，均匀 | 关闭随经纬度变化 |
| 地球半径 | 6371 km | 视因子用 |
| 深空温度 | 3 K | 与我方 0 K 近似差异可忽略 |
| 材料 | 铝，k 237 W/(m·K)，ρ 2700 kg/m³，cp 900 J/(kg·K) | COMSOL 内置 Aluminum 的 k 为 238，可直接用 |

轨道说明。COMSOL 用开普勒根数做两体或 J2 传播，与 SGP4 在 24 小时内的地影时刻会有数十秒偏差，因此对比按光照段与地影段的均值进行，不比逐时刻。out/ref/stk_lighting_leo.csv 给出 STK 的本影半影区间，可用来核对 COMSOL 的地影判断是否在同一相位。

## 二、用例 T1，等温铝壳球

与 STK SEET 基准完全相同的参数，三方对照。

| 项 | 值 |
| --- | --- |
| 几何 | 球壳，半径 1.784 m，横截面 10 m²，表面积 40 m²，壳厚 2 mm |
| 涂层 | 吸收率 0.25，发射率 0.85，整个外表面 |
| 内部耗散 | 2850 W，均匀体热源分布在壳体 |
| 姿态 | 任意，球对称 |
| 初始温度 | 265.6 K，即我方 t=0 的平衡温度 |
| 热容 | 194.4 kJ/K，由几何与材料自动得到 |

导出量。体平均温度 T_mean，以及 Orbital Thermal Loads 给出的三项吸收功率，太阳直射、反照、地球红外，单位 W，对整个外表面积分。

## 三、用例 T2，对地指向铝辐射板

检验集总假设。

| 项 | 值 |
| --- | --- |
| 几何 | 平板 2.0 m × 1.0 m × 3 mm，长边沿飞行方向 |
| 姿态 | 对地指向，板法线沿天底方向，一面朝地一面朝天顶 |
| 涂层 | 两面均为光学太阳反射镜，吸收率 0.08，发射率 0.92 |
| 热源 | 1000 W，均匀体热源分布在板中央 0.2 m × 0.2 m 的方块内，贯穿厚度 |
| 面面辐射 | 打开 Surface-to-Surface Radiation，两面向深空辐射 |
| 初始温度 | 293.4 K，即我方 t=0 的平衡温度 |
| 热容 | 14.58 kJ/K |

导出量。板体平均温度 T_mean，板最高温度 T_max，板最低温度 T_min，以及朝天顶面与朝地面各自的三项吸收热流密度，单位 W/m²。

我方参考里对这块板的处理与引擎一致，即整板一个温度，两面辐射，太阳与反照按各面法线与太阳方向的余弦计算，地球红外只作用于朝地面，视因子取 (R/r)²。T_max 与 T_mean 的差是集总模型看不见的量，也是这个用例要得到的结论。

## 四、COMSOL 建模步骤

以下按 6.2 与 6.3 的界面写，控件名称以软件实际标签为准。

1. Model Wizard，3D，物理场选 Heat Transfer in Solids，添加 Surface-to-Surface Radiation，添加 Orbital Thermal Loads，研究选 Time Dependent。
2. Global Definitions 中定义参数，S0 1361，albedo 0.30，q_ir 237，P_T1 2850，P_T2 1000，材料参数如上。
3. Geometry。T1 用球壳，可用两个同心球做差或直接用 Shell 接口，T2 用长方体 2 × 1 × 0.003 m，并在中央用另一个长方体 0.2 × 0.2 × 0.003 m 划出热源域。
4. Materials，铝，赋给全部域。
5. Orbital Thermal Loads 设置。行星选 Earth，半径 6371 km，反照率 0.30，红外 237 W/m²，均匀。太阳辐照 1361 W/m²。轨道输入开普勒根数与历元，见 orbit_elements.json。姿态 T1 任意，T2 选对地指向并把板法线对准天底。在辐射属性中给每个外边界设置吸收率与发射率。
6. Heat Transfer in Solids。热源用 Heat Source 节点，选择热源域，总功率 P 按域体积换算成体热源密度，或直接用 Total power 选项。
7. Surface-to-Surface Radiation。外表面全部设为漫射面，环境温度 3 K。T2 的两面都要包含。
8. Initial Values，按用例给的初始温度。
9. Mesh，T1 用 Normal，T2 在热源域附近加密，板厚方向至少两层单元。
10. Study，Time Dependent，range(0, 60, 86400)，求解器容差保持默认，若不收敛把最大步长限制在 60 s。
11. Results。Derived Values 下建 Global Evaluation，表达式 aveop 得到体平均温度，maxop 与 minop 得到极值，表达式需要先在 Definitions 下定义体平均与极值算子并选择板域。热流用 Orbital Thermal Loads 接口的吸收热流变量对边界做 Surface Integration，变量名在接口的 Equation View 中查看。全部量放进同一张 Table，Export 为 CSV。

## 五、导出文件约定

放到 out/comsol/t1.csv 与 out/comsol/t2.csv。COMSOL 导出的表头以 % 开头，脚本可直接读取。列按关键词识别，不区分大小写。

| 量 | 列名中需包含 | 单位 |
| --- | --- | --- |
| 时间 | time 或 t | s |
| 体平均温度 | mean 或 avg | K |
| 最高温度 | max | K |
| 最低温度 | min | K |
| 太阳直射吸收 | sun 或 solar | T1 为 W，T2 为 W/m² |
| 反照吸收 | albedo | 同上 |
| 地球红外吸收 | ir 或 infrared 或 planet | 同上 |

温度列必须有，热流列可选。T2 若能分面导出，朝天顶面与朝地面各导一组，列名里带 zenith 与 nadir。

## 六、判据

| 用例 | 指标 | 门限 |
| --- | --- | --- |
| T1 | COMSOL 与我方集总温度的光照段、地影段均值差 | 不超过 2 K |
| T1 | 由 COMSOL 三项吸收热流反推的平衡温度与 STK SEET 的分段均值差 | 不超过 2 K，需要导出三项热流。COMSOL 瞬态温度与 SEET 稳态温度之差含热容滞后，只作参考不判定 |
| T1 | 太阳直射吸收功率相对误差 | 不超过 2% |
| T1 | 反照与地球红外吸收功率相对误差 | 各不超过 10% |
| T2 | COMSOL 板均温与我方集总温度的分段均值差 | 不超过 5 K |
| T2 | 热点与板均温之差 | 报告值。超过 10 K 说明集总模型需要增加冷板节点 |

## 七、运行

```powershell
# 生成我方参考序列与轨道根数，backend venv
..\..\backend\.venv\Scripts\python.exe gen_reference.py
# COMSOL 导出 CSV 放入 out\comsol 后判分，任意 Python
python compare_comsol.py
```

报告写到 out/REPORT.md，判定明细在 out/summary.json。
