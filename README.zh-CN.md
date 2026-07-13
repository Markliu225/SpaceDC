# 太空算力 Demo

[English](README.md) · **中文**

一个**在轨算力数据中心**的数字孪生 —— 用 Omniverse 渲染卫星、通过 WebRTC 流式嵌入 React 网页，由 FastAPI 物理引擎驱动。你可以点击任意组件查看实时遥测、在界面上自由调整可展开的太阳能板 / 散热板几何，并实时观察功耗与热平衡物理量的变化。

## 架构

```
 浏览器 (React + Zustand)  ──WebRTC──►  Omniverse Kit 应用 (USD 视口)
        │      ▲                                   │
        │      │  状态 (5 Hz)                      │  读取 /state、/satellite_config、
        ▼      │                                   ▼  /twin_geometry；重载图层
   WebSocket / REST  ◄────────────────────►  后端 (FastAPI)
                                              物理 + 状态引擎
```

| 目录 | 说明 | 端口 |
|------|------|------|
| `web/` | React + TypeScript + Zustand + Three.js 前端；WebRTC 视口，含本地降级场景 | 5173（开发） |
| `backend/` | FastAPI 状态引擎（轨道 + 功率 + 热学物理）+ WebSocket 广播 | 8001 |
| `ov_app/` | Omniverse Kit 应用 + 扩展（`space.demo.scene` / `.selection` / …）；WebRTC 推流 | 49100 |
| `usd/` | USD 舞台 —— `satellite.usda`（灯光 + 相机）sublayer `twin_satellite.usda`（卫星本体） | — |
| `tools/` | USD 生成器 + 免 GL 的预览渲染器 | — |
| `assets_raw/` | 源 `.usdz`（骨干 / 太阳能板 / 散热板）—— 体积大，不入 git | — |
| `data/`、`docs/` | 模拟用例、规格文档 | — |

## 卫星模型

卫星本体由 **`tools/gen_twin_satellite.py`** 生成 → `usd/twin_satellite.usda`，以 `SpaceDcBackbone.usdz` 骨干为主干：

- **骨干 + 算力** —— 一根竖直桁架，两端各一个推进器模块，中部一个储箱 / 反作用轮组件，四个象限机架（±Y × 上/下）。每个机架有 3 个开放槽位框架 → 共 **12 块服务器刀片**。
- **太阳能翼** —— 两翼沿 **±Y** 方向、通过中部支架上的细支撑杆展开；每翼由若干个 **2×2 面板簇**（`solar_panel_3d_model.usdz`，无缝拼接）组成，电池面朝向 **+X**（太阳）。太阳能板只能往两侧继续增加。
- **散热板** —— 两块面板沿 **±Z** 方向、通过骨干两端的支撑杆展开，与太阳能翼**互相垂直**（大面朝 ±Y）。每块为单块 **2 : 5** 面板，以短边连接支撑杆；大小与比例均可调。

几何在运行时通过 `usd/twin_params.json` 参数化（由后端写入，已加入 gitignore）。免 GL 的软件渲染器 **`tools/render_usd.py`** 可在不启动 Kit 的情况下预览任意舞台。

## 交互功能

1. **更大的视口** —— Twin 页面把 Omniverse 窗口放到最大，侧栏与底栏更紧凑。
2. **组件级交互** —— 点击服务器、太阳能翼、散热板或骨干部件，弹出对应信息卡（按选中的 prim 路径匹配）。
3. **可展开结构编辑** —— *Deployables* 控件用于增减太阳能板簇（仅限两侧）、调整散热板的大小与比例；每次改动都会重新生成 USD 模型并在 Kit 中重载。
4. **实时物理** —— 太阳光照 · 面板面积 × 效率 · GPU 负载 · 设备功耗 · 散热板面积 × 发射率，统一汇入实时功率 / 热平衡，显示在状态卡片与组件面板中。改动几何，数字立即更新。完整模型见 **[docs/physics.zh-CN.md](docs/physics.zh-CN.md)**。
5. **单星设计库** —— Twin 页顶部的 *Designs* 入口打开设计库窗口（`backend/design_presets.py`）：每个完整设计带软件渲染的缩略图（`GET /designs/{id}/preview.png`，带缓存）与派生参数卡。点击应用（`POST /designs/{id}/apply`）即一键切换硬件配置、可展开几何（USD 重新生成 + Kit 层重载）、GPU workload 档案与平台常数；之后手动改任何参数会把当前设计降级为 `custom`。
6. **六种整星构型** —— 每个设计是真正不同的卫星形态（`twin_params.json` 的 `architecture`）：经典单桁架、24 刀片双桁架塔、ISS 式长条毯式翼、自带十字翼的 LUMID 小卫星、带抛物面天线的风车翼通信星，以及 Redwire 式扁平载荷舱（舱体自带的一排独立 GPU 组件朝阳面，逐个可点击弹出 GPU 面板；平板 GaAs 太阳翼与舱面平行、直接栓在舱缘凸耳上，加板时向外逐块延伸；支杆散热板出舱面）。物理面积随构型切换。
7. **类型化 AI workload** —— 每个作业块都是具体任务（`backend/ai_workloads.py`）：Llama-3.3-70B 预训练/推理、Llama-3.1-8B 微调、ViT-L/16 对地检测——按所装 GPU 的数据手册稠密算力解析为每卡 MFU、有效 TFLOPS、tokens/s / frames/s 与产热，实时暴露于 `satellite.workload_detail` 与 GPU 模块弹窗。
8. **Twin 页实时轨道运动** —— Kit 特写中，地球随实时星下点转动、太阳圆盘与主光沿真实天顶-太阳夹角（`satellite.sun_cos`）扫掠：地面轨迹、昼夜交替、进出地影都在视口中真实上演；流离线时视口回退为真实轨道追踪视图（`TwinOrbitFallback`），被跟踪卫星沿 SGP4 传播的轨道环滑行，左下 HUD 的卫星标记也在帧率级外插时钟上平滑运动。后端在每次 `/state` 读取时刷新被跟踪卫星的运动学（单次缓存 Satrec sgp4 调用），Kit 的 5Hz 轮询看到的是连续运动而非 1Hz 台阶。
9. **Workload 选择器** —— Configurator 的 *Workload* 区实时切换 GPU 作业表（`POST /workload_profile`）；每个选项标注当前设计的适配度（`GET /workload_profiles`：平均需求 vs 太阳供给、散热上限、fit 判定、每周期预期 tokens/frames/kWh），面板实时显示在跑任务的模型、MFU、有效 TFLOPS、速率、电功耗、每卡产热、辐射功率与切换以来的累计产出。
10. **LLM serving 是主营业务** —— workload 体系围绕多模型推理服务展开（Llama-3.1-8B/70B/405B、Qwen2.5-Coder-32B、Qwen2.5-72B、Mistral-Small-24B），每种作业都是 decode 定律上不同的工作点（批量、上下文、模型规模）：多层级聊天服务（`chat_serving`）、405B 前沿模型服务（`frontier`）、代码补全 + 长上下文 RAG（`code_rag`）、70B 批量服务（`inference`，默认档案）——EO 视觉与训练降为辅线。*Redwire Serving Node* 设计在 8×H200 张量并行组上飞 Llama-405B。
11. **LLM 推理解析引擎** —— LLM 作业不再用 MFU 估计：`backend/llm_perf.py` 从第一性原理解出真实工作点（DVFS 功耗聚合 `P = P_static + χ·x^θ`、计算受限的 prefill/训练幂律、含带宽平台的 decode 访存下限定律、自然功耗），并**与卫星热状态耦合**：结构就是 GPU 的冷板，`T_die = T_struct + P·R_th`，驱动通过收缩功率预算把结温压在节流目标上——散热板不足或涂层退化会直接表现为可计算的 tokens/s 损失（`gpu_thermal_throttle` / `gpu_thermal_runaway` 告警，结温 / SM 频率 / 执行相位实时显示在面板中）。模型按公开的 V100 功率上限实测研究校准，由 `tools/validate_llm_perf.py`（52 项）+ `tools/validate_llm_engine.py`（32 项闭环场景）验证；专设 *LLM serving (70B)* 档案飞 decode 主导的作业表来展示这一切。详见 **[docs/physics.md §4a](docs/physics.md)**。

## 快速开始

```bash
# 后端（Python 3.11，venv 中已装 USD/pxr）
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8001

# 前端
cd web
npm install
npm run dev            # http://localhost:5173

# Omniverse Kit 应用 —— 见 LAUNCH.md
```

**一键启动：** 双击 **`start_all.bat`**，同时拉起后端、前端开发服务器和 Kit 推流应用（见 [LAUNCH.md](LAUNCH.md)）。用 `stop_all.bat` 停止。

## 工具

| 脚本 | 用途 |
|------|------|
| `tools/gen_twin_satellite.py` | 生成卫星 USD（读取 `usd/twin_params.json`） |
| `tools/render_usd.py` | 免 GL 软件渲染器 —— 无需 Kit 即可预览任意 USD/USDZ |
| `tools/inspect_backbone.py`、`tools/analyze_slots.py` | 骨干的几何 / 槽位勘察 |

## 说明

- 大体积 `.usdz`/`.usdc` 资产（骨干、太阳能板、散热板，以及 LUMID / dish / redwire 载荷舱壳体，每个 55-80 MB）已加入 gitignore；请在本地保留于 `usd/assets/` 与 `assets_raw/`。
- 后端在几何变更时重新生成 `usd/twin_satellite.usda` 并递增版本号；Kit 场景扩展会实时重载该图层。
