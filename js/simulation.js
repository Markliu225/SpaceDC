/* ================================================================
 *  simulation.js — Main update loop, speed control, animation
 * ================================================================ */

function update(ts) {
  if (!lastTime) lastTime = ts;
  const dt = Math.min((ts - lastTime) / 1000, 0.1); lastTime = ts;
  simTime += dt * speed; metSeconds += dt * speed; phaseTime += dt * speed;

  const angle = getAngle(simTime), eclipse = isEclipse(angle), prevEclipse = isEclipse(getAngle(simTime - dt * speed));
  const newOrbit = Math.floor(simTime / ORBIT_PERIOD) + 1;
  if (newOrbit !== orbitCount) { orbitCount = newOrbit; addLog('info', `Orbit #${orbitCount} commenced.`); }
  if (eclipse !== prevEclipse) { phaseTime = 0; eclipse ? addLog('warn', 'Entering umbra. Battery discharge.') : addLog('ok', 'Exiting eclipse. Solar online.'); }

  // Compute workload + solar first (needed for battery model)
  const tech = CELL_TECHS[currentCellTech];
  const cool = COOLANTS[currentCoolant];
  const wl   = WORKLOADS[currentWorkload];
  const peakSolar = wingCount * wingArea * 1367 * tech.eff / 1000 * (1 - (75 - 25) * tech.tcoef);
  const solarPwr = eclipse ? 0 : peakSolar * (0.97 + Math.random() * 0.03);
  const radPwr = radPanels.reduce((a, p) => a + (eclipse ? p.qRad * 0.5 : p.qRad), 0);

  // Workload-driven compute
  const computeLoad = wl.totalComputekW;                           // kW total GPU power
  const heatLoad    = computeLoad * wl.heatFraction;               // kW waste heat → radiators
  const flops = eclipse ? wl.peakFLOPS * (batSOC / 100) : wl.peakFLOPS * (wl.gpuUtil + Math.random() * (1 - wl.gpuUtil) * 0.3);
  const gpu   = eclipse ? Math.floor(wl.gpuUtil * 100 * batSOC / 100) : Math.floor(wl.gpuUtil * 100 * (0.87 + Math.random() * 0.13));

  // Battery model (uses computeLoad & solarPwr)
  batSOC = eclipse
    ? Math.max(10, batSOC - (computeLoad / 1400) * 0.85 * dt * speed / 60)
    : Math.min(100, batSOC + ((solarPwr - computeLoad) > 0 ? 1 : 0) * 1.25 * dt * speed / 60);
  logTimer += dt * speed;
  if (logTimer > 85) { logTimer = 0; const [t, m] = LOGS[logIdx % LOGS.length]; addLog(t, m); logIdx++; }

  updateWingTable(eclipse); updateRadTable(eclipse);

  // GPU temp influenced by radiator capacity vs workload heat
  const radCapacity = radPwr;
  const thermalRatio = Math.min(1, radCapacity / Math.max(1, heatLoad));
  const gpuTempBase = eclipse ? 65 + batSOC * 0.18 : 76 + Math.random() * 4;
  const gpuTemp = gpuTempBase + (1 - thermalRatio) * 25;
  const arrTemp = eclipse ? -55 + Math.random() * 5 : 62 + Math.random() * 16;
  const radSurfT = radPanels.length > 0 ? radPanels.reduce((a, p) => a + p.surfTemp, 0) / radPanels.length : 0;
  const pm = Math.floor(phaseTime / 60), ps2 = Math.floor(phaseTime % 60);

  // Trend data (push every ~1s sim time)
  trendTimer += dt * speed;
  if (trendTimer >= 1) { trendTimer = 0; pushTrend(solarPwr, radPwr, gpuTemp); }

  // --- DOM updates ---
  // Phase
  document.getElementById('phaseBox').className = 'phase-box ' + (eclipse ? 'phase-eclipse' : 'phase-sunlit');
  document.getElementById('phIcon').textContent = eclipse ? '🌑' : '☀️';
  document.getElementById('phName').textContent = eclipse ? 'ECLIPSE PASS' : 'SUNLIT PASS';
  document.getElementById('phDesc').textContent = eclipse ? `Bat ${batSOC.toFixed(0)}% SOC — discharge` : `Solar arrays ${solarPwr.toFixed(0)} kW`;
  document.getElementById('phTimer').textContent = `${p2(pm)}:${p2(ps2)}`;

  // Power gauges
  document.getElementById('rSolar').innerHTML = `${solarPwr.toFixed(0)}<span class="mg-u">kW</span>`;
  document.getElementById('rSolarBar').style.width = Math.min(100, solarPwr / Math.max(1, peakSolar) * 100) + '%';
  document.getElementById('rBat').innerHTML = `${batSOC.toFixed(0)}<span class="mg-u">%</span>`;
  document.getElementById('rBatBar').style.width = batSOC + '%';
  document.getElementById('rBatBar').style.background = batSOC < 25 ? 'linear-gradient(90deg,#ff2244,#ff6600)' : 'linear-gradient(90deg,#39ff14,#00d4ff)';
  document.getElementById('rRadP').innerHTML = `${radPwr.toFixed(0)}<span class="mg-u">kW</span>`;
  document.getElementById('rRadBar').style.width = Math.min(100, radPwr / 500 * 100) + '%';
  document.getElementById('ffSolar').textContent = eclipse ? '0 kW' : `+${solarPwr.toFixed(0)} kW`;
  document.getElementById('ffBat').textContent = eclipse ? `DIS −${Math.round(computeLoad)}kW (${batSOC.toFixed(0)}%)` : `CHG +${Math.max(0, Math.floor((solarPwr - computeLoad) * 0.3))}kW`;
  document.getElementById('ffRad').textContent = `−${radPwr.toFixed(0)} kW`;
  document.getElementById('ffComp').textContent = `−${Math.round(computeLoad)} kW`;

  // Compute gauges
  document.getElementById('rFlops').innerHTML = `${flops.toFixed(1)}<span class="mg-u">EF</span>`;
  document.getElementById('rFlopsBar').style.width = (flops / 15 * 100) + '%';
  document.getElementById('rGpu').innerHTML = `${gpu}<span class="mg-u">%</span>`;
  document.getElementById('rGpuBar').style.width = gpu + '%';
  document.getElementById('rGpuT').innerHTML = `${gpuTemp.toFixed(0)}<span class="mg-u">°C</span>`;
  document.getElementById('rGpuTBar').style.width = ((gpuTemp - 20) / 80 * 100) + '%';

  // Pane headers
  document.getElementById('phSolarOut').textContent = `${solarPwr.toFixed(0)}kW`;
  document.getElementById('phIrr').textContent = eclipse ? '0W/m²' : '1367W/m²';
  document.getElementById('phArrTemp').textContent = `${arrTemp.toFixed(0)}°C`;
  document.getElementById('phEff').textContent = eclipse ? '0%' : `${(tech.eff * 100).toFixed(1)}%`;
  document.getElementById('phQrad').textContent = `${radPwr.toFixed(0)}kW`;
  document.getElementById('phTsurf').textContent = `${radSurfT.toFixed(0)}°C`;
  document.getElementById('phDeltaT').textContent = eclipse ? '25°C' : `${cool.tIn - cool.tOut}°C`;
  document.getElementById('specTin').textContent = eclipse ? '50°C' : `${cool.tIn}°C`;
  document.getElementById('specTout').textContent = eclipse ? '25°C' : `${cool.tOut}°C`;

  // Header stats
  document.getElementById('hSolar').textContent = `${solarPwr.toFixed(0)}kW`;
  document.getElementById('hRad').textContent = `${radPwr.toFixed(0)}kW`;
  document.getElementById('hBat').textContent = `${batSOC.toFixed(0)}%`;
  document.getElementById('hGpuT').textContent = `${gpuTemp.toFixed(0)}°C`;

  // MET
  const h = Math.floor(metSeconds / 3600), m2 = Math.floor((metSeconds % 3600) / 60), s3 = Math.floor(metSeconds % 60);
  document.getElementById('met').textContent = `T+${String(h).padStart(3, '0')}:${p2(m2)}:${p2(s3)}`;
  document.getElementById('orbitNum').textContent = orbitCount;

  // System status
  const se = document.getElementById('sysStatus');
  if (gpuTemp > 95) { se.textContent = '▲ GPU OVERHEAT'; se.style.color = 'var(--danger)'; }
  else if (radPwr < heatLoad * 0.8 && !eclipse) { se.textContent = '▲ THERMAL DEFICIT'; se.style.color = 'var(--danger)'; }
  else if (batSOC < 20) { se.textContent = '▲ LOW BATTERY'; se.style.color = 'var(--danger)'; }
  else if (eclipse) { se.textContent = '◉ ECLIPSE MODE'; se.style.color = '#6688ff'; }
  else { se.textContent = '● NOMINAL'; se.style.color = 'var(--accent3)'; }

  // Bottom bar
  const raan = (156.3 + (metSeconds / 86400) * 0.9856) % 360;
  document.getElementById('bbRaan').textContent = raan.toFixed(1) + '°';
  document.getElementById('bbTa').textContent = ((angle * 180 / Math.PI) % 360).toFixed(1) + '°';
  document.getElementById('bbSun').textContent = (2.3 + Math.sin(simTime * 0.0001) * 0.5).toFixed(1) + '°';
  document.getElementById('bbEnergy').textContent = (batSOC * 14).toFixed(0) + ' kWh';
  document.getElementById('bbOrbit').textContent = `#${orbitCount}`;

  // Draw all canvases
  Orbit3D.update(eclipse); Detail3D.update(eclipse); drawSolarArray(eclipse); drawRadiator(eclipse); drawTrend();
}

function setSpeed(s) {
  speed = s;
  document.querySelectorAll('.spbtn').forEach(b => b.classList.toggle('active', b.textContent === s + '×'));
}

function animate(ts) { resizeAll(); drawStars(); update(ts); requestAnimationFrame(animate); }

// --- Initialization ---
window.addEventListener('resize', () => { initStars(); resizeAll(); Orbit3D.resize(); Detail3D.resize(); });
initStars(); resizeAll();
Orbit3D.init(); Detail3D.init();
setupDTControls();
updateCellTechDisplay();
updateCoolantDisplay();
updateWorkloadDisplay();
updateDTSummary();
requestAnimationFrame(animate);
