# 国际空间站桁架与转动部件公开资料核验记录

本文件记录阶段1中桁架段、SARJ、太阳翼、PVR、主散热器与 TRRJ、俄罗斯段太阳翼的公开资料检索结果。坐标系为国际空间站分析坐标系：原点在 S0 桁架段几何中心，+X 沿舱段长轴指向飞行方向，+Y 沿桁架指向右舷，+Z 指向天底。长度单位为米，质量单位为千克。每条数值后注明资料代号与页码，页码为 PDF 文件页序，资料 H 与 I 为论文集页码，资料清单见第9节。

完成时间 2026-09-30。

## 1 关键结论

1. TRRJ 转轴平行于 X 轴，不平行于桁架 Y 轴。转轴通过 Y 为 ±14.6 至 ±14.7 m、Z 约 0 的直线。三条独立证据一致：NASA 为 TopCoder 挑战赛提供的官方坐标模型及其程序用绕 X 轴的转动矩阵转动散热器，资料 T2；IGOAL 模型中 SARJ、BGA、TRRJ 三类关节节点都以本地 Z 轴为转轴，按同一约定 SARJ 本地 Z 轴对应分析系 Y 轴，BGA 对应 X 轴，TRRJ 对应 X 轴，节点位置在 Y 为 ±14.681 m、Z 为 0，资料 G；ISAG 净空分析给出 S1 散热器与 S3 天底 ELC4 上 CTC2 的最近距离出现在 gamma 为 35°，只有绕 X 轴扫掠才会在某个中间角度出现最近点，资料 I。
2. TRRJ 零位时散热器梁竖直，三个 ORU 沿 Z 上下叠放，中心距约 3.89 m，每个 ORU 由 X 约 −1 m 向后伸到 X 约 −23.3 m，面板位于 XZ 平面，法向为 ±Y。零位定义取自官方坐标模型图中散热器标注的 0°，资料 T3；NASA 线框图 SSP 51071 图 3.1.5-3 与 Boeing 图纸画法相同，资料 S、A。
3. TRRJ 转到 ±90° 时散热器梁沿 Y，三个 ORU 沿 Y 并排，面板法向为 ±Z，即正面对地姿态。收拢发射状态、IGOAL 存档姿态、ICES-2019-31 图1 照片都是这一姿态。ICES-2019-31 图1 是从天顶拍摄，图片上方为 +X，散热器向后伸展，不是向天底悬挂。
4. SARJ 为 0° 时，每个光伏模块的两个太阳翼沿 +X 与 -X 伸展：1A、3B、4A、2B 向前，3A、1B、2A、4B 向后。PVR 沿 +Z 指向天底，面板位于 YZ 平面，法向为 ±X，随 SARJ 转动。资料 T2、T3、G、S。
5. 姊妹文档 ISS_3D_MODELS.md 第2.3节与第2.9节第4条把 TRRJ 写成绕 Y 向轴转动，应改为绕 X 向轴转动。该文档所列 C 模型、VTAD 模型的 ORU 竖向叠放与 IGOAL 的 ORU 横向并排并不矛盾，两者是同一机构在 0° 与 ±90° 两个转角下的存档姿态。

## 2 桁架段尺寸与质量

| 段 | 长 | 截面尺寸 | 质量 | 资料与定位 |
|---|---|---|---|---|
| Z1 | 4 至 5 m | 4 至 5 m | 约 8300 | J，Z1 truss 页面 |
| S0 | 13.41，即 44 ft | 宽 4.57，即 15 ft；截面为拉长六边形，5 个节间 | 12247，即 27000 lb | P110 第33、34页 |
| S1 | 13.72，即 45 ft | 高 4.57，宽 1.83，即 15 ft 与 6 ft | 12572，即 27717 lb | P112 第42页 |
| P1 | 13.72 | 45 ft × 15 ft × 13 ft，与 S1 数据矛盾 | 12477，即 27506 lb | P113 第63、65页 |
| S3/S4 | 13.656 | 宽 4.965，高 4.631；S3 为六边形框架，4 个隔框 6 根纵梁 | 16183，即 35678 lb | P117 第48页 |
| P3/P4 | 13.81，即 45.3 ft | 宽 4.88，高 4.75；P3 为拉长六边形截面，2 个节间 | 15824，即 34885 lb | P115 第34、42页 |
| S5 | 3.37 | 宽 4.55，高 4.24；方形框架 | 1819，即 4010 lb | P118 第42页 |
| P5 | 3.35，即 11 ft | 15 ft × 14 ft；原文公制值 3.2 m 与 14 ft 不符 | 约 1800，即 4000 lb | P116 第6页 |
| S6 | 13.84，即 545.16 in | 宽 4.965，高 4.484 | 在轨 14088，即 31060 lb；概述另写 31127 lb | P119 第36页、第6页 |
| P6 | 长间隔段 8.53 与 IEA 4.88 | 长间隔段 28 × 16 × 16 ft，IEA 16 ft 立方 | 发射时约 15876，即 35000 lb；IEA 约 7711 | P97 第16、25、27页 |

压力套件中的长宽高是发射包络，长宽高标注随载荷舱摆放而定，在轨截面以模型包围盒为准。

## 3 桁架段 Y 范围与 SARJ 位置

IGOAL 模型包围盒，取自 ISS_3D_MODELS.md 第2.2节，相邻段在接口处有重叠：

| 段 | Y 范围 |
|---|---|
| S0 | −6.71 至 6.71 |
| S1 | 6.55 至 20.37；P1 为 −20.36 至 −6.54 |
| S3 | 20.32 至 26.06；P3 为 −26.07 至 −20.32 |
| S4 | 25.81 至 33.73；P4 为 −33.72 至 −25.96 |
| S5 | 32.13 至 35.79；P5 为 −35.78 至 −32.13 |
| S6 | 35.40 至 48.73；P6 为 −48.80 至 −35.39 |

SARJ 位于 S3 与 S4、P3 与 P4 之间，资料 P117 第51页、P115 第45页。官方坐标模型中不转动的内侧桁架止于 Y 为 −26.23 与 26.30，SARJ 转动体起于 ±27.27，资料 T2。SARJ 转轴为 Y 轴，官方坐标模型转轴过 X 为 5 mm、Z 为 11 mm。SARJ 滚道直径约 3.2 m，总质量 1161 kg，12 个滚轮组件，资料 H 第187、188页。

按压力套件长度逐段累加得到的右舷外端为 51.3 m，比 IGOAL 的 48.73 m 长 2.6 m，原因是 S5 插入 S4 外端，两段在 Y 向重叠约 1.6 m。

## 4 太阳翼

| 项目 | 数值 | 资料 |
|---|---|---|
| 单翼展开尺寸 | 35.05 × 11.58 m，即 115 × 38 ft；STS-116 套件写 110 ft | P117 第50页，P116 第42页 |
| 同一模块两翼总长 | 大于 73.2 m，即 240 ft | P117 第50页 |
| 单翼质量 | 大于 1089，即 2400 lb | P117 第50页 |
| 每翼毯面 | 2 块，桅杆居中；每块 82 个有效面板，每板 200 片电池，41 串；两端各 1 块无效面板 | P115 第36页 |
| 桅杆 | 可折叠铰接方形桁架 FAST，收在桅杆筒内 | P97 第23页 |
| 毯面尺寸 | 每块 32.51 × 4.752 m，含扁平导线宽度；电池串区 31.0 × 4.470 m；两块间隙 1.928 m；全翼宽 11.432 m | T2 模型与 T1 程序注释 |
| 桅杆长度与截面 | 纵梁长 32.43 m；4 根纵梁构成边长约 0.77 m 的方形 | T2，纵梁坐标推算 |
| 翼根位置 | SARJ 为 0° 时桅杆筒自 abs X 为 1.15 至 1.74 m 起，毯面自 abs X 为 3.32 至 3.91 m 起，毯面止于 35.83 至 36.43 m | T2 |
| BGA 转轴 | 沿桅杆轴线，即单翼长轴 | P115 第37页，P117 第51页 |
| BGA 轴线位置 | S4 与 P4 为 abs Y 33.35，S6 与 P6 为 abs Y 48.42；Z 为 ±0.75 左右；IGOAL 为 33.371、−33.435、48.445 至 48.447，Z 为 ±0.66 | T2，G |
| 相邻模块翼中心距 | 15.07 m；S4 外侧毯面外缘与 S6 内侧毯面内缘间隙 3.63 m | T2 推算 |
| 外侧毯面外缘 | abs Y 54.14，端到端 108.27 m，与参考指南 108.5 m 相符 | T2，R10 第95页 |

## 5 PVR

| 项目 | 数值 | 资料 |
|---|---|---|
| 展开尺寸与质量 | 13.6 × 3.12 m，740.7 kg，7 块面板，两条流路，最大散热 14 kW | P116 第61页 |
| 另一组尺寸 | 44 × 12 × 7 ft，宽度 12 ft 与 3.12 m 不符 | P117 第54页，P119，P115 |
| 位置 | S4 为 Y 27.70 至 31.19，S6 为 42.71 至 46.40，P4 为 −31.28 至 −27.70，P6 为 −46.28 至 −42.77 | T2；IGOAL 结果差 0.2 m 以内 |
| SARJ 为 0° 时朝向 | 由 Z 约 1.6 m 的安装处向 +Z 伸到 Z 约 14.9 至 15.2 m；面板在 YZ 平面，法向 ±X；X 约 0 至 0.5 m | T2，G，S |
| 是否随 SARJ 转动 | 是，PVR 属于 SARJ 外侧的光伏模块 | P117 第49页，T2 |

P6 位于 Z1 顶部期间，其 PVR 称为前向散热器，当时太阳翼沿 ±Y，说明 PVR 伸展方向垂直于太阳翼长轴，资料 P118 第23页、P120 第17页。P6 长间隔段上的两块 EEATCS 散热器在 2006 至 2007 年收拢，2011 至 2019 年构型中不展开。

## 6 主散热器与 TRRJ

| 项目 | 数值 | 资料 |
|---|---|---|
| ORU | 23.3 × 3.4 m，1122.64 kg，8 块面板 | P116 第69页 |
| 每翼组成 | 3 个 ORU 装在散热器梁上，6 个 RBVM，1 个 TRRJ | P116 第69页 |
| TRRJ 尺寸质量 | 1.7 × 1.4 × 1.3 m，420.5 kg；STS-112 套件为 3.4 × 4.5 × 5.2 ft、992 lb | P116 第71页，P112 第37页 |
| 转角范围 | 距中立位置 ±115°，软件限值 ±105°，转速 0 至 45 °/min | P116 第70、71页 |
| 转轴 | 平行 X，过 Y 为 ±14.600 与 14.694、Z 约 0；IGOAL 为 ±14.681；C 模型枢轴 ±14.732 | T1，T2，G |
| 零位姿态 | 梁竖直，ORU 沿 Z 叠放，包络 Z 为 −5.81 至 5.76 m，面板在 Y 约 ±14.3 至 ±15.0 的 XZ 平面内，X 为 −0.93 至 −23.34 m | T2，T3 |
| ORU 中心距 | 3.89 m，IGOAL 存档姿态下 ORU 中线在 abs Y 为 10.79、14.68、18.57 | G |
| 收拢状态 | 3 个 ORU 并排收在 S1 或 P1 后向面 | A 第19页 |
| 最近点实测 | gamma 为 35° 时 S1 散热器与 CTC2 净空 10.84 in，即 0.275 m | I |

RGAC 在光照段令散热器侧边对日，在地影段令散热器正面对地，资料 P116 第70页。按本节几何，β 为 0 时零位姿态已经侧边对日，正面对地需要转到 ±90°。转角正方向未找到公开定义。

## 7 俄罗斯段太阳翼

| 项目 | 数值 | 资料 |
|---|---|---|
| Zvezda 翼展 | 29.73 m；NASA 为 29.7 m，即 97.5 ft | E1，R10 第63页 |
| Zvezda 光伏面积 | 76 m2，两翼合计；最大输出 13.8 kW | E1 |
| Zvezda 位置 | 官方坐标模型用一块固定平板表示，X 为 −29.6 至 −25.7，Y 为 −15.26 至 15.20，Z 为 4.0 至 4.3 | T2 |
| Zvezda 转动 | 可转动跟踪太阳 | N1 |
| Zarya 翼展与面积 | 24.4 m，28 m2 | E2，R10 第59页 |
| Zarya 状态 | 2007 年 9 月底收拢，收拢后回弹，未完全收回，公开资料无回弹后尺寸 | I，E2 |

## 8 总跨度口径

| 口径 | 数值 | 资料 |
|---|---|---|
| 含太阳翼端到端 | 108.5 m，即 356 ft | R10 第95页 |
| 含太阳翼端到端 | 109 m；另一处写宽 110 m | R10 第102、101页 |
| P6 至 S6 桁架 | 95 m，即 311 ft | R15 第78页 |
| 桁架长 | 310 ft，即 94.5 m | P116，P118，P119 |
| 桁架长 | 335 ft，即 102.1 m | P119 第6页 |
| 桁架长 | 100 m，1998 年设计值 | F 第208页 |
| IGOAL 桁架端到端 | 97.53 m | G |

## 9 资料清单

| 代号 | 资料 | 地址 |
|---|---|---|
| A | Boeing, Active Thermal Control System ATCS Overview | https://www.nasa.gov/wp-content/uploads/2021/02/473486main_iss_atcs_overview.pdf |
| E1 | RSC Energia, Service module Zvezda | https://www.energia.ru/en/iss/rs/zvezda.html |
| E2 | RSC Energia, FGB Zarya | https://www.energia.ru/en/iss/rs/zarya.html |
| F | NASA JSC TD9702A, ISS Familiarization, 1998 | https://snebulos.mit.edu/projects/reference/International-Space-Station/FAM-C-22109RA.pdf |
| G | NASA JSC IGOAL 三维模型与本仓库 ISS_3D_MODELS.md | https://github.com/nasa/NASA-3D-Resources/tree/master/3D%20Models/International%20Space%20Station%20%28ISS%29%20%28D%29%20%28IGOAL%29 |
| H | Harik 等, ISS Solar Alpha Rotary Joint Anomaly Investigation, 2010 | https://ntrs.nasa.gov/api/citations/20100021920/downloads/20100021920.pdf |
| I | Liddle, Clearance Analysis of CTC2 on ELC4 to S-TRRJ HRS Radiator Rotation Envelope | https://ntrs.nasa.gov/archive/nasa/casi.ntrs.nasa.gov/20150003833.pdf |
| J | JAXA, Z1 truss and equipment | https://iss.jaxa.jp/iss/3a/mis_z1truss_e.html |
| N1 | NASA JSC 新闻稿转载, Zvezda Module Docks With ISS, 2000 | https://www.sciencedaily.com/releases/2000/07/000727081616.htm |
| P97 至 P120 | STS-97、110、112、113、115、116、117、118、119、120 航天飞机新闻资料包 | 见结构化输出各条地址 |
| R10 | Reference Guide to the ISS, Assembly Complete Edition, 2010 | https://www.nasa.gov/pdf/508318main_ISS_ref_guide_nov2010.pdf |
| R15 | ISS Utilization Guide, 2015 | https://www.nasa.gov/wp-content/uploads/2017/09/np-2015-05-022-jsc-iss-guide-2015-update-111015-508c.pdf |
| S | SSP 51071 External Payloads Proposer's Guide, 图 3.1.5-3 | https://explorers.larc.nasa.gov/HPMIDEX/pdf_files/07A_External-Payloads-Proposers-Guide-to-ISS-SSP-51071-Baseline_Redacted.pdf |
| T1 | NASA 与 TopCoder ISS Longeron Challenge 测试程序 ISSVis.java 第9版 | http://web.archive.org/web/20160429155625/http://www.topcoder.com/contest/problem/ISS/v9/ISSVis.java |
| T2 | 同上，官方坐标模型 ISS_simple.model 第9版，单位 mm | http://web.archive.org/web/20200921172614/https://www.topcoder.com/contest/problem/ISS/v9/ISS_simple.model |
| T3 | 同上，官方坐标系示意图 operations.png | http://web.archive.org/web/20201125105152/http://www.topcoder.com/contest/problem/ISS/operations.png |

NTRS 对本机返回 403，H 与 I 经 web.archive.org 存档副本读取。
