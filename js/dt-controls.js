/* ================================================================
 *  dt-controls.js — Digital Twin control panel handlers
 * ================================================================ */

function setupDTControls() {
  // Solar wing count
  const slWC = document.getElementById('slWingCount');
  slWC.addEventListener('input', () => {
    wingCount = parseInt(slWC.value);
    document.getElementById('valWingCount').textContent = wingCount;
    rebuildWings(); updateDTSummary();
    addLog('info', `[DT] Solar wings reconfigured: ${wingCount} wings.`);
  });

  // Solar wing area
  const slWA = document.getElementById('slWingArea');
  slWA.addEventListener('input', () => {
    wingArea = parseInt(slWA.value);
    document.getElementById('valWingArea').textContent = wingArea + 'm²';
    rebuildWings(); updateDTSummary();
  });

  // Cell tech
  const selCT = document.getElementById('selCellTech');
  selCT.addEventListener('change', () => {
    currentCellTech = selCT.value;
    rebuildWings(); updateCellTechDisplay(); updateDTSummary();
    addLog('info', `[DT] Cell tech → ${CELL_TECHS[currentCellTech].name}.`);
  });

  // Rad panel count
  const slRC = document.getElementById('slRadCount');
  slRC.addEventListener('input', () => {
    radCount = parseInt(slRC.value);
    document.getElementById('valRadCount').textContent = radCount;
    rebuildRadPanels(); updateDTSummary();
    addLog('info', `[DT] Radiator panels reconfigured: ${radCount} panels.`);
  });

  // Rad panel area
  const slRA = document.getElementById('slRadArea');
  slRA.addEventListener('input', () => {
    radArea = parseInt(slRA.value);
    document.getElementById('valRadArea').textContent = radArea + 'm²';
    rebuildRadPanels(); updateDTSummary();
  });

  // Epsilon
  const slEps = document.getElementById('slEpsilon');
  slEps.addEventListener('input', () => {
    radEpsilon = parseInt(slEps.value) / 100;
    document.getElementById('valEpsilon').textContent = radEpsilon.toFixed(2);
    radPanels.forEach(p => p.emissivity = radEpsilon);
    updateDTSummary();
  });

  // Coolant
  const selCo = document.getElementById('selCoolant');
  selCo.addEventListener('change', () => {
    currentCoolant = selCo.value;
    updateCoolantDisplay(); updateDTSummary();
    addLog('info', `[DT] Coolant → ${COOLANTS[currentCoolant].name}.`);
  });
}

function updateCellTechDisplay() {
  const tech = CELL_TECHS[currentCellTech];
  document.getElementById('ctType').textContent = tech.name;
  document.getElementById('ctBOL').textContent = tech.bolEff;
  document.getElementById('ctEOL').textContent = tech.eolEff;
  document.getElementById('ctVoc').textContent = tech.voc;
  document.getElementById('ctTcoef').textContent = tech.tcoefStr;
  document.getElementById('ctRadTol').textContent = tech.radTol;
  document.getElementById('ctArea').textContent = (wingCount * wingArea) + ' m²';
  document.getElementById('solarPaneTitle').textContent = `☀ Solar Array · ${wingCount} Wings · ${tech.name}`;
}

function updateCoolantDisplay() {
  const cool = COOLANTS[currentCoolant];
  document.getElementById('caFluid').textContent = cool.name;
  document.getElementById('caFlow').textContent = cool.flow.toFixed(1) + ' kg/s';
  document.getElementById('caArea').textContent = (radCount * radArea).toFixed(0) + ' m²';
  document.getElementById('radPaneTitle').textContent = `🌡 Radiative Cooling · ${radCount} Panels · ${cool.name} VCHP`;
}

function updateDTSummary() {
  const tech = CELL_TECHS[currentCellTech];
  const cool = COOLANTS[currentCoolant];
  const totalSolarArea = wingCount * wingArea;
  const peakSolar = (totalSolarArea * 1367 * tech.eff / 1000) * (1 - (75 - 25) * tech.tcoef);
  const totalRadArea = radCount * radArea;
  const Tsurf = 58 + 273.15;
  const peakQ = (radEpsilon * SIGMA * totalRadArea * 0.9 * (Tsurf ** 4 - 2.7 ** 4)) / 1000 * cool.heatCapFactor;
  const balance = peakSolar - 1000;

  document.getElementById('dsSolarArea').textContent = totalSolarArea + ' m²';
  document.getElementById('dsPeakPwr').textContent = peakSolar.toFixed(0) + ' kW';
  document.getElementById('dsRadArea').textContent = totalRadArea.toFixed(0) + ' m²';
  document.getElementById('dsPeakQ').textContent = peakQ.toFixed(0) + ' kW';

  const balEl = document.getElementById('dsBalance');
  if (balance > 0) {
    balEl.className = 'val'; balEl.textContent = `+${balance.toFixed(0)} kW surplus`;
  } else {
    balEl.className = 'danger-val'; balEl.textContent = `${balance.toFixed(0)} kW DEFICIT`;
  }

  // Update pane titles
  document.getElementById('solarPaneTitle').textContent = `☀ Solar Array · ${wingCount} Wings · ${tech.name}`;
  document.getElementById('radPaneTitle').textContent = `🌡 Radiative Cooling · ${radCount} Panels · ${cool.name} VCHP`;
  document.getElementById('phEpsDisp').textContent = radEpsilon.toFixed(2);

  // Update cell tech & coolant display
  document.getElementById('ctArea').textContent = totalSolarArea + ' m²';
  document.getElementById('caArea').textContent = totalRadArea.toFixed(0) + ' m²';
  document.getElementById('caFlow').textContent = cool.flow.toFixed(1) + ' kg/s';

  // Update cost estimates
  const solarCost = Math.round(totalSolarArea * 0.023);
  const radCost = Math.round(totalRadArea * 0.033);
  document.getElementById('costSolar').textContent = '$' + solarCost + 'M';
  document.getElementById('costRad').textContent = '$' + radCost + 'M';
  const totalCost = 120 + 85 + solarCost + 42 + radCost + 256 + 38 + 22 + 45 + 80;
  document.getElementById('costTotal').textContent = '$' + totalCost + 'M';
  const revenue = 420, opex = 38;
  const be = totalCost / (revenue - opex);
  document.getElementById('costBreakeven').textContent = '~' + be.toFixed(1) + ' yrs';
}
