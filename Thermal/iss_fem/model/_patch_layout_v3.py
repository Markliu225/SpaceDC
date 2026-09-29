p = 'iss_layout.py'
s = open(p, encoding='utf-8').read()
old = """    for L in P['loops']:
        gv[f'Q_{L}'] = ' + '.join(pick[L]) if pick[L] else '0[W]'
"""
new = """    # the collected heat is a global UNKNOWN Qc_L with the algebraic equation Qc_L = sum(pick-ups):
    # only that one row touches all rack/box DOFs; radiator panels then depend on Qc_L alone
    # (a global VARIABLE would put every rack DOF into every panel row: dense Jacobian block)
    qrows = []
    for L in P['loops']:
        gv[f'Q_{L}'] = f'Qc_{L}'
        expr = ' + '.join(pick[L]) if pick[L] else '0[W]'
        qrows.append((f'Qc_{L}', f'Qc_{L}-({expr})', '20[kW]' if not L.startswith('PV') else '6[kW]', f'{L}: heat collected by the loop (cold plates, IFHX)'))
"""
assert old in s
s = s.replace(old, new)
old2 = """    lay['int_ops_spec'] = ops
    lay['global_vars'] = gv
    lay['ge_rows'] = rows"""
new2 = """    lay['int_ops_spec'] = ops
    lay['global_vars'] = gv
    lay['ge_rows'] = qrows + rows"""
assert old2 in s
s = s.replace(old2, new2)
open(p, 'w', encoding='utf-8').write(s)
print('ok')
