# 舱段布局与坐标系独立核验记录

本文件记录阶段1 舱段布局与坐标系一项的独立核验结果，完成时间 2026-09-30。核验对象是研究阶段 modules_layout 结构化输出中对有限元热模型影响最大的数值、其中唯一的低置信度数值，以及涉及朝向与布局的结论。每项都重新打开原引文献核对定位，并尽量用另一份文献交叉核对。结论分为确认、修正、存疑、无法核实四类。页码均为 PDF 文件页序。长度单位为米，坐标为国际空间站分析坐标系：原点在 S0 桁架段几何中心，+X 向前，+Y 向右舷，+Z 向天底。

## 1 结论

39 项中确认 34 项，修正 2 项，存疑 3 项，没有无法核实的数值。

1. 研究阶段所引的 JSC 26557 修订版 AB 第一卷本地副本只有 23.4 MB，是不完整文件。本次按字节区间重新下载 web.archive.org 存档全文 45878989 字节，共 607 页，逐页核对了表 6.4-1、各舱段质量特性页与图纸标注，研究阶段引用的坐标与图纸尺寸全部与原文一致。
2. 坐标系定义由正式规范 SSP 30219 修订版 F 独立确认：原点在 S0 几何中心，即相对两组耳轴底座中心连线的交点；X 平行舱段簇纵轴向前，Y 与 S0 轴线重合并指向右舷，alpha 转轴平行 Y，Z 指向天底；姿态角按偏航、俯仰、滚转顺序。RSA 坐标系 X 与分析系 X 反向，Y 指向天顶，Z 指向左舷，研究阶段给出的换算式成立。
3. 美国舱段轴线 Z 为 4.852，俄罗斯舱段轴线 Z 为 4.142，NASA 为 TopCoder 挑战赛提供的官方坐标模型分别为 4.855 与 4.190，IGOAL 模型中 Destiny 与 Unity 中心 Z 为 4.849 与 4.853，差值在 0.05 m 以内。
4. 修正两项。其一，加压舱包络的天顶端应为 Kibo 后勤舱 ELM-PS 的顶端，约 Z = −1.1 至 −1.3，研究记录自己推算的 ELM-PS 顶端为 −1.32，却把包络写成 Poisk 天顶口的 −1.02。其二，Zvezda 最大直径按制造方 RSC Energia 为 4350 mm，参考指南写 4.2 m，其英制值 13.5 ft 只相当于 4.11 m，JSC 26557 图纸最大半径 2125 mm 即直径 4.25 m。
5. 存疑三项。其一，全站 Z 向高度约 14 m 这一低置信度推算漏掉了 Z1 桁架及其 Ku 波段天线杆，JSC 26557 第123页 Z1 图纸从参考点 Z = 4.857 起总高 10248 mm，顶端约 Z = −5.4，IGOAL 为 −5.43，固定结构 Z 向跨度约 16.7 m，计入 S3 与 P3 天顶侧的 ELC-2、ELC-3 为约 18.5 m。其二，P6 至 S6 桁架长 95 m 虽与 2015 版利用指南原文一致，但 JSC 26557 第二卷表 8.0-1 中 P6 与 S6 太阳翼 beta 转轴已在 Y = ±48.559，相距 97.12 m，IGOAL 桁架端到端为 97.53 m，95 m 与坐标数据不符。其三，Unity 直径 4.3 m 只有参考指南一处来源，STS-88 资料包写 15 ft 即 4.57 m，JSC 26557 图纸与 IGOAL 的外包络直径为 4.45 m。
6. Zarya 太阳翼翼展 24.4 m 为设计展开值，Energia 页面写明目前 Zarya 太阳翼处于收拢状态，官方坐标模型也不含展开的 Zarya 太阳翼，2011 至 2019 年构型不应按展开翼建模。
7. 同一数据册第93页 EATCS 散热器图纸把 S1 散热器画成 3 个 ORU 沿 Z 叠放，叠放总高 10974 mm，沿 -X 长 23288 mm，面板位于 XZ 平面，参考点即 TRRJ 中心为 X −0.036、Y 14.693、Z 0.003。该姿态下绕 Y 轴转动无法让面板正面对地，TRRJ 转轴平行 X 轴，与姊妹记录 VERIFY_TRUSS_ARTICULATION.md 的结论一致。该图把单个 ORU 宽度标为 3190 mm，与本地文献的 3.4 m 不同，长度 23.3 m 一致，这一矛盾转交散热器条目处理。

## 2 核验文献

研究阶段已引文献沿用原链接，本次重新打开核对。本次新增的独立文献记为 V1 至 V12。

| 代号 | 文献 | 链接 |
|---|---|---|
| A1 | JSC 26557 修订版 AB 第一卷，On-Orbit Assembly, Modeling, and Mass Properties Data Book，2008 年 1 月，607 页全文 | https://web.archive.org/web/20150912224425/http://athena.ecs.csus.edu/~grandajj/ME296M/RevAB_Volume%20I%20Signed_updated.pdf |
| A2 | JSC 26557 修订版 AB 第二卷 | https://web.archive.org/web/20150912222142/http://athena.ecs.csus.edu/~grandajj/ME296M/RevAB_Volume%20II%20Signed_updated.pdf |
| A3 | JSC 26557 修订版 P 第一卷，2002 年 6 月 | https://web.archive.org/web/20240718225404/https://athena.ecs.csus.edu/~grandajj/ME296M/space.pdf |
| R10 | Reference Guide to the ISS, Assembly Complete Edition，2010 年 11 月 | https://www.nasa.gov/pdf/508318main_ISS_ref_guide_nov2010.pdf |
| R15 | ISS Utilization Guide，2015 年 | https://www.nasa.gov/wp-content/uploads/2017/09/np-2015-05-022-jsc-iss-guide-2015-update-111015-508c.pdf |
| S | SSP 51071 External Payloads Proposer's Guide，与 essp.larc 链接文件逐页核对 | https://essp.larc.nasa.gov/EVI-6/pdf_files/External-Payloads-Proposers-Guide-to-ISS-SSP-51071-Baseline.pdf |
| F | TD9702A International Space Station Familiarization，1998 年 | https://snebulos.mit.edu/projects/reference/International-Space-Station/FAM-C-22109RA.pdf |
| TF | TFAWS 2015 短期课程 ISS Payload Thermal Environments | https://tfaws.nasa.gov/wp-content/uploads/TFAWS2015-SC-ISS-Payload-Thermal-Design.pdf |
| P110 | STS-110 新闻资料包 | https://www.nasa.gov/wp-content/uploads/2023/05/spk-110-press-kit.pdf |
| V1 | SSP 30219 修订版 F，Space Station Reference Coordinate Systems，2001 年 10 月 | https://everyspec.com/NASA/NASA-JSC/NASA-SSP-PUBS/SSP_30219F_29666/ |
| V2 | NASA 与 TopCoder ISS Longeron Challenge 官方坐标模型 ISS_simple.model 第9版，单位 mm | http://web.archive.org/web/20200921172614/https://www.topcoder.com/contest/problem/ISS/v9/ISS_simple.model |
| V3 | NASA JSC IGOAL 三维模型，经本仓库 iss3d/components_iss_frame.csv 换算到分析坐标系 | https://github.com/nasa/NASA-3D-Resources/tree/master/3D%20Models/International%20Space%20Station%20%28ISS%29%20%28D%29%20%28IGOAL%29 |
| V4 | RSC Energia 网站 Zvezda 页面，web.archive.org 2021 年 10 月 24 日存档 | http://web.archive.org/web/20211024211416/https://www.energia.ru/en/iss/rs/zvezda.html |
| V5 | RSC Energia 网站 Zarya 页面，web.archive.org 2022 年 1 月 23 日存档 | http://web.archive.org/web/20220123215533/https://www.energia.ru/en/iss/rs/zarya.html |
| V6 | STS-88 新闻资料包 | https://www.nasa.gov/wp-content/uploads/2023/05/sts-088-press-kit.pdf |
| V7 | STS-92 新闻资料包 | https://www.nasa.gov/wp-content/uploads/2023/05/sts-092-press-kit.pdf |
| V8 | STS-104 新闻资料包 | https://www.nasa.gov/wp-content/uploads/2023/05/flight-105-sts-104-press-kit.pdf |
| V9 | STS-120 新闻资料包 | https://www.nasa.gov/wp-content/uploads/2023/05/192719main-sts120-presskit.pdf |
| V10 | ESA Cupola、Columbus、Node 2 三个页面 | https://www.esa.int/Science_Exploration/Human_and_Robotic_Exploration/Node-3_Cupola/Cupola |
| V11 | NASA 新闻稿 Space Station Module Relocation Makes Way for Commercial Crew Spacecraft，2015 年 5 月 | https://www.nasa.gov/news-release/space-station-module-relocation-makes-way-for-commercial-crew-spacecraft/ |
| V12 | NASA 空间站博客 Weekend Robotics Work Sets Up Thursday Spacewalk，2017 年 3 月 27 日 | https://www.nasa.gov/blogs/spacestation/2017/03/27/weekend-robotics-work-sets-up-thursday-spacewalk/ |

V2 的配套程序 ISSVis.java 第9版存档地址为 http://web.archive.org/web/20160429155625/http://www.topcoder.com/contest/problem/ISS/v9/ISSVis.java。V10 的另两个页面为 https://www.esa.int/Science_Exploration/Human_and_Robotic_Exploration/Columbus/European_Columbus_laboratory 与 https://www.esa.int/Science_Exploration/Human_and_Robotic_Exploration/International_Space_Station/Node_2_Connecting_Module。V2 的舱段用圆柱表示，本次按圆柱端点与半径读取位置。V3 的包络含扶手与附件，只用于核对位置。

## 3 逐项核验结果

| 编号 | 参数 | 原值 | 结论 | 核验值与依据 |
|---|---|---|---|---|
| 1 | 分析坐标系原点 | S0 桁架段几何中心 | 确认 | V1 第40页图 4.0-1 与第67页图 5.0-12：原点为 T1 至 T3、T2 至 T4 两条耳轴底座中心连线的交点；A1 第26页与 F 第381页同义；V3 中 S0 关于原点对称，±264.1 in |
| 2 | 分析坐标系三轴 | +X 沿舱段簇指向前，+Y 沿右舷桁架，+Z 天底 | 确认 | V1 第40页：XA 平行舱段簇纵轴，正向向前；YA 与 S0 轴线重合，alpha 转轴平行 YA，正向右舷；ZA 指向天底；姿态角按绕 ZA、YA、XA 的偏航、俯仰、滚转顺序 |
| 3 | 当地垂直当地水平坐标系 | +Z 天底，+Y 为轨道角动量反向，+X 为速度水平投影 | 确认 | V1 第33页图 3.0-11：ZLO 指向地心，YLO 垂直轨道面并与轨道角动量反向，XLO 指向运动方向，原点在质心；F 第377页同义 |
| 4 | +XVV 飞行时间占比 | 95%，另一处 75% | 确认 | S 第35页表 3.1.3-1 为 95% of Flight Time，第39页正文为 75% of the time，两处原文均核对无误；未找到第二份给出占比的文献 |
| 5 | +XVV 力矩平衡姿态包络与典型值 | 滚转 ±15°，偏航 ±15°，俯仰 +15° 至 −20°；典型偏航 −7° 至 0°，俯仰 −10° 至 2°，滚转 ±1.5° | 确认 | S 第35页表 3.1.3-1 与第42页表 3.1.5-1，两表的俯仰与滚转要求互相吻合 |
| 6 | PMM 搬移后 +XVV 自然平衡姿态 | 滚转 0.6° 至 0.8°，俯仰 −4.0° 至 2.5°，偏航 −4.1° 至 −2.9° | 确认 | S 第42页图 3.1.5-4，按 300 dpi 重新读图；-XVV 俯仰下限读作 −3.5°，与研究记录一致 |
| 7 | 热环境代表姿态 | +XVV，偏航、俯仰、滚转为 −4°、−2°、+1° | 确认 | TF 第49页与第37页原文核对；该值落在 S 第42页典型值范围内，滚转 +1° 略高于自然平衡姿态上限 0.8° |
| 8 | RSA 坐标系原点与换算 | 原点 −35.339、−0.006、4.142；XA = −35.339 - xR，YA = −0.006 - zR，ZA = 4.142 - yR | 确认 | V1 第43页图 4.0-4：XRSA 与 XA 反向，ZRSA 平行 YA 指向左舷，YRSA 与 ZA 反向；A1 第125页 Zvezda 参考点 ISS 坐标 −35339、−6、4142 mm 对应 RSA 原点；A1 第30页同时给出实测值 −35339、4、4139 mm；F 第381页 ROS 系 +X 向后、+Y 天顶、+Z 左舷 |
| 9 | 美国舱段轴线 | Y = 0，Z = 4.852 | 确认 | A1 第78至79页表 6.4-1 复核；V2 美国舱段圆柱与 Harmony 至 Kibo 圆柱轴线 Z 均为 4.855；V3 Destiny 与 Unity 中心 Z 为 4.849 与 4.853 |
| 10 | 俄罗斯舱段轴线 | Y = −0.006，Z = 4.142 | 确认 | A1 第78页复核；V2 俄罗斯舱段圆柱 Y = −0.125，Z = 4.190；V2 Poisk 与 Pirs 竖直圆柱轴线 X = −23.694，与 A1 的 −23.701 相差 7 mm |
| 11 | S0 长度 | 13.198 | 确认 | A1 第113页图纸 13198 mm；P110 第26页 43.3 ft；同一资料包第33页另写 44 ft 即 13.41 m，V3 的 S0 网格长 13.42 m，差值 0.22 m |
| 12 | S0 与 Destiny 的连接 | 实验舱托架 LCA 加前后共 4 组舱桁连接支杆 | 确认 | P110 第10、26、27页复核；F 第211页 9.4.2 节：LCA 连接 S0 与实验舱，固定在实验舱环框与纵梁上；R10 第95页：S0 装在 Destiny 顶部 |
| 13 | Z1 的安装 | Z1 天底 CBM 接 Unity 天顶 CBM，接口 −4.463、0、2.857 | 确认 | A1 第78页复核；V7 第18页：Z1 与 Unity 天顶口对接；R10 第95页同义 |
| 14 | 舱段轴向总长 | 51 m，PMA-2 前端至 SM 后端 | 确认 | R10 第102页复核；A1 坐标 15.427 至 −35.691 为 51.12 m；V2 的 PMA-2 前端 X 为 15.427；V3 为 51.38 m |
| 15 | 含太阳翼的端到端宽度 | 109 m，另有 108.5 m 与 110 m | 确认 | R10 第95、101、102页三处原文均核对无误；V2 外侧毯面外缘 Y = ±54.14，合 108.27 m；V3 为 108.3 m；几何值支持 108.5 m，110 m 为孤立值 |
| 16 | P6 至 S6 桁架长度 | 95 m | 存疑 | R15 第78页原文无误；但 A2 第17页表 8.0-1 中 P6、S6 的 beta 转轴 Y = ±48.559，相距 97.12 m；V3 桁架端到端 97.53 m；95 m 不能用于几何 |
| 17 | 全站长度 | 74 m，按沿 X 伸展的太阳翼解释 | 确认 | R10 第101页原文无误；V2 翼尖 X 为 ±36.70，合 73.40 m；V3 的 P4 两翼为 72.60 m；F 第22页把 1998 年设计的 74 m 称为舱段长度，74 m 的口径属于解释 |
| 18 | 全站 Z 向高度 | 约 14 m，由 S0 天顶耳轴 −2.48 至 Rassvet 天底口 11.29 | 存疑 | 漏掉 Z1 与 Ku 波段天线杆：A1 第123页 Z1 图纸从参考点 Z = 4.857 起总高 10248 mm，顶端约 −5.39；V3 为 −5.43；V2 天线盘 Z 为 −4.30 至 −4.92。固定结构 Z 向跨度约 16.7 m，计入 ELC-2、ELC-3 天顶侧的 −7.17 为 18.5 m，2011 至 2015 年 PMM 在节点1 天底口时再加 2.2 m |
| 19 | 加压舱包络 | X −35.69 至 15.43；Y −13.67 至 8.60；Z −1.02 至 11.29，PMM 在节点1 时至 13.52 | 修正 | Z 下限改为约 −1.3：ELM-PS 天底 CBM 在 Z = 2.844，A1 图纸长 4163 mm，顶端 −1.32，V3 为 −1.14，均高于 Poisk 天顶口 −1.02；其余边界与 V3 相符，V3 为 JEM PM −13.37、Columbus 8.68、Rassvet 11.24、PMM 13.47 |
| 20 | SARJ 转轴位置 | 0、±25.831、0 | 确认 | A2 第17页表 8.0-1 复核；V3 转轴 X = 0、Z = 0；V2 配套程序 ISSVis.java 第4111至4112行两侧 SARJ 转轴点为 X 5 mm、Z 11 mm |
| 21 | TRRJ 转轴位置 | −0.122、±14.691、0.001 | 确认 | A2 表 8.0-1 复核；A1 第93页 TRRJ 中心 −0.036、14.693、0.003；V3 为 ±14.681；V2 为 14.600 与 −14.694；转轴方向平行 X，见第1节第7条 |
| 22 | 8 个太阳翼 beta 转轴位置 | S4、P4 在 abs Y 33.39 至 33.42，S6、P6 在 48.559，Z ±0.66 | 确认 | A2 表 8.0-1 逐项复核；V3 为 33.371、−33.435、±48.445，Z ±0.66；V2 配套程序 ISSVis.java 第4113至4120行为 abs Y 33.350 与 48.413 至 48.422，abs Z 0.683 至 0.817；8 个翼的 Z 正负号在三方完全一致；S6、P6 的 Y 比两套模型大 0.11 至 0.15 m |
| 23 | 俄罗斯段与来访飞行器接口 | SM 后口 −35.691；Rassvet 天底口 Z 11.285；Pirs 天底口 9.308；Poisk 天顶口 −1.024；Harmony 天底口 6.854；PMA-2 前端 15.427 | 确认 | A1 第77至79页与 A2 表 8.0-1 复核；V2 Poisk 与 Pirs 圆柱 Z 为 −1.026 至 9.320，Rassvet 天底端 11.284，PMA-2 前端 15.427 |
| 24 | Zarya 长度与最大直径 | 12.99 与 4.1 | 确认 | V5：舱体长 12990 mm，最大直径 4100 mm；R10 第59页印作 12,990 m，为排印错误 |
| 25 | Zarya 太阳翼翼展 | 24.4 | 确认 | V5 为 24400 mm；V5 同页注明 at present solar arrays on FGB Zarya are stowed，V2 不含展开的 Zarya 太阳翼，2011 至 2019 年构型不建展开翼 |
| 26 | Zvezda 最大直径 | 4.2 | 修正 | V4 为 4350 mm；A1 第125页图纸最大半径 2125 mm 即 4.25 m；R10 第63页的 13.5 ft 只合 4.11 m，与 4.2 m 自相矛盾 |
| 27 | Zvezda 长度与太阳翼翼展 | 13.1 与 29.7 | 确认 | V4：舱体长 13110 mm，翼展 29730 mm，光伏面积 76 m²；A1 第125页图纸翼展 29734 mm |
| 28 | Unity 直径 | 4.3 | 存疑 | V6 第48页：15 ft 即 4.57 m；A1 第122页图纸半径 2223 mm 即外包络 4.45 m；V3 为 4.447 m；长度 5.5 m 与 V6 的 18 ft 一致 |
| 29 | Destiny 长度与直径 | 8.5 与 4.3 | 确认 | R10 第49页复核；A1 第91页图纸半径 2094 与 2223 mm，即 4.19 与 4.45 m，长 9075 mm 含两端 CBM；V3 包络 9.07 m、4.45 m；辐射外表面宜取 4.45 m |
| 30 | Harmony 长度与直径 | 6.706 与 4.48 | 确认 | V10 Node 2 页面：6706 mm、4480 mm；A1 第101页图纸半径 2239 mm；V9 第33页为 23.6 ft 与 14.5 ft，即 7.19 与 4.42 m，为含对接件的外形尺寸 |
| 31 | Tranquility 长度、直径与质量 | 6.706、4.48、17992 kg | 确认 | ESA 概况单第3页原文复核；R10 第55页长度与质量相同；A1 第534页图纸直径 4477 mm，总长 6888 mm |
| 32 | Tranquility 径向口轴线位置 | Y = −6.63，由节点2 在 2007 年同一 Unity 左舷口的数据推得 | 确认 | A1 第79页表中节点2 位于 Unity 左舷口时径向口 Y 为 −6.627 与 −6.632；A1 第534页 4632 mm 端朝向 Unity；V3 中 Cupola 中心 Y −6.688，节点3 前向口上的 PMM 中心 Y −6.638 |
| 33 | Cupola 尺寸与位置 | 高 1.5，直径 2.955，1880 kg；中心 −4.46、−6.63、7.59 | 确认 | V10 Cupola 页面：1500 mm、2955 mm、发射 1805 kg、在轨 1880 kg；V3 中心 −4.543、−6.688、7.509，Z 范围 6.74 至 8.28，与推算相差 0.1 m 以内 |
| 34 | Columbus 尺寸与位置 | 长 6.871，直径 4.477；中心 10.933、5.305、4.858 | 确认 | V10 Columbus 页面：6871 mm、4477 mm，装在节点2 右舷口；A1 第90页图纸 6588 与 7533 mm；V3 中心 10.855、5.325、4.851 |
| 35 | Kibo 加压舱尺寸与位置 | 长 11.2，外径 4.4，15.9 t；中心 10.936、−7.589、4.851 | 确认 | JAXA 手册第21页表 3.1-1 复核；R10 第51页与 R15 第29页相同；V3 中心 10.957、−7.665、4.973；V2 的 Harmony 至 Kibo 圆柱轴线 X 为 10.926 |
| 36 | ELM-PS 长度与位置 | 长 4.2，装在加压舱天顶口 10.941、−9.930、2.844，中心 Z 0.762 | 确认 | JAXA 手册第21页与 R15 第29页均为 4.2 m，R10 第51页 3.9 m 为孤立值；V3 中心 11.093、−9.948、0.920，Z 向尺寸 4.13 m |
| 37 | Kibo 暴露平台尺寸 | 5.6 × 5.0 × 4.0，4.1 t | 确认 | JAXA 手册第21页复核；R10 第51页相同；S 第79页为 6 × 5 × 4 m；V3 为 Y 5.64、X 4.97、Z 3.51，高度按有效载荷包络另计 |
| 38 | Quest 长度与宽度 | 5.5 与 4.0 | 确认 | V8 第23页：长 5.5 m 即 18 ft，直径 4 m 即 13 ft，质量 6064 kg；A1 第87页图纸设备舱外包络半径 2223 mm；V2 乘员舱端部 Y = 7.574，距 Unity 右舷口 5.58 m |
| 39 | 全站质量与加压容积 | 2010 年 419600 kg 与 935 m³；2015 年 410501 kg 与 916 m³ | 确认 | R10 第101页与 R15 第78页原文无误；R10 第102页，即 51 m 与 109 m 所在页，另写 399380 kg 含联盟号与 860 m³，同一文件两组数值不同 |

## 4 布局与朝向问题

1. 全站 Z 向高度的推算漏掉了 Z1 桁架，Z1 与 Ku 波段天线杆的顶端约在 Z = −5.4，见第3节第18项。
2. 加压舱包络的天顶端取错为 Poisk，应为 ELM-PS，见第3节第19项。
3. 桁架长度 95 m 与 94 m 这类整数公布值和 JSC 26557 的 beta 转轴坐标不符，建模应以坐标为准。
4. Zarya 太阳翼在目标年代处于收拢状态，不应按展开翼展 24.4 m 建模。
5. TRRJ 转轴平行 X 轴，过 Y ≈ ±14.69、Z ≈ 0。A1 第93页散热器零位姿态为 3 个 ORU 沿 Z 叠放，面板位于 XZ 平面。ISS_3D_MODELS.md 第2.3节与第2.9节第4条写成绕 Y 向轴转动，应改正。
6. 参考指南把 Unity、Destiny、Harmony、Tranquility 的直径都写成 4.3 m。意大利制造的节点 ESA 给出 4.48 m，JSC 26557 图纸的外包络为 4.45 至 4.48 m。舱体辐射外表面应取外包络直径。
7. 研究记录中的朝向结论经核对无误：+Z 指向天底，舱段位于桁架下方，美国舱段轴线在 S0 中心下方 4.85 m；Cupola 圆顶朝天底；Columbus 沿 +Y，Kibo 加压舱、暴露平台与 Tranquility 沿 -Y，ELM-PS 沿 -Z 即天顶；PMM 于 2015 年 5 月 27 日由 Unity 天底口移到 Tranquility 前向口，见 V11；PMA-3 于 2017 年 3 月 26 日由 Tranquility 移到 Harmony，见 V12。

## 5 对建模取值的影响

本节对照 ISS_SPEC.md 第2.1节的舱段表，列出与 JSC 26557 接口坐标不符的取值，偏差来自把舱段贴在相邻舱段外壳半径上，而没有贴在 CBM 或对接口平面上。

| 舱段 | ISS_SPEC.md 取值 | 按接口坐标的取值 | 依据 |
|---|---|---|---|
| Tranquility、Cupola、Quest | 中心 X = −5.02，即 Unity 两端 CBM 中点 | X ≈ −4.46，即 Unity 径向口轴线 | A1 第78页：Unity 左舷口 X −4.462，右舷口 X −4.464；V2 Tranquility 圆柱 X −4.470 |
| Poisk、Pirs | X = −24.10，中心 Z 0.31 与 8.21，长 4.90 | X = −23.701；Poisk Z 3.023 至 −1.024，中心约 1.00；Pirs Z 5.271 至 9.308，中心约 7.29 | A1 第78至79页；V2 竖直圆柱 X −23.694，Z −1.026 至 9.320 |
| Rassvet | 中心 Z 9.17 | Z 5.285 至 11.285，中心约 8.29 | A1 第79页；V3 中心 8.24 |
| Columbus | 中心 Y 5.73 | 约 5.31 | A1 第79页 CBM 平面 Y 2.011，第90页壳体 6588 mm；V3 为 5.33 |
| Kibo 加压舱 | 中心 Y −7.89 | 约 −7.59 至 −7.67 | A1 第79页 CBM 平面 Y −1.989；V3 为 −7.665 |
| ELM-PS | 中心 Z 0.50 | 约 0.76 至 0.92 | A1 第79页 CBM 平面 Z 2.844；V3 为 0.920 |
| Zvezda 大直径段 | 直径 4.20 | 4.35 | V4 |
| Unity、Destiny | 直径 4.30 | 外包络 4.45 | A1 第91、122页图纸半径 2223 mm；V3 |

以上偏差为 0.3 至 0.9 m，Tranquility 组三个舱段整体偏后 0.56 m。修改后相邻舱段仍需按接口平面留出间隙，避免几何相交。
