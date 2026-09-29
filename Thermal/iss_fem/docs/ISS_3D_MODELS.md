# 国际空间站公开三维模型梳理与部件布局提取

本文件记录公开三维模型的检索、下载、解析与坐标换算结果，用于在 COMSOL 中按原生体素搭建全站几何时读取各部件的相对位置。COMSOL 许可不含 CAD 导入模块，三维模型只用来读取部件包围盒与安装位置，几何本身用圆柱、方块与薄板重建。

坐标系统一为国际空间站分析坐标系：X 沿实验舱轴线指向飞行方向，Y 沿桁架指向右舷，Z 指向天底，原点在 S0 桁架段几何中心并位于桁架中心线上。长度单位为米。

## 阶段1 候选模型检索与下载

完成时间 2026-09-30。

### 1.1 候选清单

| 编号 | 来源与作者 | 格式与大小 | 部件命名 | 构型年代 | 处理结论 |
|---|---|---|---|---|---|
| A | NASA-3D-Resources 库 3D Models 目录 A 号模型，NASA Ames | GLB，39708 字节 | 只有一个名为 ISS 的网格 | 页面未注明 | 过于简化，不采用 |
| B | 同库 B 号模型，NASA Michael D. Carbajal | GLB，476992 字节 | 11 个节点，名称为 isscombine、bendedtrus 等建模软件默认名 | 页面未注明 | 无法对应部件，不采用 |
| C | 同库 C 号高分辨率模型，NASA JSC Visual Communications Lab | LightWave 9 场景与物体文件，7z 包 24793851 字节，解压后 88 MB | 场景 91 个条目，按舱段与桁架段分文件，物体表面名区分 PVR 面板 iearad、主散热器面板 tcsrad、太阳电池 pan-cels | 说明文件写明为 2011 年规划的装配完成构型，文件日期 2011 年 2 月 | 目标构型参考，已下载解析 |
| D | 同库 D 号 IGOAL 模型，NASA JSC Integrated Graphics, Operations, and Analysis Laboratory，页面日期 2026 年 5 月 20 日 | GLB 95875648 字节，网格为 Draco 压缩；另有 FBX 的 7z 分卷共 144487381 字节 | 588 个节点，按元件命名，含 SARJ、BGA、TRRJ 关节节点，根节点名为 SSREF_IGOAL | 2026 年现役构型，含 iROSA、BEAM、Bishop、Nauka、Prichal | 主几何来源，已下载解析 |
| E | 同库 E 号舱内模型 | 7z 分卷共 303774173 字节 | 舱内设备 | 无外形布局信息 | 不下载 |
| VTAD | science.nasa.gov 发布的 ISS_stationary.glb，NASA Visualization Technology Applications and Development，2019 年 4 月 22 日发布 | GLB 44495916 字节，另有 USDZ 15.97 MB | 132 个节点，按装配序号命名，例如 16 S1 Truss | 约 2015 至 2019 年混合状态，PMM 仍在节点1 天底口，含 2019 年上站的 OCO-3 | 第三方核对，已下载解析 |
| Sketchfab 转载 | 用户转载的 NASA JSC 与 VTAD 模型，CC BY 4.0 | 需登录下载 | 与上面同源 | 同源模型 | 不下载 |
| 商业 CAD 站点 | 3dcadbrowser 等站点的 STEP 与 IGES 模型 | 付费 | 非一手资料 | 未注明 | COMSOL 无 CAD 导入模块，不采用 |

许可情况：NASA-3D-Resources 库说明写明 "These assets are free and without copyright"；C 号模型说明文件要求在成果上注明 NASA 署名。

公开有限元模型：检索 NTRS 与公开网络未找到可下载的国际空间站 NASTRAN 或其他结构有限元模型文件。NTRS 上的结构动力学论文只给出模型描述，不附模型文件；本机访问 NTRS 下载接口返回 403。

### 1.2 链接

| 编号 | 地址 |
|---|---|
| A | https://github.com/nasa/NASA-3D-Resources/tree/master/3D%20Models/International%20Space%20Station%20%28ISS%29%20%28A%29 |
| B | https://github.com/nasa/NASA-3D-Resources/tree/master/3D%20Models/International%20Space%20Station%20%28ISS%29%20%28B%29 |
| C | https://github.com/nasa/NASA-3D-Resources/tree/master/3D%20Models/International%20Space%20Station%20%28ISS%29%20%28C%29%20%28High%20Res%29 |
| C 说明页 | https://science.nasa.gov/3d-resources/international-space-station-iss-c-high-res/ |
| D | https://github.com/nasa/NASA-3D-Resources/tree/master/3D%20Models/International%20Space%20Station%20%28ISS%29%20%28D%29%20%28IGOAL%29 |
| D 说明页 | https://science.nasa.gov/3d-resources/international-space-station-iss-d-igoal/ |
| VTAD | https://science.nasa.gov/resource/international-space-station-3d-model/ |
| VTAD 文件 | https://assets.science.nasa.gov/content/dam/science/psd/solar/2023/09/i/ISS_stationary.glb |

### 1.3 下载与解析方法

模型文件体积大，保存在会话临时目录，不进仓库。仓库 docs/iss3d 目录保存解析脚本与结果表，把 C 号 7z 包解压到脚本同目录的 C_HighRes 子目录、两个 GLB 分别命名为 ISS_stationary_VTAD.glb 与 ISS_D_IGOAL.glb 后即可复现。

| 文件 | 作用 |
|---|---|
| iss3d/lwo2.py | LightWave LWO2 物体读取，按图层取顶点，按多边形标签取表面分组 |
| iss3d/extract_bbox.py | 读取 LightWave 场景的父子层级、位置、HPB 转角、缩放与枢轴点，读取 GLB 节点变换并解压 Draco 网格，输出每个节点或条目在世界坐标下的轴对齐包围盒 |
| iss3d/parts_bbox.csv | 1397 行，含三套模型全部节点的原始坐标包围盒与换算到分析坐标系后的中心与尺寸 |

Python 环境为独立虚拟环境，安装 numpy、trimesh、pygltflib、DracoPy、py7zr、scipy。LightWave 场景按 HPB 顺序构造转动矩阵，子条目位置按父条目物体坐标解释；机械臂各段位置与各自枢轴点逐一重合，验证了这一解释。

### 1.4 坐标轴与尺度判定

各模型的轴向由相互独立的实物安装关系逐轴确定：S 桁架、哥伦布舱、Quest 气闸在右舷，节点2 位于实验舱前方且俄罗斯舱段在后方，穹顶舱与 PMM 在节点下方而 Z1 桁架在节点1 上方。三条轴分别由不同事实确定，换算结果不存在镜像。

| 模型 | 原始坐标 | 单位 | 换算关系 | 原点 |
|---|---|---|---|---|
| C | 场景空节点 ISS PIVOT 的物体坐标，LightWave 左手系，+X 向前，+Y 右舷，+Z 天顶 | 英寸 | X = x，Y = y，Z = -z，乘 0.0254 | 原生原点即 S0 中心，桁架各段关于 X = 0、Z = 0 对称 |
| D IGOAL | 根节点 SSREF_IGOAL 的子空间，a 向前，b 向天底，c 向左舷 | 英寸 | X = a，Y = -c，Z = b，乘 0.0254 | 原生原点即 S0 中心，Truss_S0 沿 c 向为 -264.1 至 264.1 英寸 |
| VTAD | glTF 世界坐标，+z 向前，-x 右舷，+y 天顶 | 米 | X = z，Y = -x，Z = -y，再做相似变换拟合 | 按 19 个桁架段与舱段中心对 IGOAL 做最小二乘拟合，比例 0.9580，平移 -4.550、0.006、4.887 m，残差均方根 0.43 m |

IGOAL 根节点带 -0.00258 的均匀负缩放，只用于网页浏览，直接使用其世界坐标会得到镜像的空间站，解析时去掉了根节点变换。

尺度核对采用 NASA 官网公布尺寸：

| 核对项 | 模型值 | 公布值 | 出处 |
|---|---|---|---|
| 太阳翼端到端宽度 | C 模型外侧太阳翼外缘 Y = ±54.31 m，总宽 108.63 m；IGOAL 按太阳翼展平推算 108.3 m | 356 ft，即 109 m | NASA Space Station Facts and Figures 页面 |
| 同一光伏模块两翼总长 | IGOAL 的 P4 两翼 X 由 -36.65 至 35.95 m，共 72.60 m；C 模型 75.07 m | 239 ft，即 73 m | 同上 |
| Destiny 长度与直径 | C 模型壳体含两端封头 8.32 m，直径 4.42 m；IGOAL 包围盒 9.07 m，含对接环，直径 4.43 至 4.45 m | 28 ft 与 14 ft，即 8.53 m 与 4.27 m | NASA Destiny Laboratory Module 页面 |
| S0 桁架段长度 | IGOAL 13.42 m，C 模型 13.24 m | 未另行查证 | 无 |
| 桁架总长 | IGOAL 由 P6 外端 -48.80 m 至 S6 外端 48.73 m，共 97.53 m；C 模型 98.05 m | 310 ft，即 94 m | NASA Space Station Facts and Figures 页面 |

前三项与公布值相差 3% 以内，确认 C 与 IGOAL 的单位为英寸。桁架总长模型值比官网值长 3.7%，两套独立模型结果一致，官网 94 m 的计量口径未说明，建模时以模型为准并在报告中注明。
