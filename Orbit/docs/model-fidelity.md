# 模型精度与数据契约

## 单位、时间和坐标系

公共接口仅使用 SI。`datetime` 必须包含时区；UTC 可写为 `tzinfo=timezone.utc`。数值外推初值必须为 GCRS，SGP4 原生结果为 TEME，地固结果为 ITRS。`transform_ephemeris()` 同时转换位置和速度，避免遗漏地球自转产生的速度项。

Astropy 的 GCRS/ITRS 转换依赖 UT1-UTC、极移和闰秒数据。工程在默认情况下禁止自动联网，使用运行环境已有的 IERS 表；超出表有效期时 Astropy 会发出降精度警告。生产部署应把受控版本的 IERS Bulletin A/B 数据作为任务输入归档。

## 轨道模型

- `TwoBodyPropagator`：仅中心引力，适合算法基线、短时初始化和单元测试。
- `J2Propagator`：中心引力与 J2，适合解释主要节点/近地点长期漂移，不包含阻力和三体摄动。
- `SGP4Propagator`：只用于 TLE/OMM 平均根数语义；输出 TEME。不要把瞬时经典根数直接塞进 SGP4，也不要用 HPOP 初值与 TLE 在同一时刻逐项比较后推断实现错误。
- `HighPrecisionPropagator`：DOP853 Cowell 积分，可组合力模型。默认地球重力为 EGM2008 70×70（随包可用到 120×120），星历每 900 s 取样并用三次样条共享给日/月三体和 SRP；轨道积分仍按自适应步长执行。

当前 HPOP 的限制：

1. 静态地球非球形引力支持完全归一化 ICGEM `gfc`，内置 EGM2008 tide-free 系数到 120×120；默认求和到 70×70，可通过 `gravity_degree` / `gravity_order` 调整，或传入 GRACE 等静态系数；
2. 阻力使用静态分段指数大气，不响应 F10.7、F10.7a、Ap/Kp；
3. SRP 为 cannonball 模型，不含复杂几何、自遮挡和红外/反照率；
4. 日月星历默认使用 Astropy `builtin`，可切换到受控的本地 JPL kernel；
5. 不含固体潮、海潮、极潮、时变重力系数、相对论框架完整项、推力事件和参数估计。GRACE 月解或 ICGEM `gfct/trnd/asin/acos` 记录须先归算到任务历元再加载。

高阶重力在 ITRS 中计算。GCRS→ITRS 旋转由 Astropy/ERFA 和本地 IERS 数据生成，并以 300 s 节点做球面线性插值；因此系数文件、EOP/IERS 表、截断阶次和潮汐系统都属于可复现实验输入。内置数据的来源与 SHA-256 见 [`data/gravity/README.md`](../src/ntu_space_dynamics/data/gravity/README.md)。

因此，“HPOP”表示高阶自适应数值外推架构，不代表一个不声明数据源和力模型的固定精度等级。

## OE/RV 奇异情况

经典根数在圆轨道和赤道轨道上数学奇异。`rv_to_oe()` 采用以下固定约定：

- 圆倾斜轨道：近地点幅角设为 0，`anomaly_rad` 返回纬度幅角；
- 偏心赤道轨道：RAAN 设为 0，近地点幅角返回近地点经度；
- 圆赤道轨道：RAAN 与近地点幅角都设为 0，`anomaly_rad` 返回真经度。

这保证 OE→RV→OE→RV 可复现状态，但不应把这些占位角解释为可观测的物理方向。

## 太阳与功率

解析太阳模型原生输出日期平赤道/平春分点（MOD），选择 GCRS 时会进行岁差和参考系转换。星历模型默认使用 Astropy 离线内置星历；传入本地 JPL kernel 时需要安装 `jplephem`。

`eclipse_fraction()` 计算从航天器看到的太阳圆盘可见比例，输出 0–1，因此半影区可以连续作用于太阳强度、功率和 SRP。

热功率是单节点模型：吸收热 = 入射太阳能 × 吸收率 − 电功率；散热使用对深空的 Stefan–Boltzmann 辐射。不含结构传导、地球红外、反照率或电池/MPPT 动态。

## Access

当前 Access 面向固定 WGS-84 地面点和固定 VVLH 传感器：

- 地球遮挡用目标点局部地平高度角表达；
- 视场用目标视线与传感器波束中心夹角表达；
- 可选最大斜距；
- 轨道插值是带速度导数的三次 Hermite；
- 事件搜索先按 `scan_step_s` 扫描，再用 Brent 方法细化到 `boundary_tolerance_s`。

尚未包含地形遮挡、大气折射、星体/太阳规避、云量、姿态机动时间和载荷工作模式约束。
