# -*- coding: utf-8 -*-
"""Smoke 8 (not a deliverable): heat pipe as (D1) slender solid block with
high k, (D2) Isothermal Domain block with interface h. Toy model, frozen study
range(0,10,100) at hemicube 32, then the orbital study for the cheapest."""
import mph, time, os
S = r"C:\Users\markl\AppData\Local\Temp\claude\c--Workspace-SpaceDC\d840e3dd-5698-45ad-840c-5338a469d46d\scratchpad"
client = mph.start(cores=4)

def tryset(obj, name, val, label=""):
    try:
        obj.set(name, val); print("set OK", label, name, "=", val, flush=True); return True
    except Exception as e:
        print("set FAIL", label, name, "=", val, "->", str(e).replace("\n", " ")[:300], flush=True); return False

def build(variant):
    model = client.create('smoke8_' + variant); j = model.java
    comp = j.component().create('comp1', True)
    geom = comp.geom().create('geom1', 3); geom.lengthUnit('m')
    b1 = geom.feature().create('blk1', 'Block'); b1.set('size', [0.3, 0.3, 0.3]); b1.set('base', 'center')
    b3 = geom.feature().create('blk3', 'Block'); b3.set('size', [0.1, 0.1, 0.01]); b3.set('base', 'center'); b3.set('pos', [0.0, 0.0, 0.155])
    b2 = geom.feature().create('blk2', 'Block'); b2.set('size', [1.0, 0.02, 2.0]); b2.set('base', 'center'); b2.set('pos', [0.0, 0.0, 1.5])
    pipe = geom.feature().create('pipe', 'Block'); pipe.set('size', [0.025, 0.0254, 2.5]); pipe.set('base', 'corner'); pipe.set('pos', [0.15, 0.01, -0.1])
    csel = geom.selection().create('csel_pipe', 'CumulativeSelection'); pipe.set('contributeto', 'csel_pipe')
    geom.run()
    mat = comp.material().create('mat1', 'Common'); mat.selection().all()
    mat.propertyGroup('def').set('thermalconductivity', ['238']); mat.propertyGroup('def').set('density', '2700'); mat.propertyGroup('def').set('heatcapacity', '900')
    f = j.func().create('int1', 'Interpolation'); f.set('source', 'file'); f.set('filename', os.path.join(S, "smoke_power.csv")); f.set('nargs', '1')
    f.set('interp', 'linear'); f.set('extrap', 'const'); f.set('argunit', 's'); f.set('fununit', 'W'); f.setIndex('funcs', 'Pgpu', 0, 0); f.setIndex('funcs', '1', 0, 1); f.importData()
    for nm, expr in (('rx', '6800e3*cos(2*pi*t/5574)'), ('ry', '6800e3*sin(2*pi*t/5574)*cos(51.6[deg])'), ('rz', '6800e3*sin(2*pi*t/5574)*sin(51.6[deg])')):
        fa = j.func().create(nm, 'Analytic'); fa.set('expr', expr); fa.set('args', ['t']); fa.set('argunit', 's'); fa.set('fununit', 'm')
    comp.variable().create('var_stat').set('tt', 't*1e-3'); comp.variable().create('var_trans').set('tt', 't')
    ht = comp.physics().create('ht', 'HeatTransfer', 'geom1')
    if variant == 'D1':
        mp_ = comp.material().create('mat_pipe', 'Common'); mp_.selection().named('geom1_csel_pipe_dom')
        mp_.propertyGroup('def').set('thermalconductivity', ['1.6e5']); mp_.propertyGroup('def').set('density', '2700'); mp_.propertyGroup('def').set('heatcapacity', '900')
    else:
        try:
            pm = ht.prop('PhysicalModel'); print("ht PhysicalModel props:", list(pm.properties()), flush=True)
            for cand in ('isothermalDomain', 'IsothermalDomain', 'useIsothermalDomain', 'isothermaldomain'):
                if tryset(pm, cand, True, 'ht.PM'): break
        except Exception as e:
            print("PhysicalModel ERR", str(e)[:200], flush=True)
        idom = ht.create('id1', 'IsothermalDomain', 3); idom.selection().named('geom1_csel_pipe_dom')
        print("id1 props:", list(idom.properties()), flush=True)
        idi = ht.create('idi1', 'IsothermalDomainInterface', 2); idi.selection().named('geom1_csel_pipe_bnd')
        print("idi1 props:", list(idi.properties()), flush=True)
        for cand in ('ThermalContact', 'thermalContact', 'Contact', 'ConvectiveHeatFlux', 'Continuity'):
            if tryset(idi, 'InterfaceType', cand, 'idi1'): break
        for cand in ('h', 'hc', 'h_contact', 'h_int'):
            if tryset(idi, cand, '2.07e5', 'idi1'): break
    otl = comp.physics().create('otl', 'OrbitalThermalLoadsEvents', 'geom1')
    rs = otl.prop('RadiationSettings'); rs.set('wavelengthDependenceOfSurfaceProperties', 'SolarAndAmbient'); rs.set('radiationMethod', 'hemicube'); rs.set('radiationResolution', '32')
    op = otl.feature('op1'); op.set('orbitType', 'userDefined'); op.set('orbitDefinition', 'FromFunction')
    for ax in 'XYZ':
        op.set(f'functionType_{ax}_ECS', 'userDefined'); op.set(f'userDefinedFunction_{ax}_ECS', f'r{ax.lower()}(tt)')
    sup = otl.feature('sup1'); sup.set('sunDirection', 'userdef'); sup.set('SV_ECS', ['-1', '0', '0']); sup.set('solarFluxSolAmb', 'userdefBand'); sup.set('q0s_bandSolAmb', ['1361', '0'])
    plp = otl.feature('plp1'); plp.set('planetAlbedoTypeSolAmb', 'userdefBand'); plp.set('planetAlbedoEachBandSolAmb', ['0.3', '0'])
    plp.set('planetRadiativeFluxTypeSolAmb', 'userdefBand'); plp.set('planetRadiativeFluxEachBandSolAmb', ['0', '237'])
    otl.feature('sa1').set('primaryAxis', 'z'); otl.feature('sa1').set('secondaryAxis', 'y')
    otl.feature('so1').set('primaryOrientation', 'nadir'); otl.feature('so1').set('secondaryOrientation', 'velocity')
    d = otl.feature('dsurf1'); d.set('userDefinitionTypeSolAmb', 'userDefinedForEachBand'); d.set('epsilon_radSolAmb_mat', 'userdef'); d.set('epsilon_rad_bandSolAmb', ['0.25', '0.85']); d.set('Tamb', '2.7[K]')
    hs = ht.create('hs1', 'HeatSource', 3); hs.selection().set([2]); hs.set('heatSourceType', 'HeatRate'); hs.set('P0', 'Pgpu(tt)')
    ht.feature('init1').set('Tinit', '300[K]')
    mpx = comp.multiphysics().create('htrad1', 'HeatTransferWithSurfaceToSurfaceRadiation', 2); mpx.set('Heat_physics', 'ht'); mpx.set('Rad_physics', 'otl')
    mesh = comp.mesh().create('mesh1'); mesh.autoMeshSize(7); mesh.run()
    print(variant, "mesh:", mesh.getNumElem('tet'), "tets", flush=True)
    return model, j

def frozen(j, tag, tlist='range(0,10,100)'):
    st = j.study().create(tag)
    for typ, ftag in (('OrbitThermalLoads', 'otl'), ('OrbitalTemperature', 'ot')):
        s = st.create(ftag, typ); s.set('timestepspec', 'timesteps'); s.set('tlist', tlist); s.set('useadvanceddisable', True); s.set('disabledvariables', ['var_trans'])
        if typ == 'OrbitalTemperature': s.set('rtol', '0.005')
    t0 = time.time()
    try:
        st.run(); print(f"{tag} -> {time.time()-t0:.1f}s", flush=True); return True
    except Exception as e:
        print(f"{tag} ERR", str(e).replace("\n", " ")[:500], flush=True); return False

def orbital(j, tag, init_study):
    st = j.study().create(tag)
    for typ, ftag in (('OrbitThermalLoads', 'otl'), ('OrbitalTemperature', 'ot')):
        s = st.create(ftag, typ); s.set('timestepspec', 'timesteps'); s.set('tlist', 'range(0,60,1800)'); s.set('useadvanceddisable', True); s.set('disabledvariables', ['var_stat'])
        if typ == 'OrbitalTemperature':
            s.set('rtol', '0.005'); s.set('initmethod', 'sol'); s.set('initstudy', init_study); s.set('initstudystep', 'ot'); s.set('solnum', 'last')
    t0 = time.time()
    try:
        st.run(); print(f"{tag} orbital 1800s -> {time.time()-t0:.1f}s", flush=True)
    except Exception as e:
        print(f"{tag} ERR", str(e).replace("\n", " ")[:500], flush=True)

for variant in ('D1', 'D2'):
    try:
        model, j = build(variant)
        ok = frozen(j, f'{variant}_frozen')
        if ok:
            orbital(j, f'{variant}_orbital', f'{variant}_frozen')
        model.save(os.path.join(S, f"smoke8_{variant}.mph"))
    except Exception as e:
        print(variant, "BUILD ERR", str(e).replace("\n", " ")[:600], flush=True)
print("done", flush=True)
