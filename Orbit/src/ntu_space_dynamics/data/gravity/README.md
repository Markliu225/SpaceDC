# Bundled Earth gravity data

`EGM2008_120.gfc` is a text-preserving truncation of the official ICGEM
EGM2008 tide-free model. The original model is complete to degree and order
2159 and has additional coefficients through degree 2190/order 2159; this
package distributes degrees 0–120 to keep installation size and orbit
propagation cost bounded.

- Official model page: <https://icgem.gfz.de/tom_longtime>
- Official source archive: <https://icgem.gfz.de/getmodel/zip/c50128797a9cb62e936337c890e4425f03f0461d7329b09a8cc8561504465340/EGM2008.zip>
- Source archive SHA-256: `8cb3521f9650568a80d049bd6dd3668a4191f3ac9d741122cc0321bcc28948e3`
- Packaged subset SHA-256: `6ae505fcd7acfed84c5f69ff3e729be9cbb450162fd6bcf9116584c5b00570f2`
- Normalization: fully normalized
- Tide system: tide-free
- Model GM: `3.986004415e14 m^3/s^2`
- Reference radius: `6378136.3 m`

The subset is generated reproducibly with:

```powershell
python scripts/prepare_gravity_model.py EGM2008.zip `
  src/ntu_space_dynamics/data/gravity/EGM2008_120.gfc --max-degree 120
```

The generated `.sha256` sidecar protects the installed subset. No coefficient
values are rounded or reformatted by the packaging script. The coefficients
remain subject to the original model owner's data terms and are not relicensed
by the Python package's MIT software license; retain this provenance and cite
Pavlis et al. (2012), <https://doi.org/10.1029/2011JB008916>, in derived work.
