# STK 11 对标报告 · 轨道/电/热

场景：22 Aug 2024 12:00:00.000 起 24 h，步长 60 s；判据源自 NTU 测试报告（STK 为真值）。

## 用例 `leo_iss`

- **B1 SGP4/TEME**：|Δr| max 2.924e-10 km (rms 6.866e-11)，|Δv| max 3.297e-13 km/s
- **B2 星下点**：Δlat max 0.181°，Δlon max 151.287°，Δalt max 13.165 km（vs 地心纬度 Δ max 0.012°——大地/地心之差与 GMST 误差分离）
- **B3 太阳几何**：方向角差 max 141.270°（mean 141.226°），Δβ max 77.253°
- **B4 地影**：日照占比 STK 63.9% vs 我方 52.2%；事件时刻差 max 2384.5 s，漏报 1、误报 1（STK 地影段 16 个）
- **B6 光照因子**：RMS 0.859，max 1.000
- **B7 太阳能**：24h 能量（对日）STK 196871 Wh vs 我方 163976 Wh（差 16.7%）；（对地）STK 86300 Wh vs 我方 72965 Wh（差 15.5%）
- **B8 电池**：min SOC STK 驱动 78.1% vs 我方驱动 71.3%；期末 SOC 差 3.1 pp
- **B9 热**：SEET 光照段均温 264.4 K、地影段均温 231.1 K；我方恒定 270.9 K（无轨道相位依赖）→ 光照段偏差 mean 6.5 K、地影段 mean 39.8 K
- **B5 接入 @0°**：STK 5 窗 / 我方 4 窗，配对 0，漏 5、多 4，起止差 max n/a s
- **B5 接入 @5°**：STK 5 窗 / 我方 3 窗，配对 0，漏 5、多 3，起止差 max n/a s
- **B5 接入 @10°**：STK 3 窗 / 我方 3 窗，配对 0，漏 3、多 3，起止差 max n/a s
- **B5 接入 @20°**：STK 1 窗 / 我方 3 窗，配对 0，漏 1、多 3，起止差 max n/a s

## 用例 `sso_landsat`

- **B1 SGP4/TEME**：|Δr| max 2.067e-10 km (rms 6.467e-11)，|Δv| max 2.177e-13 km/s
- **B2 星下点**：Δlat max 0.173°，Δlon max 151.287°，Δalt max 20.949 km（vs 地心纬度 Δ max 0.020°——大地/地心之差与 GMST 误差分离）
- **B3 太阳几何**：方向角差 max 141.271°（mean 141.226°），Δβ max 106.413°
- **B4 地影**：日照占比 STK 70.8% vs 我方 54.2%；事件时刻差 max 2494.0 s，漏报 1、误报 1（STK 地影段 15 个）
- **B6 光照因子**：RMS 0.812，max 1.000
- **B7 太阳能**：24h 能量（对日）STK 218471 Wh vs 我方 170526 Wh（差 21.9%）；（对地）STK 71222 Wh vs 我方 48109 Wh（差 32.5%）
- **B8 电池**：min SOC STK 驱动 81.9% vs 我方驱动 70.6%；期末 SOC 差 8.7 pp
- **B9 热**：SEET 光照段均温 260.2 K、地影段均温 227.2 K；我方恒定 270.9 K（无轨道相位依赖）→ 光照段偏差 mean 10.7 K、地影段 mean 43.7 K
- **B5 接入 @0°**：STK 4 窗 / 我方 4 窗，配对 0，漏 4、多 4，起止差 max n/a s
- **B5 接入 @5°**：STK 4 窗 / 我方 4 窗，配对 0，漏 4、多 4，起止差 max n/a s
- **B5 接入 @10°**：STK 4 窗 / 我方 3 窗，配对 0，漏 4、多 3，起止差 max n/a s
- **B5 接入 @20°**：STK 2 窗 / 我方 2 窗，配对 0，漏 2、多 2，起止差 max n/a s

## 用例 `geo_goes`

- **B1 SGP4/TEME**：|Δr| max 1.616e-10 km (rms 4.354e-11)，|Δv| max 1.215e-14 km/s
- **B2 星下点**：Δlat max 6.980e-05°，Δlon max 151.287°，Δalt max 3.087e-05 km（vs 地心纬度 Δ max 3.916e-04°——大地/地心之差与 GMST 误差分离）
- **B3 太阳几何**：方向角差 max 141.262°（mean 141.226°），Δβ max 12.398°
- **B4 地影**：日照占比 STK 100.0% vs 我方 51.6%；事件时刻差 max 0.0 s，漏报 0、误报 2（STK 地影段 0 个）
- **B6 光照因子**：RMS 0.696，max 1.000
- **B7 太阳能**：24h 能量（对日）STK 307687 Wh vs 我方 162229 Wh（差 47.3%）；（对地）STK 96065 Wh vs 我方 91516 Wh（差 4.7%）
- **B8 电池**：min SOC STK 驱动 85.0% vs 我方驱动 0.0%；期末 SOC 差 100.0 pp
- **B9 热**：SEET 光照段均温 238.6 K、地影段均温 nan K；我方恒定 270.9 K（无轨道相位依赖）→ 光照段偏差 mean 32.3 K、地影段 mean n/a K

## 判定汇总

| ID | 用例 | 指标 | 实测 | 门限 | 判定 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| B1 | leo_iss | TEME |Δr| max (km) | 2.924e-10 | ≤0.001 | ✅ |  |
| B1 | leo_iss | TEME |Δv| max (km/s) | 3.297e-13 | ≤1e-6 | ✅ |  |
| B2 | leo_iss | lat max Δ (deg) | 0.181 | ≤0.02 | ❌ |  |
| B2 | leo_iss | lon max Δ (deg) | 151.287 | ≤0.02 | ❌ |  |
| B2 | leo_iss | alt max Δ (km) | 13.165 | ≤1.0 | ❌ |  |
| B3 | leo_iss | 太阳方向角差 max (deg) | 141.270 | ≤0.5 | ❌ |  |
| B3 | leo_iss | β 角差 max (deg) | 77.253 | ≤0.5 | ❌ |  |
| B4 | leo_iss | 日照占比差 (pp) | 11.674 | ≤1 | ❌ |  |
| B4 | leo_iss | 地影事件时刻差 max (s) | 2384.524 | ≤15 | ❌ | 漏 1 / 多 1 |
| B6 | leo_iss | 光照因子 RMS | 0.859 | ≤0.02 | ❌ |  |
| B7 | leo_iss | 对日姿态 24h 能量差 | 16.709 | ≤2% | ❌ | STK 196870.5 Wh vs 我方 163975.6 Wh |
| B7 | leo_iss | 对地姿态 24h 能量差 | 15.452 | ≤2% | ❌ | STK 86300.4 Wh vs 我方 72965.4 Wh |
| B8 | leo_iss | SOC 最低点差 (pp) | 6.875 | ≤5 | ❌ |  |
| B9 | leo_iss | 光照段温差 mean (K) | 6.498 | ≤10 | ✅ |  |
| B9 | leo_iss | 地影段温差 mean (K) | 39.774 | ≤10 | ❌ |  |
| B5 | leo_iss | 接入窗口@0° 起止差 max (s) | nan | ≤1 且无漏/误报 | ❌ | STK 5 窗 vs 我方 4 窗，漏 5 多 4 |
| B5 | leo_iss | 接入窗口@5° 起止差 max (s) | nan | ≤1 且无漏/误报 | ❌ | STK 5 窗 vs 我方 3 窗，漏 5 多 3 |
| B5 | leo_iss | 接入窗口@10° 起止差 max (s) | nan | ≤1 且无漏/误报 | ❌ | STK 3 窗 vs 我方 3 窗，漏 3 多 3 |
| B5 | leo_iss | 接入窗口@20° 起止差 max (s) | nan | ≤1 且无漏/误报 | ❌ | STK 1 窗 vs 我方 3 窗，漏 1 多 3 |
| B1 | sso_landsat | TEME |Δr| max (km) | 2.067e-10 | ≤0.001 | ✅ |  |
| B1 | sso_landsat | TEME |Δv| max (km/s) | 2.177e-13 | ≤1e-6 | ✅ |  |
| B2 | sso_landsat | lat max Δ (deg) | 0.173 | ≤0.02 | ❌ |  |
| B2 | sso_landsat | lon max Δ (deg) | 151.287 | ≤0.02 | ❌ |  |
| B2 | sso_landsat | alt max Δ (km) | 20.949 | ≤1.0 | ❌ |  |
| B3 | sso_landsat | 太阳方向角差 max (deg) | 141.271 | ≤0.5 | ❌ |  |
| B3 | sso_landsat | β 角差 max (deg) | 106.413 | ≤0.5 | ❌ |  |
| B4 | sso_landsat | 日照占比差 (pp) | 16.538 | ≤1 | ❌ |  |
| B4 | sso_landsat | 地影事件时刻差 max (s) | 2493.983 | ≤15 | ❌ | 漏 1 / 多 1 |
| B6 | sso_landsat | 光照因子 RMS | 0.812 | ≤0.02 | ❌ |  |
| B7 | sso_landsat | 对日姿态 24h 能量差 | 21.946 | ≤2% | ❌ | STK 218471.5 Wh vs 我方 170525.8 Wh |
| B7 | sso_landsat | 对地姿态 24h 能量差 | 32.451 | ≤2% | ❌ | STK 71221.7 Wh vs 我方 48109.4 Wh |
| B8 | sso_landsat | SOC 最低点差 (pp) | 11.250 | ≤5 | ❌ |  |
| B9 | sso_landsat | 光照段温差 mean (K) | 10.660 | ≤10 | ❌ |  |
| B9 | sso_landsat | 地影段温差 mean (K) | 43.691 | ≤10 | ❌ |  |
| B5 | sso_landsat | 接入窗口@0° 起止差 max (s) | nan | ≤1 且无漏/误报 | ❌ | STK 4 窗 vs 我方 4 窗，漏 4 多 4 |
| B5 | sso_landsat | 接入窗口@5° 起止差 max (s) | nan | ≤1 且无漏/误报 | ❌ | STK 4 窗 vs 我方 4 窗，漏 4 多 4 |
| B5 | sso_landsat | 接入窗口@10° 起止差 max (s) | nan | ≤1 且无漏/误报 | ❌ | STK 4 窗 vs 我方 3 窗，漏 4 多 3 |
| B5 | sso_landsat | 接入窗口@20° 起止差 max (s) | nan | ≤1 且无漏/误报 | ❌ | STK 2 窗 vs 我方 2 窗，漏 2 多 2 |
| B1 | geo_goes | TEME |Δr| max (km) | 1.616e-10 | ≤0.001 | ✅ |  |
| B1 | geo_goes | TEME |Δv| max (km/s) | 1.215e-14 | ≤1e-6 | ✅ |  |
| B2 | geo_goes | lat max Δ (deg) | 6.980e-05 | ≤0.02 | ✅ |  |
| B2 | geo_goes | lon max Δ (deg) | 151.287 | ≤0.02 | ❌ |  |
| B2 | geo_goes | alt max Δ (km) | 3.087e-05 | ≤1.0 | ✅ |  |
| B3 | geo_goes | 太阳方向角差 max (deg) | 141.262 | ≤0.5 | ❌ |  |
| B3 | geo_goes | β 角差 max (deg) | 12.398 | ≤0.5 | ❌ |  |
| B4 | geo_goes | 日照占比差 (pp) | 48.404 | ≤1 | ❌ |  |
| B6 | geo_goes | 光照因子 RMS | 0.696 | ≤0.02 | ❌ |  |
| B7 | geo_goes | 对日姿态 24h 能量差 | 47.275 | ≤2% | ❌ | STK 307686.6 Wh vs 我方 162228.8 Wh |
| B7 | geo_goes | 对地姿态 24h 能量差 | 4.736 | ≤2% | ❌ | STK 96065.5 Wh vs 我方 91515.9 Wh |
| B8 | geo_goes | SOC 最低点差 (pp) | 85.000 | ≤5 | ❌ |  |
| B9 | geo_goes | 光照段温差 mean (K) | 32.292 | ≤10 | ❌ |  |

**通过 9 / 51**

