/* ================================================================
 *  constants.js — Orbital & physics constants, tech databases
 * ================================================================ */

// Orbital parameters
const ORBIT_PERIOD = 95.7 * 60;           // seconds
const ECLIPSE_FRAC = 0.36;
const ECLIPSE_START = Math.PI * (1 - ECLIPSE_FRAC);
const SIGMA = 5.67e-8;                    // Stefan-Boltzmann constant

// Solar cell technology database
const CELL_TECHS = {
  tj:    { name:'TJ InGaP/GaAs/Ge',               eff:0.295, bolEff:'32.0%', eolEff:'28.8%', voc:'2.67V/cell', tcoef:0.002,  tcoefStr:'-0.20%/°C', radTol:'1e15 e/cm²' },
  imm4j: { name:'4J IMM InGaP/GaAs/InGaAsP/InGaAs', eff:0.340, bolEff:'36.8%', eolEff:'33.2%', voc:'3.42V/cell', tcoef:0.0018, tcoefStr:'-0.18%/°C', radTol:'8e14 e/cm²' },
  perov: { name:'Perovskite/Si Tandem',             eff:0.260, bolEff:'28.0%', eolEff:'22.5%', voc:'1.92V/cell', tcoef:0.0025, tcoefStr:'-0.25%/°C', radTol:'5e13 e/cm²' },
  si:    { name:'Silicon PERC',                     eff:0.220, bolEff:'24.0%', eolEff:'21.2%', voc:'0.72V/cell', tcoef:0.003,  tcoefStr:'-0.30%/°C', radTol:'1e14 e/cm²' },
};

// Coolant / heat-pipe fluid database
const COOLANTS = {
  nh3:       { name:'NH₃ 2-phase',      flow:4.2, tIn:85, tOut:45, heatCapFactor:1.0  },
  propylene: { name:'Propylene 1-phase', flow:5.8, tIn:80, tOut:50, heatCapFactor:0.72 },
  r134a:     { name:'R-134a 2-phase',    flow:6.1, tIn:78, tOut:48, heatCapFactor:0.85 },
};
