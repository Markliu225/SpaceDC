# 开源实现调研与选型记录

## 采用

| 项目 | 用途 | 选用原因 |
|---|---|---|
| [python-sgp4](https://pypi.org/project/sgp4/) | SGP4/SDP4 | MIT；直接编译 Vallado 官方 C++ 版本；提供官方验证数据；明确返回 TEME |
| [Astropy](https://docs.astropy.org/en/stable/coordinates/) / ERFA | 时间、太阳/月球、GCRS/ITRS/TEME | BSD；参考系语义明确；支持 EOP 和速度转换；内置太阳模型可离线运行 |
| [SciPy solve_ivp](https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.solve_ivp.html) | 轨道/姿态/热积分 | BSD；DOP853 适合低容差非刚性高精度积分 |
| [SciPy Rotation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.transform.Rotation.html) | YPR/Euler | 明确区分大小写表示的内禀/外禀序列，并处理奇异警告 |
| [ICGEM](https://icgem.gfz.de/tom_longtime) EGM2008 | 高阶地球重力系数 | 官方 `gfc` 数据源；完全归一化、tide-free，随包保留到 120×120，并记录来源与 SHA-256 |

## 评估但未作为核心依赖

| 项目 | 结论 |
|---|---|
| [TudatPy](https://py.api.tudat.space/en/latest/dynamics/propagation_setup.html) | 力模型和多体传播非常完整，适合作为后续“定轨级 HPOP 后端”；但运行时、环境和 SPICE 数据体量明显高于当前可嵌入包，因此不作为最小核心依赖 |
| [Basilisk](https://avslab.github.io/basilisk/) | 适合复杂航天器 GNC/软硬件闭环，Python 驱动 C/C++；当前需求更偏轻量批量轨道/Access 服务，不直接引入 |
| [poliastro](https://github.com/poliastro/poliastro) | API 设计和 Cowell 思路有参考价值，但上游仓库自 2023-10-14 起归档只读，不宜成为新工程核心依赖 |
| [Skyfield](https://rhodesmill.org/skyfield/earth-satellites.html) | SGP4 与天文时间接口友好；当前已由 python-sgp4 + Astropy 覆盖，并需要统一到 GCRS/ITRS 数据契约，故未重复引入 |

## 用户参考代码吸收情况

- `D:/MyCode/HPOPforc/`：保留了 `area/mass`、`Cd`、`Cr`、日/月三体、光压和相对论等配置概念；去除了硬编码磁盘 EOP 路径和末行单位不一致风险。
- `D:/MyCode/Access/`：保留了“视场 ∩ 地球无遮挡”和 VVLH 的 pitch/roll 定义；把固定 86400 s、线性状态插值和可能漏掉短窗口的自适应逻辑改为任意场景时长、Hermite 状态插值、固定扫描尺度与根求解边界细化。
- `E:/MyProject/计算Beta角/SunLight/SunLightProjection.py`：保留了解析太阳和轨道面投影思想；修复了圆轨道/赤道轨道根数奇异问题，并把 MOD 与 GCRS 参考系显式区分。

工程没有复制上述第三方项目的源代码；运行时依赖遵循各自许可证。Vallado SGP4 验证向量用于测试实现接口是否保持官方结果。
