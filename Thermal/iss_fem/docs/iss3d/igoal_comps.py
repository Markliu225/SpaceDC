import sys; sys.path.insert(0,'.')
import numpy as np, DracoPy
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from extract_bbox import load_glb, node_local
js, bin_ = load_glb('ISS_D_IGOAL.glb')
nodes = js['nodes']
parent = {}
for i,n in enumerate(nodes):
    for c in n.get('children',[]): parent[c]=i
def world(i):
    M = np.eye(4); chain=[]; j=i
    while j is not None:
        chain.append(j); j=parent.get(j)
    for j in reversed(chain):
        n=nodes[j]
        M = M @ (np.eye(4) if n.get('name','').startswith('SSREF') else node_local(n))
    return M
def mesh_world(name):
    i = next(k for k,n in enumerate(nodes) if n.get('name')==name)
    W = world(i)
    allP=[]; allF=[]; off=0
    for prim in js['meshes'][nodes[i]['mesh']]['primitives']:
        ext = prim['extensions']['KHR_draco_mesh_compression']
        bv = js['bufferViews'][ext['bufferView']]; o=bv.get('byteOffset',0)
        dm = DracoPy.decode(bin_[o:o+bv['byteLength']])
        P = np.asarray(dm.points,float).reshape(-1,3); F=np.asarray(dm.faces).reshape(-1,3)
        allP.append(P); allF.append(F+off); off+=len(P)
    P=np.vstack(allP); F=np.vstack(allF)
    return P@W[:3,:3].T + W[:3,3], F
def comps(name, tol=0.5):
    Pw, F = mesh_world(name)
    key = np.round(Pw/tol)
    _, inv = np.unique(key, axis=0, return_inverse=True); inv=inv.ravel()
    Fm = inv[F]; n = inv.max()+1
    e = np.vstack([Fm[:,[0,1]],Fm[:,[1,2]]])
    A = coo_matrix((np.ones(len(e)),(e[:,0],e[:,1])),shape=(n,n))
    nc, lab = connected_components(A, directed=False)
    Pu = np.zeros((n,3)); Pu[inv]=Pw
    out=[]
    for c in range(nc):
        Q=Pu[lab==c]; out.append((Q.min(0),Q.max(0),len(Q)))
    return out
if __name__=='__main__':
    for nm in sys.argv[1:]:
        out = comps(nm)
        out.sort(key=lambda t: -np.sort(t[1]-t[0])[-1]*np.sort(t[1]-t[0])[-2])
        print(f'=== {nm}: {len(out)} components (sorted by largest face area)')
        for mn,mx,k in out[:40]:
            s=mx-mn
            print(f'   min=({mn[0]:8.1f},{mn[1]:8.1f},{mn[2]:8.1f}) max=({mx[0]:8.1f},{mx[1]:8.1f},{mx[2]:8.1f}) size=({s[0]:7.1f},{s[1]:7.1f},{s[2]:7.1f}) n={k}')
