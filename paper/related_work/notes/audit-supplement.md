# 查漏审计补充笔记

## 审计结论

本次审计按三个角度检查了已收集的二十九条文献清单,结论如下。

角度一,与 SpaceDC 直接竞争的卫星模拟器。清单覆盖了 StarryNet、Celestial、Hypatia、StarPerf、xeoverse、Stardust 这条网络模拟器脉络,但漏掉了最直接的竞争系统 Rhone。Rhone 是北大和北邮团队做的空间计算网络仿真器,完整论文发表在 USENIX ATC 2025,同一系统的 demo 版发表在 ACM MobiCom 2025,与我们的目标 venue 和论文形态完全相同,是审稿人必然会想到的对照系统,必须引用并正面区分。两个版本都已补入。检索中还核对了 OpenSN 等 2024 年后的新模拟器,它们只做网络层仿真,清单中已有的系统足以代表该方向,不再增补。

角度二,在轨 AI 数据中心的动机文献。清单已有 Google Suncatcher、Starcloud 白皮书、JPL 经济可行性、系绳架构、一体化板设计和 LLMSpace,产业侧动机充分。缺的是网络系统学术社区最早论证在轨算力价值的奠基文献,即 HotNets 2020 的 In-orbit Computing 一文。补入这一篇后,动机链条从学术设想到产业方案完整闭合,不需要再加。

角度三,GPU 功耗性能建模的支撑文献。SpaceDC 的核心反馈回路是结构温度压缩 GPU 的 DVFS 功率预算进而降低大模型推理吞吐,清单中没有任何一篇论文支撑功率封顶与推理性能之间的量化关系。补入 ASPLOS 2024 的 POLCA 一文,它用真实 A100 服务器测量了频率锁定和功率封顶对大模型推理的影响,是这条建模假设的直接实验依据。一篇足够。

共补充四篇,全部拿到开放获取 PDF 并通过校验。

## 1. Emulating Space Computing Networks with RHONE

引用信息。Liying Wang, Qing Li, Yuhan Zhou, Zhaofeng Luo, Donghao Zhang, Shangguang Wang, Xuanzhe Liu, Chenren Xu. Emulating Space Computing Networks with RHONE. In Proceedings of the 2025 USENIX Annual Technical Conference, ATC 2025, Boston, MA, USA, 2025 年 7 月 7 日至 9 日, 论文集起始页 815. 作者单位为北京大学与北京邮电大学。

研究的问题。空间计算网络的应用难以设计和评估,因为真实星座成本极高,而现有实验平台无法同时复现单星层面的能源热约束和星座层面的动态网络。物理测试台保真但难获取,解析型模拟器缺少真实系统栈,网络仿真器忽略了星载商用芯片在空间环境下的性能变化。

方法。Rhone 采用两阶段仿真。离线阶段用天算星座的真实遥测数据建立电源、热、轨道、网络和计算模型,遥测数据超过八十万条时间戳记录,跨度从 2021 年 12 月到 2022 年 7 月,计算模型用硬件在环芯片镜像方法对树莓派、Jetson、Atlas 200DK 等星载商用芯片建模。在线阶段用容器化仿真加载这些模型,卫星 COTS 对齐器通过画像和动态资源调节让容器复现卫星芯片的实际算力,卫星网络对齐器让容器网络复现星座拓扑动态,并提供监控和指令 API 运行未修改的应用。

关键结论与数字。单台物理机可扩展到 700 颗卫星,与 Starlink 单壳层规模相当。电源模型和计算模型误差低于百分之五,温度模型平均误差在 1.3 到 2.5 摄氏度之间,以在轨卫星遥测为真值。两个案例研究分别是卫星网络能量耗竭攻击和实时对地观测四种处理策略对比。

与 SpaceDC 的关系。这是与 SpaceDC 定位最接近的系统,同样强调电源、热、轨道、计算的联合复现,是必须正面比较的对照。

它没有覆盖而我们覆盖的地方。Rhone 的模型由已有卫星的遥测数据拟合而来,只能复现已经飞过的硬件与构型,不支持对尚未存在的算力卫星做设计空间探索,SpaceDC 用第一性物理模型并对 STK 11.6 做了数值验证,可以推演任意新构型。Rhone 面向树莓派和 Jetson 级别的低功耗商用芯片,没有数据中心级 GPU 的大模型推理性能模型,也没有温度压缩 DVFS 功率预算再降低推理吞吐的显式反馈回路。Rhone 不提供卫星搭建向导、实时 what-if 并行对比和三维可视化。

## 2. Demo: Emulating Space Computing Networks with Rhone

引用信息。Liying Wang, Qirui Liu, Qing Li, Shangguang Wang, Xuanzhe Liu, Chenren Xu. Demo: Emulating Space Computing Networks with Rhone. In The 31st Annual International Conference on Mobile Computing and Networking, ACM MobiCom 2025, Hong Kong, China, 2025 年 11 月 4 日至 8 日, 页 1239 至 1241. DOI 10.1145/3680207.3765603.

研究的问题。与 ATC 完整论文同一系统,demo 版展示 Rhone 的仿真工作流和交互能力,让参会者提交空间计算应用并实时观察卫星级和星座级指标。

方法。演示形态是笔记本电脑连接部署在远程服务器上的仿真后端,通过 Rhone 的监控与指令 API 提交应用、观察功率温度网络指标并交互控制。系统结构与完整论文一致,离线建模加在线容器仿真。

关键结论与数字。demo 论文重复了核心精度数字,电源与计算模型误差低于百分之五,温度模型平均误差 1.3 到 2.5 摄氏度。

与 SpaceDC 的关系。这是 MobiCom 正式论文集里与我们形态完全相同的 demo 论文,同一会议系列,同一展示方式,审稿人会直接拿它与 SpaceDC 对照,引用它能准确锚定我们的增量。

它没有覆盖而我们覆盖的地方。与完整论文相同,没有面向设计阶段的物理推演能力,没有 GPU 大模型推理与热的耦合反馈,没有搭建向导和 what-if 并行对比,演示界面是终端和曲线监控,没有 Omniverse RTX 级别的三维场景可视化。

## 3. In-orbit Computing: An Outlandish thought Experiment?

引用信息。Debopam Bhattacherjee, Simon Kassing, Melissa Licciardello, Ankit Singla. In-orbit Computing: An Outlandish thought Experiment? In Proceedings of the 19th ACM Workshop on Hot Topics in Networks, HotNets 2020, 线上会议, 2020 年 11 月 4 日至 6 日, 页 197 至 204. DOI 10.1145/3422604.3425937. 作者单位为苏黎世联邦理工学院。

研究的问题。低轨巨型星座除了做网络转发之外能否同时作为云算力提供商,把计算放到用户随时可达的轨道上,这一设想的应用价值和技术障碍分别有多大。

方法。定性加定量的思想实验。作者列举内容分发与边缘计算、多人交互会合服务器、协同音乐与沉浸应用、空间原生数据处理等受益应用,再用 Starlink 第一期和 Kuiper 的星座几何计算任意地面点到最近和最远可达卫星服务器的往返时延与可达卫星数量,并讨论重量、体积、功率、抗辐射加固和有状态应用迁移等约束。

关键结论与数字。对 Starlink 第一期,大多数纬度上最近可达卫星的传播往返时延在 4 毫秒以内,所有地面位置都能在 11 毫秒往返时延内到达最近卫星,最远直达卫星也在 16 毫秒以内。几乎所有位置任意时刻可达超过 30 颗卫星。若 Starlink 四万颗卫星每颗放一台服务器,规模只比最大的 CDN 小七倍。作者判断在卫星上加计算硬件的重量体积和加固代价并不致命,真正的难点是功率需求和低轨动态性导致的状态迁移。结论是这个设想不应被轻易否定,值得社区深入研究。

与 SpaceDC 的关系。这是网络系统社区论证在轨算力价值的奠基文献,为在轨算力卫星这个研究对象提供了最早的学术动机,SpaceDC 面向的正是这篇论文设想的那类卫星,我们的引言可以用它开启从设想到工程工具的叙事。

它没有覆盖而我们覆盖的地方。这篇论文停留在思想实验层面,只算了几何时延和可达性,没有任何系统实现。它把功率列为最大难点却没有建模电源与热,更没有算力与热的反馈。SpaceDC 提供了逐秒耦合轨道电源热控与 GPU 推理性能的可验证物理引擎,把这篇论文指出的核心难点变成了可以量化推演的工程问题。

## 4. Characterizing Power Management Opportunities for LLMs in the Cloud

引用信息。Pratyush Patel, Esha Choukse, Chaojie Zhang, Íñigo Goiri, Brijesh Warrier, Nithish Mahalingam, Ricardo Bianchini. Characterizing Power Management Opportunities for LLMs in the Cloud. In Proceedings of the 29th ACM International Conference on Architectural Support for Programming Languages and Operating Systems, Volume 3, ASPLOS 2024, La Jolla, CA, USA, 2024 年 4 月 27 日至 5 月 1 日, 共 16 页. DOI 10.1145/3620666.3651329. 作者来自 Microsoft Azure。

研究的问题。功率是 GPU 数据中心扩容的第一瓶颈,大模型训练和推理的真实功耗形态是什么,GPU 的频率锁定和功率封顶这些管理手段对大模型负载的性能影响有多大,能否据此做功率超额认购。

方法。在 8 卡 A100 的 DGX 服务器上测量 Llama2 70B、BLOOM 176B、GPT-NeoX、OPT、Flan-T5 等开源大模型在不同批大小、输入输出长度下的功耗,用 DCGM 以 100 毫秒粒度采集 GPU 功率与性能计数器,用 nvidia-smi 施加频率锁定与功率封顶并测量推理延迟和吞吐的响应,再用生产集群踪迹验证服务器级结论,最后提出功率超额认购框架 POLCA。

关键结论与数字。GPU 占服务器供电预算约一半。训练集群功率峰值大且同步,只有约百分之三的超额空间,推理集群在集群层面有约百分之二十一的功率余量。功率封顶的实现机制是达到上限时反应式地压低 GPU 频率,频率下降直接转化为推理延迟上升和吞吐下降,论文给出了各模型在不同封顶值下的量化性能曲线。POLCA 在同样的推理集群里可以多部署百分之三十的服务器,性能损失极小。

与 SpaceDC 的关系。SpaceDC 的热算力反馈回路假设功率预算被压缩时 GPU 通过 DVFS 降频导致推理吞吐下降,这篇论文用真实硬件测量证实了功率封顶经由降频作用于大模型推理性能这条因果链,是我们 GPU 功耗性能模型的直接实验依据,引用它可以支撑我们把温度映射到功率预算再映射到吞吐的建模选择。

它没有覆盖而我们覆盖的地方。这篇论文研究的是地面数据中心,功率上限来自供电合同,散热由机房空调兜底,功率与温度相互独立。SpaceDC 面向轨道环境,功率预算随日照与电池状态逐秒变化,散热只能靠辐射器,结构温度直接压缩 DVFS 功率预算,功率和热在轨道时间尺度上强耦合,这条空间特有的反馈链是它完全没有触及的。
