# one-off patch: split the loop DAE into three Global Equations features by physical kind (separate
# solver fields -> separate scales) and add manual solver scaling for T, T2 and the loop fields
p = 'iss_layout.py'
s = open(p, encoding='utf-8').read()
s = s.replace("""        qrows.append((f'Qc_{L}', f'Qc_{L}-({expr})', '20[kW]' if not L.startswith('PV') else '6[kW]', f'{L}: heat collected by the loop (cold plates, IFHX)'))""",
              """        qrows.append((f'Qc_{L}', f'Qc_{L}-({expr})', '20[kW]' if not L.startswith('PV') else '6[kW]', f'{L}: heat collected by the loop (cold plates, IFHX)', 'Q'))""")
s = s.replace("""                rows.append((tf, eq, d.get('Tf_init', f'{Tset}-10[K]'), f'{L} ORU {oru} panel {i} NH3 outlet T'))""",
              """                rows.append((tf, eq, d.get('Tf_init', f'{Tset}-10[K]'), f'{L} ORU {oru} panel {i} NH3 outlet T', 'T'))""")
s = s.replace("""        rows.insert(0, (f'f_{L}', f"f_{L}*(Tret_{L}-Tout_{L})-(Tret_{L}-{Tset})", str(d.get('f_init', 0.3)), f'{L}: radiator flow fraction (bypass mixing to set point)'))""",
              """        rows.insert(0, (f'f_{L}', f"f_{L}*(Tret_{L}-Tout_{L})-(Tret_{L}-{Tset})", str(d.get('f_init', 0.3)), f'{L}: radiator flow fraction (bypass mixing to set point)', 'f'))""")
open(p, 'w', encoding='utf-8').write(s)

p = 'iss_build.py'
s = open(p, encoding='utf-8').read()
old = s[s.index("        ge = comp.physics().create('ge', 'GlobalEquations'); ge.label('Cooling loops (EATCS A/B, PVTCS)')"):s.index("        log('global equations:', len(lay['ge_rows']), 'unknowns')")]
new = """        ge = comp.physics().create('ge', 'GlobalEquations'); ge.label('Cooling loops (EATCS A/B, PVTCS)')
        # one Global Equations feature per physical kind: each becomes its own solver field with its own scale
        kinds = {'Q': ('power', 'power', 'collected heat Qc (W)'), 'T': ('temperature', 'power', 'NH3 panel outlet temperatures (K)'),
                 'f': ('dimensionless', 'temperature', 'radiator flow fractions')}
        self.ge_fields = {}
        for ki, (kind, (dq, sq, lbl)) in enumerate(kinds.items()):
            rows = [r for r in lay['ge_rows'] if r[4] == kind]
            g1 = ge.feature('ge1') if ki == 0 else ge.create(f'ge{ki + 1}', 'GlobalEquations', -1)
            g1.label(lbl)
            for i, (name, eq, init, descr, _k) in enumerate(rows):
                g1.setIndex('name', name, i); g1.setIndex('equation', eq, i); g1.setIndex('initialValueU', init, i); g1.setIndex('initialValueUt', '0', i)
                g1.setIndex('description', descr, i)
            tryset(g1, 'DependentVariableQuantity', dq, 'ge'); tryset(g1, 'SourceTermQuantity', sq, 'ge')
            self.ge_fields[kind] = str(g1.tag())
"""
s = s.replace(old, new)
# solver sequences with manual scaling, created after the studies
s = s.replace("""    def save(self, path):""", """    def solver_scaling(self):
        \"\"\"Generate the solver sequences and set manual scales: temperatures 300 K, loop heat 2e4 W,
        loop temperatures 300 K, flow fractions 1 (automatic scaling mixed them into one 2e4 scale).\"\"\"
        j = self.j
        scale = {'comp1_T': '300', 'comp1_T2': '300'}
        for st in ('stdL', 'stdF', 'stdO'):
            try:
                j.study(st).createAutoSequences('all')
            except Exception as e:
                log('createAutoSequences', st, str(e)[:150]); continue
        for sol in j.sol():
            for f in sol.feature():
                if str(f.getType()) != 'Variables': continue
                for c in f.feature():
                    tag = str(c.tag())
                    val = None
                    if tag in scale: val = scale[tag]
                    elif tag.startswith('comp1_ODE'):
                        val = None
                    if tag.startswith('comp1_ODE'):
                        # field order follows the ge features: ge1 = Q, ge2 = T, ge3 = f
                        try: descr = str(c.getString('fieldname')) if 'fieldname' in [str(x) for x in c.properties()] else ''
                        except Exception: descr = ''
                        idx = int(tag.replace('comp1_ODE', '') or '1')
                        val = {1: '2e4', 2: '300', 3: '1'}.get(idx)
                    if val:
                        try:
                            c.set('scalemethod', 'manual'); c.set('scaleval', val)
                        except Exception as e:
                            log('scale', tag, str(e)[:120])
                log('scaling', str(sol.tag()), str(f.tag()), [(str(c.tag()), str(c.getString('scalemethod'))) for c in f.feature()][:12])

    def save(self, path):""")
s = s.replace("b.geometry(); b.selections(); b.materials(); b.physics(); b.mesh(); b.studies()",
              "b.geometry(); b.selections(); b.materials(); b.physics(); b.mesh(); b.studies(); b.solver_scaling()")
open(p, 'w', encoding='utf-8').write(s)
print('ok')
