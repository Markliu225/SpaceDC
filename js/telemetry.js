/* ================================================================
 *  telemetry.js — Telemetry log system
 * ================================================================ */

const LOGS = [
  ['ok',   'Solar tracking nominal. Sun angle <3°.'],
  ['info', 'Station-keeping ΔV=0.2m/s done.'],
  ['ok',   'GPU T=84°C. Cold plate ΔT=8°C.'],
  ['info', 'Downlink: Tokyo→Svalbard. 12Gbps.'],
  ['warn', 'Cosmic ray DIMM-07. ECC corrected.'],
  ['ok',   'BMS: 480 cells balanced. SOH=99.8%.'],
  ['info', 'LLM batch queued. 847 jobs pending.'],
  ['ok',   'ADCS 0.01° off-nadir. RWA OK.'],
  ['info', 'SSO dawn-dusk geometry. β=2.3°.'],
  ['ok',   'Laser: 12Gbps Tenerife. BER=1e-12.'],
  ['ok',   'VCHP conductance adj. post-eclipse.'],
  ['warn', 'Wing-D 82°C. Within TML.'],
  ['ok',   'Radiator P3 NH₃ 4.2kg/s nominal.'],
  ['info', 'Orbit decay +0.1km cold-gas thrust.'],
];

function addLog(type, msg) {
  const el = document.getElementById('telemLog');
  const div = document.createElement('div');
  div.className = type;
  const h = Math.floor(metSeconds / 3600);
  const m = Math.floor((metSeconds % 3600) / 60);
  const s2 = Math.floor(metSeconds % 60);
  div.textContent = `[${String(h).padStart(3, '0')}:${p2(m)}:${p2(s2)}] ${msg}`;
  el.appendChild(div);
  while (el.children.length > 60) el.removeChild(el.firstChild);
  el.scrollTop = el.scrollHeight;
}

function p2(n) { return String(Math.floor(n)).padStart(2, '0'); }
