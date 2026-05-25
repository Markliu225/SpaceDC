"""Generate usd/interior.usda — a satellite-interior corridor that mirrors
the user's reference image: bright white shell, racks on BOTH sides of a
central aisle, AIR WALL of circular fans + DCP coolant unit at the +Y end,
camera looking down the aisle from the -Y entrance.

All visible *equipment* (racks, servers, switches, PDUs, patch panels,
CDU, cable trays) are referenced from the NVIDIA Datacenter_NVD asset
pack under
  assets_usd/DigitalTwin/Assets/Datacenter/
The corridor shell (floor / walls / ceiling) and the procedural AIR WALL
fan grid are built as cubes/cylinders because they are not components in
the NVIDIA pack.
"""
from pathlib import Path


OUT = Path("C:/Workspace/SpaceDC/space-compute-demo/usd/interior.usda")
A = "../assets_usd/DigitalTwin/Assets/Datacenter"

REF_RACK    = f"@{A}/Racks/Rack_42U_A/Rack_42U_A_01.usd@"
REF_DGX     = f"@{A}/Server_Nodes/DGX/DGX_A100_01.usd@"
REF_SRV1U   = f"@{A}/Server_Nodes/Servers/Server_1U_A_01.usd@"
REF_SRV2U_B = f"@{A}/Server_Nodes/Servers/Server_2U_B_01.usd@"
REF_SRV2U_C = f"@{A}/Server_Nodes/Servers/Server_2U_C_01.usd@"
REF_DCP     = f"@{A}/Liquid_Cooling/Data_Hall/DCP_A/DCP_A_01.usd@"
REF_PDU     = f"@{A}/Power_Distribution/Controllers/PDU_A/rPDU_A_01.usd@"
REF_SW_QM   = f"@{A}/Network_Switches/NVIDIA/QM8700/QM8700_F_01.usd@"
REF_SW_SN   = f"@{A}/Network_Switches/NVIDIA/SN4600/SN4600C-CS2FC_01.usd@"
REF_PATCH   = f"@{A}/Racks/Patch_Panels/Fiber_A/Fiber_Patch_Panel_1U_A_01.usd@"
REF_TRAY    = f"@{A}/Facilities/Cable_Tray/Cable_Tray_61x299x5cm_A01_01.usd@"

# Rack dimensions (cm): door at x≈0 facing +X, depth=143 (extending into -X),
# width=60 (Y), height=316 (Z). Body extends from rack_origin x to x-143.

# Layout: 6 racks per side, spaced 65cm along Y. Aisle width 220cm.
RACK_Y_POSITIONS = [-340, -270, -200, -130]   # 4 racks per side
LEFT_RACK_X  = -110   # left racks: door at x=-110 facing +X (toward aisle)
RIGHT_RACK_X =  110   # right racks: door at x=+110 facing -X (toward aisle)

# Stacking layout for one populated rack — list of (asset_ref, height_in_U).
# Slots are read from the BOTTOM up (z=0) using slot_z accumulator.
# 1U = 4.45 cm in real life. This rack asset is 316cm tall though; we'll
# use 5cm as the U pitch to fill the rack visibly.
U_CM = 5.0

# Each rack gets a similar stack: PDU + DGXs + servers + network switch.
# Patch_Panel and QM8700_F are skipped because their assets have missing
# sublayers (metricsAssembler) that emit warnings on load.
def rack_layout():
    """Return list of (ref, name_prefix, height_units)."""
    return [
        (REF_PDU,     'PDU',      2),
        (REF_DGX,     'DGX_a',    6),
        (REF_SRV1U,   'Srv1U_a',  1),
        (REF_DGX,     'DGX_b',    6),
        (REF_SRV2U_B, 'Srv2UB',   2),
        (REF_DGX,     'DGX_c',    6),
        (REF_SRV1U,   'Srv1U_b',  1),
        (REF_SW_SN,   'SwSN',     2),
    ]


def main() -> None:
    L: list[str] = []
    P = L.append

    P('#usda 1.0')
    P('(')
    P('    defaultPrim = "World"')
    P('    upAxis = "Z"')
    P('    metersPerUnit = 0.01')
    P('    doc = "Inside the satellite -- corridor with NVIDIA Datacenter racks/servers/switches/CDU on both sides of a central aisle. Equipment refs come from the Datacenter_NVD asset pack; only the corridor shell + AIR WALL fan grid are procedural."')
    P('    customLayerData = { dictionary cameraSettings = { string boundCamera = "/World/Cameras/Aisle" } }')
    P(')')
    P('')

    P('def Xform "World"')
    P('{')

    # -----  Materials for procedural shell + AIR WALL  -----
    P('    def Scope "Looks"')
    P('    {')
    mats = [
        ('PanelWhite', (0.92, 0.93, 0.95), 0.10, 0.35),
        ('FloorTile',  (0.82, 0.83, 0.86), 0.10, 0.40),
        ('FanRing',    (0.55, 0.57, 0.60), 0.65, 0.35),
        ('FanBlade',   (0.18, 0.20, 0.24), 0.30, 0.55),
        ('FanHub',     (0.45, 0.47, 0.52), 0.75, 0.30),
        ('Conduit',    (0.18, 0.42, 0.85), 0.10, 0.45),
    ]
    for name, c, m, r in mats:
        P(f'        def Material "{name}"')
        P('        {')
        P(f'            token outputs:surface.connect = </World/Looks/{name}/Shader.outputs:surface>')
        P('            def Shader "Shader"')
        P('            {')
        P('                uniform token info:id = "UsdPreviewSurface"')
        P(f'                color3f inputs:diffuseColor = ({c[0]}, {c[1]}, {c[2]})')
        P(f'                float inputs:metallic = {m}')
        P(f'                float inputs:roughness = {r}')
        P('                token outputs:surface')
        P('            }')
        P('        }')
    # Emissive light-fixture lens for ceiling strips
    P('        def Material "EmitWhite"')
    P('        {')
    P('            token outputs:surface.connect = </World/Looks/EmitWhite/Shader.outputs:surface>')
    P('            def Shader "Shader"')
    P('            {')
    P('                uniform token info:id = "UsdPreviewSurface"')
    P('                color3f inputs:diffuseColor = (1.0, 0.97, 0.94)')
    P('                color3f inputs:emissiveColor = (1.0, 0.97, 0.94)')
    P('                float inputs:metallic = 0.0')
    P('                float inputs:roughness = 0.6')
    P('                token outputs:surface')
    P('            }')
    P('        }')
    P('    }')
    P('')

    def cube(name, mat, t, s, indent=8):
        pad = ' ' * indent
        P(f'{pad}def Cube "{name}" ( prepend apiSchemas = ["MaterialBindingAPI"] )')
        P(f'{pad}{{')
        P(f'{pad}    double size = 1.0')
        P(f'{pad}    rel material:binding = </World/Looks/{mat}>')
        P(f'{pad}    double3 xformOp:translate = ({t[0]}, {t[1]}, {t[2]})')
        P(f'{pad}    double3 xformOp:scale = ({s[0]}, {s[1]}, {s[2]})')
        P(f'{pad}    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]')
        P(f'{pad}}}')

    def cylinder(name, mat, t, radius, height, axis='Z', rotZ=0.0, indent=8):
        pad = ' ' * indent
        P(f'{pad}def Cylinder "{name}" ( prepend apiSchemas = ["MaterialBindingAPI"] )')
        P(f'{pad}{{')
        P(f'{pad}    double radius = {radius}')
        P(f'{pad}    double height = {height}')
        P(f'{pad}    uniform token axis = "{axis}"')
        P(f'{pad}    rel material:binding = </World/Looks/{mat}>')
        P(f'{pad}    double3 xformOp:translate = ({t[0]}, {t[1]}, {t[2]})')
        P(f'{pad}    float3 xformOp:rotateXYZ = (0, 0, {rotZ})')
        P(f'{pad}    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]')
        P(f'{pad}}}')

    # -----  Corridor shell  -----
    # Aisle is at x ∈ [-110, +110]. Walls go just outside the rack outer face.
    # Rack body extends from x=-110 to x=-253 (left side), so left wall at x=-260.
    # Mirror for right wall at x=+260.
    # Y span: racks from y=-360 to y=-35, plus DCP at y≈+30. Use y∈[-420, +130].
    # Z span: 0 to 320 (just above rack tops).
    P('    def Xform "Shell"')
    P('    {')
    cube('Floor',      'FloorTile',  (0,    -145,   -2), (560, 580,   4))
    cube('Ceiling',    'PanelWhite', (0,    -145,  322), (560, 580,   4))
    cube('WallLeft',   'PanelWhite', (-262, -145,  160), (4,   580, 320))
    cube('WallRight',  'PanelWhite', ( 262, -145,  160), (4,   580, 320))
    P('    }')
    P('')

    # -----  Two rows of NVIDIA racks, each populated with NVIDIA hardware  -----
    # Door faces +X by default. For LEFT row (rack origin at x=LEFT_RACK_X with
    # body extending in -X), no rotation needed. For RIGHT row, rotate 180° Z
    # so door faces -X (toward the aisle).
    layout = rack_layout()

    def write_rack(side, sx, y, idx):
        rot_z = 0 if side == 'L' else 180
        rack_name = f'Rack_{side}{idx}'
        P(f'        def "{rack_name}" (')
        P(f'            prepend references = {REF_RACK}')
        P('        )')
        P('        {')
        P(f'            double3 xformOp:translate = ({sx}, {y}, 0)')
        P(f'            float3 xformOp:rotateXYZ = (0, 0, {rot_z})')
        P('            uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]')
        P('        }')
        # Populate the rack with equipment. Each component asset has its
        # door-face at x=0 facing +X with depth extending in -X. To slot it
        # into the rack at the correct front-flush position, place the
        # equipment with the SAME translation and rotation as the rack
        # itself. Then offset along Z for the slot, and slightly inset along
        # X so the front sits flush with the rack door (door at x≈sx).
        slot_z = 8.0   # start a bit above the floor (above the rack's bottom rails)
        for ref, name_prefix, hu in layout:
            # Inset 5cm into the rack so equipment door is just behind the rack door.
            # For left side (rot_z=0), inset is in +X direction (sx + 5 wrong: rack
            # door is at sx and body extends in -X, so equipment with depth in -X
            # naturally slots in. We want equipment door slightly inside rack door:
            # equipment_origin_x = sx - 5 (inset of 5 in -X).
            # For right side (rot_z=180), the equipment will be flipped, so we
            # apply the same -5 inset in the LOCAL frame which becomes +5 in world.
            # Easiest: apply translation ALONG with the rack rotation by also
            # rotating 180° and putting eq at sx_eq = sx + sign*5 where sign is +1
            # for L (inset moves equipment INTO the rack along -X), -1 for R.
            sign = -1 if side == 'L' else +1
            ex = sx + sign * 5
            eq_name = f'{name_prefix}_{side}{idx}'
            P(f'            def "{eq_name}" (')
            P(f'                prepend references = {ref}')
            P('            )')
            P('            {')
            P(f'                double3 xformOp:translate = ({ex}, {y}, {slot_z})')
            P(f'                float3 xformOp:rotateXYZ = (0, 0, {rot_z})')
            P('                uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]')
            P('            }')
            slot_z += hu * U_CM

    P('    def Xform "Racks"')
    P('    {')
    for i, y in enumerate(RACK_Y_POSITIONS, start=1):
        write_rack('L', LEFT_RACK_X,  y, i)
    for i, y in enumerate(RACK_Y_POSITIONS, start=1):
        write_rack('R', RIGHT_RACK_X, y, i)
    P('    }')
    P('')

    # -----  DCP coolant distribution unit at the +Y end  -----
    # DCP_A_01 size: 114×99×345. Door at x=0 facing +X. Place at the back-right
    # of the corridor so the camera at the -Y end sees it past the row of racks.
    P('    def "DCP" (')
    P(f'        prepend references = {REF_DCP}')
    P('    )')
    P('    {')
    P('        double3 xformOp:translate = (130, 70, 0)')
    P('        float3 xformOp:rotateXYZ = (0, 0, 180)')
    P('        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]')
    P('    }')
    P('')

    # -----  AIR WALL at the +Y end (back-left), opposite the DCP  -----
    # 4×4 grid of fan rings sunk into a backplate. Built procedurally as
    # cylinders + cubes (NVIDIA pack has no fan-wall component).
    P('    def Xform "AirWall"')
    P('    {')
    cube('Backplate', 'PanelWhite', (-130, 105, 160), (220, 8, 320), indent=8)
    # 4 cols × 4 rows of fans
    fan_xs = [-200, -160, -120, -80]   # 4 columns, 40cm apart
    fan_zs = [55, 130, 205, 275]       # 4 rows
    for r, z in enumerate(fan_zs):
        for c, x in enumerate(fan_xs):
            # Outer ring (cylinder along Y axis since wall faces -Y)
            cylinder(f'Ring_{r}{c}',  'FanRing',  (x, 100, z), 18, 6, axis='Y', indent=8)
            cylinder(f'Blade_{r}{c}', 'FanBlade', (x,  98, z), 16, 3, axis='Y', indent=8)
            cylinder(f'Hub_{r}{c}',   'FanHub',   (x,  96, z),  4, 4, axis='Y', indent=8)
    P('    }')
    P('')

    # -----  Overhead cable trays (NVIDIA Cable_Tray refs)  -----
    # The Cable_Tray asset has bbox (299, 61, 5) anchored at origin. Place two
    # parallel runs along the corridor length above the racks.
    P('    def Xform "CableTrays"')
    P('    {')
    # Tray asset is 299cm long along its X axis (the long dimension). To run
    # them along the corridor's Y axis we rotate +90° around Z. Place two runs.
    for k, x in enumerate([-160, 160], start=1):
        for j, y_start in enumerate([-410, -110], start=1):
            P(f'        def "Tray_{k}_{j}" (')
            P(f'            prepend references = {REF_TRAY}')
            P('        )')
            P('        {')
            # After +90° Z rotation, the asset's local +X (its long axis) points
            # to world +Y. The asset's bbox starts at origin, so after rotation
            # +X(0..299) maps to +Y(0..299). y_start translates.
            P(f'            double3 xformOp:translate = ({x}, {y_start}, 305)')
            P('            float3 xformOp:rotateXYZ = (0, 0, 90)')
            P('            uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]')
            P('        }')
    P('    }')
    P('')

    # -----  Lighting  -----
    P('    def Xform "Lighting"')
    P('    {')
    # 7 ceiling RectLight strip fixtures down the center of the aisle, with
    # visible emissive lens cubes right beneath each so auto-exposure locks
    # to a known bright reference.
    for i, y in enumerate([-380, -310, -240, -170, -100, -30, 50], start=1):
        P(f'        def RectLight "Panel_{i}"')
        P('        {')
        P('            float inputs:width = 100')
        P('            float inputs:height = 70')
        P('            float inputs:intensity = 90000')
        P('            color3f inputs:color = (1.0, 0.97, 0.94)')
        P('            bool primvars:doNotCastShadows = 1')
        P('            token visibility = "invisible"')
        P(f'            double3 xformOp:translate = (0, {y}, 318)')
        P('            uniform token[] xformOpOrder = ["xformOp:translate"]')
        P('        }')
        cube(f'Lens_{i}', 'EmitWhite', (0, y, 320), (110, 80, 4), indent=8)
    # Bright SphereLights down the centerline above the racks for direct kick.
    for i, y in enumerate([-360, -260, -160, -60, 30], start=1):
        P(f'        def SphereLight "Strip_{i}"')
        P('        {')
        P('            float inputs:radius = 8.0')
        P('            float inputs:intensity = 1800000')
        P('            color3f inputs:color = (1.0, 0.97, 0.94)')
        P('            bool inputs:treatAsPoint = 1')
        P('            bool primvars:doNotCastShadows = 1')
        P('            token visibility = "invisible"')
        P(f'            double3 xformOp:translate = (0, {y}, 290)')
        P('            uniform token[] xformOpOrder = ["xformOp:translate"]')
        P('        }')
    # Per-rack fill SphereLights aimed INTO each cabinet so the rack
    # contents (DGX/servers/switches) are clearly visible.
    for side, fx in [('L', -50), ('R', 50)]:
        for i, y in enumerate(RACK_Y_POSITIONS, start=1):
            for j, z in enumerate([60, 160, 260], start=1):
                P(f'        def SphereLight "Fill_{side}{i}_{j}"')
                P('        {')
                P('            float inputs:radius = 4.0')
                P('            float inputs:intensity = 600000')
                P('            color3f inputs:color = (0.95, 0.97, 1.0)')
                P('            bool inputs:treatAsPoint = 1')
                P('            bool primvars:doNotCastShadows = 1')
                P('            token visibility = "invisible"')
                P(f'            double3 xformOp:translate = ({fx}, {y}, {z})')
                P('            uniform token[] xformOpOrder = ["xformOp:translate"]')
                P('        }')
    # Ambient dome
    P('        def DomeLight "Ambient"')
    P('        {')
    P('            color3f inputs:color = (0.92, 0.95, 1.0)')
    P('            float inputs:intensity = 1500')
    P('            token inputs:texture:format = "latlong"')
    P('        }')
    P('    }')
    P('')

    # -----  Camera at -Y entrance looking +Y down the aisle  -----
    P('    def Xform "Cameras"')
    P('    {')
    P('        def Camera "Aisle"')
    P('        {')
    P('            float focalLength = 16')
    P('            float focusDistance = 500')
    P('            float2 clippingRange = (1, 4000)')
    P('            double3 xformOp:translate = (0, -410, 165)')
    P('            float3 xformOp:rotateXYZ = (90, 0, 0)')
    P('            uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]')
    P('        }')
    P('    }')
    P('}')
    P('')

    OUT.write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {OUT} ({len(L)} lines)")


if __name__ == "__main__":
    main()
