# -*- coding: utf-8 -*-
"""English static content of the SDTwin thermal module test report: groups, environment lines, cases and static tables."""

GROUPS_EN = [
    ('Common Data and Parameter Assembly', ['DM-001', 'PA-001']),
    ('Surface Environment and Radiation', ['EN-001', 'EN-002', 'EN-003']),
    ('Component Heat Transfer and Temperature Derivatives', ['HT-001', 'HT-002', 'HT-003']),
    ('Electrical/Thermal Coupling', ['EC-001']),
    ('Finite-Element Benchmarks', ['FE-001', 'FE-002', 'FE-003', 'FE-004']),
    ('Numerical Calculation and End-to-End Operation', ['NI-001', 'NI-002', 'NI-003']),
]

ENV_LINES_EN = ['Design cold case: β angle 0°, solar constant 1321 W/m², albedo 0.20, Earth infrared 206 W/m².',
                'Mean environment case: β angle 0°, solar constant 1371 W/m², albedo 0.31, Earth infrared 241 W/m².',
                'Design hot case: β angle 75°, solar constant 1423 W/m², albedo 0.40, Earth infrared 286 W/m².']

CASES_EN = {
    'DM-001': dict(
        func='ThermalParameters, ThermalState, ThermalInputs, ThermalEvaluation', name='Common Data Objects',
        req='TH-01, TH-02, TH-04',
        basis='Section 3.2; Section 5.1, Table 6; Section 6.1; Appendix A',
        intro='This project verifies the four common data objects and the package exports of the SDTwin thermal module, '
              'specified in Section 5.1 and Section 3.2 of the design report respectively.',
        goal='Verify the fields, array dimensions, array order, and construction checks of ThermalParameters, ThermalState, '
             'ThermalInputs, and ThermalEvaluation, and check the public exports of the thermal package.',
        pre=['The four data objects are implemented according to Table 6 of the design report, and the thermal package is '
             'organized according to Section 3.2.'],
        input=['Nominal construction: C_J_K holds six positive values, R_K_W holds five positive values, temperature_K holds '
               'six positive values, and the environment and four powers of ThermalInputs share a timestamp.',
               'Q_B_W set to a positive value and, separately, to a negative value.',
               'Invalid construction: mismatched array dimensions, nonfinite values, nonpositive thermal capacitance or '
               'resistance, and mismatched run identifiers or times.'],
        steps=['Construct the four objects from the nominal inputs and read all fields.',
               'Check that the temperature order is $S$, $J$, $C$, $B$, $D$, $R$, the path order is SR, JC, CR, BR, DR, and '
               'the environment and radiation array order is $S$, $R$.',
               'Check that Q_B_W retains its sign.',
               'Inject the invalid constructions one at a time and record the error messages.',
               'Attempt to modify ThermalParameters after the run starts, and check that trial states and accepted states '
               'use separate records.',
               'Check that __init__.py exports the four data types and five functions listed in Appendix A.'],
        expect=['Fields, dimensions, and order conform to Table 6.',
                'Invalid constructions are rejected, and each error message names the specific field.',
                'The parameter object is read-only after the run starts, and trial states do not overwrite accepted states.',
                'The public exports match Appendix A.'],
        accept='All fields, dimensions, and orders shall match Table 6. All invalid constructions shall produce deterministic '
               'errors. The read-only, state-separation, and public-export checks shall all pass.',
        focus='Fields, dimensions, order, read-only parameters, and state separation'),
    'PA-001': dict(
        func='assemble_thermal_parameters', name='Thermal Capacitance and Resistance Assembly', req='TH-04',
        basis='Section 4.5, Equation T5; Section 5.2; Section 9.4',
        intro='This project verifies the function of the SDTwin thermal module that assembles component thermal capacitances '
              'and connection thermal resistances according to Equation T5.',
        goal='Verify that assemble_thermal_parameters assembles thermal capacitances, thermal resistances, and surface '
             'parameters from asset materials and connections according to T5, and check override precedence, duplicate '
             'material assignment, equivalent total resistance, and provenance records.',
        pre=['components contains the instance-to-node assignments, material masses, specific heats, and surface records.',
             'connections gives the length, thermal conductivity, cross-sectional area, and contact resistance of SR, JC, CR, '
             'BR, and DR, or gives an equivalent total resistance confirmed by test.',
             'A hand-calculation table prepared from the same inputs has been reviewed.'],
        input=['Example in Section 4.5 of the design report: a material with a mass of 1 kg and a specific heat of '
               '1000 J·kg^{−1}·K^{−1}.',
               'MBSU box from the ISS model parameter table: 0.94 m×0.84 m×0.51 m, density 300 kg/m³, specific heat '
               '900 J·kg^{−1}·K^{−1}; radiator panel areal density 8 kg/m², specific heat 900 J·kg^{−1}·K^{−1}.',
               'A set of overrides that changes the material mass of one component and the contact resistance of one '
               'connection.',
               'Invalid inputs: zero or negative mass, specific heat, length, thermal conductivity, or cross-sectional area; '
               'negative contact resistance; one material portion assigned to two components; duplicate surfaces; undefined '
               'connections; a contact resistance given again for an equivalent total resistance that already includes it.'],
        steps=['Call assemble_thermal_parameters, read C_J_K and R_K_W, and compare them item by item with the '
               'hand-calculation table.',
               'Reassemble with the overrides added and check that the overrides take precedence over the asset parameter set.',
               'Check that heat-pipe or liquid-cooling equivalent paths read the total resistance directly and do not add an '
               'already included contact resistance again.',
               'Inject the invalid inputs one at a time and record the error messages.',
               'Check that ThermalParameters records the resolved values, units, asset revisions, and provenance, and check '
               'that the function does not create or update operating temperatures.'],
        expect=['Thermal capacitances and resistances agree with the hand calculation, and the overrides take effect.',
                'Each invalid input identifies the offending record, and no default device values are produced.',
                'The function produces no operating temperatures.'],
        accept='The relative error of thermal capacitances and resistances shall not exceed 1×10^{−12}. The thermal '
               'capacitance shall be 1000 J/K for the Section 4.5 example and 108.7 kJ/K for the MBSU box, and the radiator '
               'panel thermal capacitance per unit area shall be 7.2 kJ·m^{−2}·K^{−1}. All invalid inputs shall produce '
               'deterministic errors.',
        focus='T5 capacitances and resistances, overrides, duplicate assignment, provenance'),
    'EN-001': dict(
        func='prepare_surface_environment', name='Surface Environment Preparation', req='TH-03',
        basis='Section 5.3; Section 6.1',
        intro='This project verifies the function of the SDTwin thermal module that prepares synchronized surface environment '
              'inputs.',
        goal='Verify that prepare_surface_environment obtains cos_incidence for each surface from synchronized orbit, '
             'attitude, and surface records, and arranges the environment inputs in asset surface order.',
        pre=['orbit_input contains run_id, time_s, epoch, position_m, sun_position_m, frame, quaternion_xyzw, and G_W_m2, '
             'and the satellite position and the Earth-to-Sun vector have been converted to GCRS.',
             'earth_flux carries the same run identifier and time as orbit_input.',
             'An independent vector and quaternion calculation program is available.'],
        input=['Constructed attitudes: the identity quaternion, a 90° rotation about each of the three axes, and arbitrary '
               'combined rotations.',
               'Surface normals: the six body face directions and one arbitrary direction.',
               'Orbit output over one full revolution of a circular orbit at 400 km altitude, including the eclipse phase; '
               'G is given by sun_intensity with include_eclipse true.',
               'Invalid inputs: an unnormalized quaternion or normal, a zero difference between the satellite position and '
               'the Sun vector, an unconverted TEME position, an unsupported frame, mismatched surface identifiers, and a '
               'missing earth_flux record.'],
        steps=['Subtract the satellite position from the Earth-to-Sun vector and normalize the result to obtain the '
               'satellite-to-Sun direction; calculate cos_incidence for each constructed attitude and compare it with the '
               'independent calculation.',
               'Calculate one full orbit and check that the returned dictionary contains run_id, time_s, surface_ids, '
               'G_W_m2, cos_incidence, albedo_W_m2, and infrared_W_m2, and that the surface arrays have equal lengths and '
               'follow asset surface order.',
               'Check that G_W_m2 is identical to the Orbit output at every point and is not multiplied by an eclipse factor '
               'again.',
               'Inject the invalid inputs one at a time and record how each is handled.'],
        expect=['cos_incidence agrees with the independent calculation, and surfaces facing away from the Sun receive '
                'negative values.',
                '$G$ is zero in eclipse and is supplied only by Orbit.',
                'The function does not change temperatures, and invalid inputs are rejected.'],
        accept='The cos_incidence error shall not exceed 1×10^{−12}. Over the full orbit, $G$ shall be identical to the Orbit '
               'output at every point. All invalid inputs shall produce deterministic errors.',
        focus='Sun direction, quaternion rotation, incidence cosine, eclipse counted once'),
    'EN-002': dict(
        func='calculate_surface_heat', name='Surface Absorption and Emission', req='TH-03',
        basis='Section 4.4, Equation T4; Section 5.4',
        intro='This project verifies the function of the SDTwin thermal module that calculates the heat absorbed by exposed '
              'surfaces and their surface emission according to Equation T4.',
        goal='Verify that calculate_surface_heat calculates, for each surface according to T4, the direct solar, albedo, and '
             'infrared absorption and the surface emission, sums them by $S$ and $R$ into Q_env_W and Q_emit_W, and returns '
             'absorbed_solar_S_W.',
        pre=['Surface areas, absorptivities, and emissivities are assembled.',
             'EN-001 has passed.'],
        input=['Example in Section 4.4 of the design report: area 2 m², direct irradiance 1000 W/m², absorptivity 0.8.',
               'Three orientations: facing the Sun, edge-on to the Sun, and facing away from the Sun; two environments: '
               'albedo only and infrared only.',
               'Component temperatures of 200 K, 300 K, and 400 K.',
               'Invalid inputs: zero or negative temperature, negative irradiance, mismatched run identifier or time, and a '
               'temperature outside the applicable range of the material parameters.'],
        steps=['Calculate Q_env_W, Q_emit_W, and absorbed_solar_S_W for each example and compare them with the hand '
               'calculation.',
               'Check that direct irradiance is $G$ multiplied by the nonnegative incidence cosine, that direct and albedo '
               'irradiance are multiplied by absorptivity and infrared by emissivity, and that the area is not projected '
               'again.',
               'Check that surface emission is calculated from the fourth power of the absolute temperature of the owning '
               'component.',
               'Check that the front and back of the solar array are calculated separately and then summed, and that '
               'absorbed_solar_S_W includes only the direct solar power absorbed by the solar array.',
               'Inject the invalid inputs one at a time.'],
        expect=['The absorbed power in the Section 4.4 example is 1600 W, and direct absorption is zero when the surface '
                'faces away from the Sun.',
                'When a temperature lies outside the applicable material range, the limitation is reported.',
                'The function does not modify the state.'],
        accept='The relative error against the hand calculation shall not exceed 1×10^{−12}. The ratio of the emitted power '
               'at 400 K to that at 200 K shall be 16. All invalid inputs shall produce deterministic outcomes.',
        focus='T4 direct, albedo, and infrared absorption and surface emission'),
    'EN-003': dict(
        func='earth_flux environment input', name='Earth Albedo and Infrared Inputs', req='TH-03',
        basis='Section 4.4, Table 5; Section 5.3; Section 9.4',
        intro='This project verifies the Earth albedo and Earth infrared inputs supplied to Equation T4 of the SDTwin thermal '
              'module. Section 5.3 of the design report specifies that these two inputs come from additional environmental '
              'data and cannot be inferred from the solar irradiance of Orbit; this project checks that data source.',
        goal='Verify the albedo_W_m2 and infrared_W_m2 values that earth_flux supplies for each surface_id, and confirm that '
             'the Earth view factor and the albedo calculation of each surface are correct.',
        pre=['earth_flux is connected according to Section 5.3 and carries the same run identifier and time as orbit_input.'],
        input=['Circular orbit at 400 km altitude, β angle 0° and 75°.',
               'Albedo and Earth infrared at the ISS design case values: cold case 0.20 and 206 W/m², mean case 0.31 and '
               '241 W/m², hot case 0.40 and 286 W/m².',
               'Surface orientations: facing Earth, facing away from Earth, perpendicular to the local vertical, and '
               'tracking the Sun.'],
        steps=['Compare the view factor of an Earth-facing flat plate with the analytical value, which equals the square of '
               'the ratio of the Earth radius to the orbit radius.',
               'Compare the other orientations with numerical integration over the visible Earth surface.',
               'Export the albedo and infrared heat loads of the solar array wings and radiators from the solved ISS '
               'finite-element model and compare them with the earth_flux results.',
               'Delete one albedo or infrared record and check that the system identifies the unconfigured field according '
               'to Section 9.4 and does not treat the missing value as zero.'],
        expect=['The view factor of the Earth-facing plate agrees with the analytical value.',
                'The albedo and infrared irradiance for each orientation agree with the numerical integration.',
                'When a record is missing, the unconfigured field is reported.'],
        accept='The view factor of the Earth-facing plate at 400 km shall be 0.8855, with an error not exceeding 0.1%. For '
               'the other orientations, differences from the numerical integration shall not exceed 1%. Differences from '
               'the finite-element heat loads shall not exceed 3%. All missing records shall be reported.',
        focus='Earth-facing view factor, albedo and infrared irradiance, missing fields'),
    'HT-001': dict(
        func='calculate_heat_flows', name='Component Heat-Transfer Calculation', req='TH-01',
        basis='Section 4.2, Equation T2; Section 5.5',
        intro='This project verifies the function of the SDTwin thermal module that calculates connection heat flows '
              'according to Equation T2.',
        goal='Verify that calculate_heat_flows evaluates T2 in the fixed order SR, JC, CR, BR, DR and returns signed heat '
             'flows.',
        pre=['PA-001 has passed, and the thermal resistances of the five connections are assembled.'],
        input=['Battery example in Section 4.3 of the design report: $T_B$ is 303 K, $T_R$ is 300 K, and $R_BR$ is 0.5 K/W.',
               'Cases with the two endpoint temperatures swapped and with equal endpoint temperatures.',
               'Invalid inputs: a missing node, mismatched array order, zero or negative resistance, and nonfinite inputs.'],
        steps=['Calculate the five connection heat flows, compare them with the hand calculation, and check that the returned '
               'dictionary contains run_id, time_s, and q_W.',
               'Swap the two endpoint temperatures and check that the heat flow changes sign while its magnitude is '
               'unchanged.',
               'Check that a positive value means transfer from the first node in the path name to the second.',
               'Inject the invalid inputs one at a time.'],
        expect=['The example heat flow $q_BR$ is 6 W, −6 W after the swap, and zero at equal temperatures.',
                'Each path is evaluated once, and the function performs no state update.',
                'Invalid inputs produce errors, and neither zero resistance nor ad hoc clipping of the heat flow stands in '
                'for the actual path.'],
        accept='The relative error against the hand calculation shall not exceed 1×10^{−12}. All invalid inputs shall produce '
               'deterministic errors.',
        focus='T2 signed heat flows, path order'),
    'HT-002': dict(
        func='thermal_derivative', name='Temperature Derivatives and Overall Heat Balance', req='TH-01',
        basis='Section 4.1, Equation T1; Section 4.3, Equation T3; Section 5.6',
        intro='This project verifies the temperature derivatives of the SDTwin thermal module, formed according to Equation '
              'T3, and checks the overall heat balance of Equation T1.',
        goal='Verify that thermal_derivative returns, in one call according to T3, the temperature derivatives of $S$, $J$, '
             '$C$, $B$, $D$, and $R$ and the ThermalEvaluation, and that the result satisfies T1.',
        pre=['EN-002 and HT-001 have passed.'],
        input=['Battery example in Section 4.3 of the design report: $C_B$ is 1000 J/K, $T_B$ is 303 K, $T_R$ is 300 K, '
               '$R_BR$ is 0.5 K/W, and $Q_B$ is 10 W.',
               'A total of 1000 randomly generated sets of temperatures, four powers, and environment inputs.'],
        steps=['Calculate the heating rate of the battery example.',
               'For the random inputs, calculate the sum of the products of component thermal capacitance and temperature '
               'derivative, and compare it with the right-hand side of T1.',
               'Check that each heat flow is subtracted at the outgoing node and added at the incoming node.',
               'Check that ThermalEvaluation contains dT_dt_K_s, q_W, Q_env_W, Q_emit_W, T_B_K, and T_J_K, and that T_B_K '
               'and T_J_K copy the corresponding input temperatures and are not new integrated states.'],
        expect=['The heating rate of the battery example is 0.004 K/s.',
                'The summed rate of heat storage of all components equals the right-hand side of T1.'],
        accept='The error in the heating rate of the example shall not exceed 1×10^{−12} K/s. The ratio of the overall '
               'heat-balance residual to the total input power shall not exceed 1×10^{−12}.',
        focus='T3 temperature derivatives, T1 overall heat balance'),
    'HT-003': dict(
        func='thermal_derivative and the numerical solver', name='Comparison with Analytical Solutions', req='TH-01',
        basis='Section 4.3, Equation T3; Chapter 8, Table 8',
        intro='This project verifies the temperature integration results of the SDTwin thermal module using examples that '
              'have analytical solutions.',
        goal='Verify the temperature evolution over time obtained by combining thermal_derivative with the numerical solver '
             'of Chapter 8.',
        pre=['HT-002 has passed.',
             'RK45 is selected as the initial integration method according to Chapter 8, and the tolerances and maximum '
             'step are configured.'],
        input=['Single-node step: the cold-plate temperature is held constant, $P_load$ of the computing node steps from zero '
               'to 300 W, $C_J$ is 500 J/K, and $R_JC$ is 0.1 K/W.',
               'Series steady state: the computing node connects through the cold plate to a radiator held at constant '
               'temperature, and $P_load$ is 300 W.',
               'Radiative equilibrium: the radiator has only a fixed input power and its own surface emission.'],
        steps=['Integrate the single-node step and compare it with the exponential solution.',
               'Integrate the series example to steady state; the temperature difference between the computing node and the '
               'radiator should equal the power multiplied by the sum of $R_JC$ and $R_CR$.',
               'Integrate the radiative-equilibrium example to steady state; the fourth power of the steady-state '
               'temperature should equal the input power divided by the product of emissivity, the Stefan-Boltzmann '
               'constant, and the radiating area.'],
        expect=['The numerical solutions of the three examples agree with the analytical solutions.'],
        accept='The step-response error shall not exceed 0.001 K over the whole run. The errors of the two steady-state '
               'examples shall not exceed 0.001 K.',
        focus='Exponential response, series-resistance steady state, radiative equilibrium'),
    'EC-001': dict(
        func='ThermalInputs and thermal_derivative', name='Electrical/Thermal Coupling', req='TH-02',
        basis='Section 4.1; Section 4.3; Section 5.6; Section 6.1',
        intro='This project verifies the function of the SDTwin thermal module that uses the four power ports of Power.',
        goal='Verify that P_pv_W, P_load_W, Q_B_W, and Q_D_W enter the corresponding components according to T3, and check '
             'the sign constraints, the upper limit on photovoltaic output, the validity of the Power result, and the single '
             'ownership of battery temperature.',
        pre=['HT-002 has passed.',
             'solve_power_allocation of Power is available, or inputs constructed from the PowerResult fields are used.'],
        input=['$P_pv$ takes values between zero and the current absorbed_solar_S_W; $P_load$ takes values between zero and '
               'the rated power; $Q_B$ takes positive and negative values; $Q_D$ takes positive values.',
               'Invalid inputs: a negative P_pv_W, P_load_W, or Q_D_W; $P_pv$ greater than absorbed_solar_S_W; valid false; '
               'event_required true.'],
        steps=['Change one power at a time and check that only the derivative of the corresponding component changes, by an '
               'amount equal to the power change divided by the thermal capacitance of that component: $P_pv$ affects only '
               '$S$, $P_load$ only $J$, $Q_B$ only $B$, and $Q_D$ only $D$.',
               'Set $Q_B$ to a negative value and check that the battery temperature derivative decreases accordingly.',
               'Reduce $P_pv$ to represent the controller curtailing generation, and check that the energy not exported '
               'remains in the energy balance of the solar array.',
               'Inject the invalid inputs one at a time.',
               'Run one orbit jointly with Power and confirm that the battery temperature is updated only in the thermal '
               'module and is returned to Power as T_B_K.'],
        expect=['Each power enters the correct component, and its sign is retained.',
                'An invalid Power result does not enter the thermal derivative; the thermal module neither repairs invalid '
                'electrical powers nor decides load restart.',
                'Battery temperature is updated only once.'],
        accept='The relative error of the derivative changes against the hand calculation shall not exceed 1×10^{−12}. All '
               'invalid inputs shall produce deterministic outcomes. During the joint run, the battery temperature shall be '
               'updated only in the thermal module.',
        focus='Four power ports, signs and upper limit, single ownership of battery temperature'),
    'FE-001': dict(
        func='Solar array $S$', name='Solar Array Node Finite-Element Benchmark', req='TH-01, TH-03',
        basis='Section 4.3, first line of Equation T3; Section 4.4, Equation T4; Section 4.5, Equation T5',
        intro='This project verifies the solar array node of the SDTwin thermal module against finite-element results for '
              'the US solar array wings of the ISS.',
        goal='Verify the solar array temperature calculated by the first line of T3 and by T4, and check environmental '
             'absorption, the subtraction of actual electrical output, and surface emission from the front and back faces.',
        pre=['The third-orbit time histories of the three finite-element cases and the model parameter table are available.',
             'The attitude quaternion keeps the front normal of the solar array pointed at the Sun, matching the '
             'Sun-pointing law of the solar array wings in the finite-element model.',
             'The finite-element model excludes conduction between the solar array wings and the radiators; the SR '
             'connection takes a very large resistance to represent no conduction, and this test configuration is recorded '
             'according to Section 9.4.'],
        input=['Front absorptivity 0.72 and emissivity 0.82, back absorptivity 0.55 and emissivity 0.85, and thermal '
               'capacitance per unit area 1.6 kJ·m^{−2}·K^{−1}, all taken from the finite-element model parameter table.',
               '$P_pv$ taken as the generation fraction 0.073 multiplied by the direct solar power received by the solar '
               'array, representing the actual electrical output supplied by Power.',
               'Design cold case: β angle 0°, solar constant 1321 W/m², albedo 0.20, Earth infrared 206 W/m².',
               'Mean environment case: β angle 0°, solar constant 1371 W/m², albedo 0.31, Earth infrared 241 W/m².',
               'Design hot case: β angle 75°, solar constant 1423 W/m², albedo 0.40, Earth infrared 286 W/m².',
               'Circular orbit at 400 km altitude with a period of 5553.6 s.'],
        steps=['Generate orbit_input and earth_flux for each case.',
               'Integrate with the numerical settings of Chapter 8 until successive orbits repeat, splitting the integration '
               'at eclipse boundaries, and take the last orbit.',
               'Compare the minimum, mean, and maximum temperatures with the third orbit of the finite-element mean solar '
               'array wing temperature.',
               'Recalculate once with albedo and infrared disabled, and record this simplification and the temperature '
               'difference according to Section 9.4.'],
        expect=['The temperature curves of the three cases coincide with those of the finite-element model.',
                'With albedo and infrared disabled, the temperatures are markedly lower.'],
        accept='For all three cases, the differences between the minimum, mean, and maximum temperatures and the '
               'finite-element results shall not exceed 3 K.',
        focus='Environmental absorption, subtraction of actual electrical output, two-sided surface emission'),
    'FE-002': dict(
        func='Common radiator $R$', name='Radiator Node Finite-Element Benchmark', req='TH-01, TH-03',
        basis='Section 4.3, sixth line of Equation T3; Section 4.4, Equation T4; Section 4.5, Equation T5; Chapter 10',
        intro='This project verifies the radiator node of the SDTwin thermal module against finite-element results for the '
              'radiators of the ISS External Active Thermal Control System.',
        goal='Verify the radiator temperature calculated by the sixth line of T3 and by T4, and check the branch heat inputs, '
             'environmental absorption, two-sided surface emission, and thermal capacitance.',
        pre=['The finite-element time histories of radiator heat input for each loop and the mean panel temperatures of the '
             'three radiator units are available.',
             'The sum of $q_SR$, $q_CR$, $q_BR$, and $q_DR$ is replaced by the finite-element radiator heat input.',
             'The attitude quaternion follows the finite-element radiator pointing law: edge to the Sun in sunlight and face '
             'to the Earth in eclipse.'],
        input=['Each loop: 24 panels, one-side area 220.7 m²; $C_R$ calculated by T5 from panel mass and specific heat, with '
               'the thermal capacitance of the liquid ammonia added, 1.61 MJ/K in total.',
               'Z-93 white coating: absorptivity 0.15 in the cold case, 0.20 in the mean case, and 0.24 in the hot case; '
               'emissivity 0.90 to 0.91.',
               'Design cold case: β angle 0°, solar constant 1321 W/m², albedo 0.20, Earth infrared 206 W/m².',
               'Mean environment case: β angle 0°, solar constant 1371 W/m², albedo 0.31, Earth infrared 241 W/m².',
               'Design hot case: β angle 75°, solar constant 1423 W/m², albedo 0.40, Earth infrared 286 W/m².'],
        steps=['Drive the radiator node with the finite-element heat-input time history, integrate three orbits from the '
               'finite-element initial temperature, and split the integration at eclipse boundaries.',
               'Take the third orbit and compare it with the average of the mean panel temperatures of the three radiator '
               'units.',
               'Record the difference between the coldest finite-element panel and the mean temperature at the same instant.'],
        expect=['The mean temperature is close to the finite-element result.',
                'Radiative obstruction between the two wings and panel temperature differences along the flow direction '
                'are possible residual sources. Section 4.4 and Chapter 10 of the design report state that this version neglects '
                'mutual obstruction between components, radiation exchange between components, and local temperature '
                'gradients.'],
        accept='For both loops in all three cases, the third-orbit mean temperature difference shall not exceed 5 K.',
        focus='Branch heat inputs, environmental absorption, two-sided surface emission, thermal capacitance'),
    'FE-003': dict(
        func='Computing node $J$ and cold plate $C$', name='Computing Node and Cold Plate Finite-Element Benchmark',
        req='TH-01, TH-04',
        basis='Section 4.3, second and third lines of Equation T3; Section 4.5, Equation T5; Chapter 10',
        intro='This project verifies the computing-node-to-cold-plate heat-transfer calculation of the SDTwin thermal module '
              'against finite-element results for ISS cold-plate equipment. Chapter 10 of the design report provides that '
              'finite elements may identify equivalent resistances for uncertain installation paths; on that basis, this '
              'project checks the composition of the JC resistance.',
        goal='Verify the second line of T3 and the second line of T5, and confirm that the mean temperature of uniformly '
             'heated equipment can be represented by $R_JC$.',
        pre=['The finite-element part statistics and loop heat breakdown of the mean environment case are available.',
             'The cold-plate thermal capacitance takes a very large value and starts at the coolant temperature, and the CR '
             'connection takes a very large resistance, so that the cold-plate temperature stays at the coolant '
             'temperature, matching the cold-plate boundary of the finite-element model.'],
        input=['MBSU 495 W, cold-plate face 0.79 m²; DDCU 694 W, cold-plate face 0.56 m²; IEA 6000 W, cold-plate face '
               '13.5 m².',
               'Cold-plate heat-transfer coefficient 60 W·m^{−2}·K^{−1}, equivalent equipment thermal conductivity '
               '150 W·m^{−1}·K^{−1}, coolant 2.8 °C.',
               '$P_load$ apportions the FE loop cold-plate heat input among the devices. The roughly 5.4% remainder '
               'includes external radiation and storage, which current data cannot separate. The design-report '
               'computing node does not include an external surface-radiation path.'],
        steps=['Calculate $R_JC$ by the second line of T5: the contact part is the reciprocal of the product of the '
               'cold-plate heat-transfer coefficient and the cold-plate area; the conduction part uses one third of the '
               'equipment thickness as the conduction length, which is the equivalent length for the mean temperature when '
               'heat is generated uniformly within the equipment.',
               'Integrate to steady state, where $T_J$ equals the cold-plate temperature plus $P_load$ multiplied by $R_JC$.',
               'Compare with the finite-element third-orbit mean temperature.'],
        expect=['The mean temperatures of the three equipment types agree with the finite-element results.'],
        accept='The mean temperature difference shall not exceed 1 K.',
        focus='JC resistance composition, mean temperature of uniformly heated equipment'),
    'FE-004': dict(
        func='Computing node, cold plate, and radiator chain', name='Whole-Satellite Finite-Element Chain Benchmark',
        req='TH-01, TH-04',
        basis='Section 3.1, Figure 1; Section 4.3, Equation T3; Appendix B',
        intro='This project verifies the heat-transfer chain of the SDTwin thermal module in Figure 1, from the computing node '
              'through the cold plate to the radiator, against finite-element results for a single satellite.',
        goal='Verify whether the three components $J$, $C$, and $R$ and the two connections JC and CR can represent the '
             'temperature drop from the computing equipment to the radiator.',
        pre=['The whole-satellite COMSOL results completed on 30 August 2026 are available, including the time histories of '
             'the GPU baseplate, bus, and radiator temperatures.',
             'The thermal pad and heat pipe parameters of the whole-satellite model are converted into $R_JC$ and $R_CR$ '
             'according to T5, and the conversion method and sources are recorded.'],
        input=['Two examples: 12 V100 GPUs and 12 A100 GPUs.',
               'The same orbit, attitude, and load power histories as the finite-element model.'],
        steps=['Assemble the three components $J$, $C$, and $R$ from the whole-satellite model parameters.',
               'Apply the same power history and run five orbits.',
               'Take the fourth and fifth orbits and compare the mean GPU baseplate temperature and the mean radiator '
               'temperature.'],
        expect=['The chain from the computing node through the cold plate to the radiator reproduces the temperature '
                'difference between the computing equipment and the radiator. In the same comparison, the single-node model '
                'is 12 to 15 °C lower than the GPU baseplate.'],
        accept='In both the fourth and fifth orbits, the mean temperature differences of the GPU baseplate and of the '
               'radiator shall not exceed 5 K.',
        focus='Complete temperature drop from the computing equipment to the radiator'),
    'NI-001': dict(
        func='Numerical solver settings', name='Numerical Calculation and Eclipse Boundaries', req='TH-01',
        basis='Chapter 8, Table 8; Chapter 7',
        intro='This project verifies the numerical settings of the SDTwin thermal module specified in Chapter 8 of the design '
              'report.',
        goal='Verify the adaptive ODE method, tolerances, maximum step, handling of eclipse and load-switching boundaries, and '
             'output sampling.',
        pre=['The mean environment case of FE-001 can be run.'],
        input=['Integration methods RK45 and Radau.',
               'Relative tolerances 1×10^{−6} and 1×10^{−8}; temperature absolute tolerances 1×10^{−6} K and 1×10^{−8} K; '
               'maximum steps 60 s and 10 s.',
               'Output intervals 10 s and 60 s; one load-switching instant; one integration step that must be rejected.'],
        steps=['Run each combination once and compare the last-orbit temperatures.',
               'Check that at eclipse entry and exit and at load switching the integration is split at the boundary and is '
               'not averaged across it.',
               'Check that the output samples the accepted solution at the required times, independently of the internal '
               'integration step.',
               'Check that a rejected integration step writes no component temperatures.'],
        expect=['Results converge as the tolerances are tightened, and RK45 and Radau agree.',
                'Boundary handling and output sampling conform to Chapter 8.'],
        accept='After the tolerances are tightened by a factor of 100, the change in the last-orbit temperatures shall not '
               'exceed 0.01 K. The difference between RK45 and Radau shall not exceed 0.01 K. The error in eclipse entry and '
               'exit times shall not exceed 1 s. Output sampling shall not change with the internal step.',
        focus='Tolerance convergence, method agreement, eclipse and load-switching boundaries, output sampling'),
    'NI-002': dict(
        func='Joint operation and result archive', name='End-to-End Operation and Result Archive', req='TH-01, TH-02',
        basis='Section 3.3; Section 6.3; Chapter 7; Section 9.4',
        intro='This project verifies the joint operation of the SDTwin thermal module with Orbit and Power, following the '
              'workflow in Chapter 7 of the design report.',
        goal='Verify the synchronized inputs, constraint-event handling, temperature ports, single ownership of component '
             'temperatures, and result archiving.',
        pre=['The Orbit and Power modules are available, and the asset revisions, initial values, and environmental data are '
             'frozen.'],
        input=['A 24 h scenario containing eclipses, load switching, and battery constraint events.',
               'One trial in which Power returns valid false and one trial in which Power returns event_required true.'],
        steps=['Run the scenario in the calling order of Section 6.3 and save all outputs.',
               'Check that an invalid Power result is reported as an error and stops that evaluation, and that when '
               'event_required is true the calculation first returns to the constraint boundary, updates the discrete load '
               'state according to the declared rule, and then recalculates the powers and temperature derivatives.',
               'Check that temperatures are saved only after an integration step is accepted, that the computing domain '
               'reads the temperature of $J$, and that Power reads the temperature of $B$ for its next trial.',
               'Check that, with the thermal module enabled, power_considering_thermal of Orbit no longer updates the same '
               'solar array temperature, and check that the thermal module adds no power-off or throttling rules.',
               'Repeat the run with identical inputs, compare the two results, check the archive fields, and record the '
               'number of Power root evaluations and rejected trials.'],
        expect=['Events and invalid results are handled according to Chapter 7.',
                'Each component temperature has only one update source.',
                'The two runs give identical results, and the archive is complete.'],
        accept='The two runs shall be bitwise identical, or their difference shall not exceed 1×10^{−12}. The archive shall '
               'contain '
               'run_id, the UTC epoch, time_s, component identifiers and state order, temperatures, the four Power ports, '
               'heat flows, solver settings, and parameter revisions. All checks of steps 2 to 4 shall pass.',
        focus='Event handling, temperature ports, single temperature source, archive and reproducibility'),
    'NI-003': dict(
        func='SimReady assets and scene configuration', name='Asset and Scene Assembly', req='TH-04',
        basis='Section 9.3, Table 9; Section 9.4',
        intro='This project verifies the function of the SDTwin thermal module that assembles the thermal model from SimReady '
              'assets and scene configuration.',
        goal='Verify the Table 9 records, instance assignments, geometry units, overrides, the shared temperature node, '
             'independent instances, and single counting of mass.',
        pre=['The assets of the seven instances under Sat01 have asset_id, asset_version, geometry_uri, domain, model_id, '
             'parameter_set, ports, and provenance registered.'],
        input=['SolarArray01, Battery01, Controller01, PDU01, Compute01, ColdPlate01, and Radiator01, with geometry paths '
               'under /World/Sat01 named by instance identifier.',
               'One display-scaled asset; one set of parameter_overrides; two instances created from the same asset; one '
               'asset with an unregistered model_id.'],
        steps=['Assemble the scene, read the areas, masses, and thermal capacitances, and compare them with hand calculations '
               'from the physical dimensions of the assets.',
               'Check that the display-scaled bounding box is not taken as the physical dimensions.',
               'Check that parameter_overrides take precedence over the asset parameter set, and that the affected thermal '
               'capacitances, areas, and thermal resistances are recalculated after a change of material, geometry, or '
               'installation.',
               'Check that Controller01 and PDU01 share $D$, that the battery thermal connection BR leads to the radiator, '
               'that Power and Thermal use the same component instance identifiers, and that material mass is counted once.',
               'Check that the two instances have independent temperatures and battery states, that the unregistered '
               'model_id is rejected and no arbitrary code is executed from USD, and that the photovoltaic efficiency does '
               'not exceed the absorptivity of the same surface.'],
        expect=['Physical parameters are determined only by physical dimensions, materials, and installation.',
                'Instance assignments and the shared temperature node are correct.'],
        accept='The relative errors of areas and masses shall not exceed 0.1%. All checks of steps 2 to 5 shall pass.',
        focus='Table 9 records, geometry units, overrides, shared node, independent instances'),
}

ABBR_EN = [
    ['Design report', 'SDTwin Thermal Software Module Design Report, issue of 2 October 2026'],
    ['Design basis', 'Design report sections, equations, and functions that a test case verifies'],
    ['Lumped model', 'Lumped thermal RC model of Chapter 4 of the design report, in which one temperature represents each '
                     'component'],
    ['Finite-element model', 'COMSOL finite-element thermal model, comprising the complete International Space Station model '
                             'and the whole-satellite model of a single satellite, which calculates the temperature '
                             'distributions over the surfaces and within the interiors of parts on a mesh'],
    ['ISS', 'International Space Station'],
    ['EATCS', 'External Active Thermal Control System of the ISS, which carries equipment heat to the radiators through '
              'liquid ammonia loops'],
    ['MBSU, DDCU, IEA', 'Main Bus Switching Unit, DC-to-DC Converter Unit, and Integrated Equipment Assembly of the ISS, all '
                        'three mounted on liquid ammonia cold plates'],
    ['GPU', 'Graphics processing unit, used as the computing chip in this project'],
    ['Third orbit', 'Last orbital period of the ISS finite-element calculation; the statistics of FE-001 to FE-003 are taken '
                    'over this orbit'],
    ['Component symbols', '$S$, $J$, $C$, $B$, $D$, and $R$ denote the solar array, computing node, cold plate, battery, '
                          'power equipment, and common radiator respectively, as in the design report'],
    ['sdtwin_sim', 'Directory of test support programs, containing the coupled integration procedure, the Earth albedo and '
                   'infrared calculation, scene assembly, and the test power program'],
    ['Test power program', 'Power functions written according to the Power module design report, which supply the four '
                           'power ports, battery state derivatives, and event decisions for the end-to-end test cases; the '
                           'battery parameters are illustrative test values'],
]

COVERAGE_EN = [
    ['2 Requirements and Design Objectives', 'Scene model assembly and component simulation requirements',
     'PA-001, NI-003, HT-002, FE-001 to FE-004'],
    ['3.1 System architecture', 'Components and heat-transfer connections in Figure 1', 'HT-002, FE-004'],
    ['3.2 Package decomposition', 'Files and exports of the thermal package', 'DM-001'],
    ['3.3 Simulation workflow', 'Calculation sequence and temperature ports in Figure 2', 'NI-002'],
    ['4.1 Overall Heat Balance', 'Equation T1', 'HT-002'],
    ['4.2 Heat Transfer Between Components', 'Equation T2', 'HT-001'],
    ['4.3 Component Temperatures', 'Equation T3 and the battery example', 'HT-002, HT-003, EC-001, FE-001 to FE-004'],
    ['4.4 Environmental Absorption and Surface Radiation', 'Equation T4 and Table 5', 'EN-002, EN-003, FE-001, FE-002'],
    ['4.5 Thermal Capacitance and Resistance', 'Equation T5 and the example', 'PA-001, FE-002, FE-003, FE-004'],
    ['5.1 Common data models', 'Four data objects in Table 6', 'DM-001'],
    ['5.2 Thermal parameter assembly', 'assemble_thermal_parameters', 'PA-001'],
    ['5.3 Surface environment preparation', 'prepare_surface_environment and earth_flux', 'EN-001, EN-003'],
    ['5.4 Surface absorption and emission', 'calculate_surface_heat', 'EN-002'],
    ['5.5 Component heat-transfer calculation', 'calculate_heat_flows', 'HT-001'],
    ['5.6 Temperature derivative calculation', 'thermal_derivative and the Power coupling', 'HT-002, EC-001'],
    ['6.1 General contracts', 'Time, array order, power and temperature fields, Orbit outputs', 'DM-001, EN-001, EC-001'],
    ['6.2 Primary calling interfaces', 'Five calls in Table 7', 'PA-001, EN-001, EN-002, HT-001, HT-002'],
    ['6.3 Minimal end-to-end call', 'Calling order and integration-step acceptance', 'NI-002'],
    ['7 End-to-End Operational Workflow', 'Joint trials, constraint events, and temperature ports', 'NI-002'],
    ['8 Numerical Design and Performance', 'Numerical methods and controls in Table 8', 'HT-003, NI-001'],
    ['9.1 Runtime; 9.2 Installation and interpreter configuration', 'Interpreter, dependency, and source revisions',
     'Test conditions in Chapter 5'],
    ['9.3 SimReady assets and scene assembly', 'Records and instances in Table 9', 'NI-003'],
    ['9.4 Parameter configuration and result archive', 'Provenance, initial values, simplifications, and archive',
     'PA-001, EN-003, FE-001, NI-002'],
    ['10 Limitations and Planned Evolution', 'Lumped temperatures, radiation between components, equivalent resistances',
     'FE-002 to FE-004 record the magnitude of the limitations'],
    ['11 Requirements Traceability Matrix', 'TH-01 to TH-04', 'All test cases in Table 1'],
    ['Appendix A Public API Inventory', 'Proposed public names', 'DM-001'],
    ['Appendix B Model-Selection Guidance', 'Finite-element identification of equivalent parameters, and local hot spots',
     'FE-003, FE-004'],
]

# item, reference, existing data; the status column is computed from the executed cases listed last
COMPARE_EN = [
    ['Fields, dimensions, and order of the data objects', 'Table 6 of the design report', 'None', ['DM-001']],
    ['Thermal capacitances and resistances', 'Hand calculation',
     'Example in Section 4.5 of the design report; ISS model parameter table', ['PA-001']],
    ['Incidence cosine and eclipse', 'Independent vector calculation; Orbit output', 'None', ['EN-001']],
    ['Absorbed and emitted powers', 'Hand calculation', 'Example in Section 4.4 of the design report', ['EN-002']],
    ['Earth albedo and infrared irradiance', 'Analytical view factor; numerical integration; finite-element orbital heat loads',
     'Solved ISS finite-element model', ['EN-003']],
    ['Connection heat flows and temperature derivatives', 'Hand calculation; overall heat balance T1',
     'Battery example in Section 4.3 of the design report', ['HT-001', 'HT-002']],
    ['Temperature integration', 'Analytical solutions', 'None', ['HT-003']],
    ['Electrical/thermal coupling', 'Constructed examples; test power program', 'None', ['EC-001']],
    ['Solar array temperature', 'ISS finite-element results for the US solar array wings',
     'Third-orbit results of three cases', ['FE-001']],
    ['Radiator temperature', 'ISS finite-element results for the EATCS radiators',
     'Third-orbit results of two loops in three cases', ['FE-002']],
    ['Computing node temperature', 'ISS finite-element results for MBSU, DDCU, and IEA',
     'Third-orbit results of the mean environment case', ['FE-003']],
    ['Chain from the computing node to the radiator', 'Whole-satellite finite-element results',
     'Five-orbit results of two examples', ['FE-004']],
    ['Numerical settings', 'Own results with tightened tolerances; analytical solutions', 'None', ['NI-001']],
    ['End-to-end workflow and archive', 'Workflow in Chapter 7 of the design report; repeated runs', 'None', ['NI-002']],
    ['Asset and scene assembly', 'Physical dimensions of the assets; Table 9 of the design report', 'None', ['NI-003']],
]

CONDITIONS_EN = [
    'Record the thermal module source revision, the Python and dependency revisions, the operating system, and the '
    'processor, consistent with the runtime environment in Section 9.1 of the design report.',
    'Record the UTC epoch, frames, and component state order; inside the module, temperatures are in K, time in s, and '
    'powers and heat transfer in W.',
    'According to Section 9.4 of the design report, save the resolved parameters, provenance, initial values, and '
    'environmental configuration before startup; for cases with environmental terms disabled, record the simplification.',
    'Freeze the asset revisions, parameter sets, environmental cases, and finite-element reference files, and record their '
    'hashes.',
    'Run reference calculations independently; the design report examples, hand-calculation tables, analytical solutions, '
    'and finite-element results do not use thermal module code.',
    'For ISS temperature acceptance, take the third orbit, compute time-weighted statistics over the exact orbital '
    'period, and compare the mean temperatures of the same part. The planet-refinement experiment separately compares '
    'thermal loads at common sampling instants.',
]

DATA_EN = [
    ['SDTwin Thermal Software Module Design Report', 'Basis', 'DOCX', 'Thermal/SDTwin_Thermal_Design_Report_EN.docx'],
    ['SDTwin Power Software Module Design Report', 'Basis', 'DOCX', 'Power/SDTwin_Power_Design_Report_EN.docx'],
    ['Thermal module and test support programs', 'Item under test', 'Python',
     'Thermal/thermal and Thermal/sdtwin_sim; interface conventions in Thermal/IMPLEMENTATION.md'],
    ['Test programs, hand-calculation tables, and test case data', 'Program and reference', 'Python, JSON, USD',
     'Test programs and the data directory under Thermal/tests'],
    ['ISS model parameters', 'Input', 'Python', 'Thermal/iss_fem/model/iss_spec.py'],
    ['Finite-element time histories of the three cases', 'Reference', 'CSV',
     'series.csv in each case directory under Thermal/iss_fem/out'],
    ['Finite-element part statistics and loop heat breakdown', 'Reference', 'CSV',
     'items.csv and loop_breakdown.csv in the same directories'],
    ['Solved finite-element model and exported heat loads', 'Reference', 'MPH, JSON',
     'Thermal/iss_fem/out/comsol; exported results in Thermal/tests/data/en_003'],
    ['Whole-satellite finite-element results', 'Reference', 'CSV, JSON',
     'space-compute-demo/tools/comsol_benchmark/full_twin/out'],
    ['Execution evidence', 'Evidence', 'JSON, TXT',
     'Case results, time histories, pytest_verified_run.txt, pytest_en003_final.txt and verification_manifest.json under Thermal/tests/results'],
]
