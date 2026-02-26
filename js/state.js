/* ================================================================
 *  state.js — Simulation state, dynamic data models, trend buffer
 * ================================================================ */

// --- Simulation state ---
let simTime = 0, speed = 60, metSeconds = 0, orbitCount = 1;
let batSOC = 87, phaseTime = 0, lastTime = null;
let logIdx = 0, logTimer = 0;

// --- Digital-twin configurable parameters ---
let wingCount = 8, wingArea = 350, currentCellTech = 'tj';
let radCount = 6, radArea = 143.3, radEpsilon = 0.92, currentCoolant = 'nh3';
let currentWorkload = 'llama70b_train';

// --- Dynamic arrays ---
let wings = [], radPanels = [];

function rebuildWings() {
  const tech = CELL_TECHS[currentCellTech];
  wings = Array.from({ length: wingCount }, (_, i) => ({
    id: i + 1,
    name: `W${String.fromCharCode(65 + (i % 26))}${i >= 26 ? Math.floor(i / 26) : ''}`,
    cells: 240, area: wingArea,
    temp: 65 + Math.random() * 10,
    efficiency: tech.eff + (Math.random() - 0.5) * 0.005,
    output: 0
  }));
}

function rebuildRadPanels() {
  radPanels = Array.from({ length: radCount }, (_, i) => ({
    id: i + 1, area: radArea,
    surfTemp: 55 + Math.random() * 8,
    emissivity: radEpsilon,
    viewFactor: 0.85 + Math.random() * 0.1,
    qRad: 0
  }));
}

// Build initial arrays
rebuildWings();
rebuildRadPanels();

// --- Trend data buffer ---
const TREND_MAX = 600;
const trendData = { solar: [], bat: [], rad: [], gpuT: [] };
let trendTimer = 0;

function pushTrend(solarPwr, radPwr, gpuTemp) {
  trendData.solar.push(solarPwr);
  trendData.bat.push(batSOC);
  trendData.rad.push(radPwr);
  trendData.gpuT.push(gpuTemp);
  if (trendData.solar.length > TREND_MAX) {
    trendData.solar.shift(); trendData.bat.shift();
    trendData.rad.shift();   trendData.gpuT.shift();
  }
}
