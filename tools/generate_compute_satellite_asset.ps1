$ErrorActionPreference = 'Stop'

$path = 'C:\Workspace\SpaceDC\exts\spacedc.digital_twin\data\models\compute_satellite_custom.usda'
$sb = New-Object System.Text.StringBuilder

function Add([string]$line = '') {
    [void]$script:sb.AppendLine($line)
}

function Num([double]$n) {
    return [string]::Format([System.Globalization.CultureInfo]::InvariantCulture, '{0:0.###}', $n)
}

function Vec($v) {
    return '(' + (Num $v[0]) + ', ' + (Num $v[1]) + ', ' + (Num $v[2]) + ')'
}

function OpList([bool]$hasTranslate, [bool]$hasRotate, [bool]$hasScale) {
    $ops = @()
    if ($hasTranslate) { $ops += '"xformOp:translate"' }
    if ($hasRotate) { $ops += '"xformOp:rotateXYZ"' }
    if ($hasScale) { $ops += '"xformOp:scale"' }
    return '[' + ($ops -join ', ') + ']'
}

function Add-Cube($indent, $name, $mat, $translate, $scale, $rotate = $null) {
    Add ($indent + 'def Cube "' + $name + '"')
    Add ($indent + '{')
    Add "$indent    rel material:binding = </ComputeSatelliteCustom/_Materials/$mat>"
    Add "$indent    double size = 1"
    Add "$indent    double3 xformOp:translate = $(Vec $translate)"
    if ($null -ne $rotate) {
        Add "$indent    double3 xformOp:rotateXYZ = $(Vec $rotate)"
    }
    Add "$indent    double3 xformOp:scale = $(Vec $scale)"
    Add "$indent    uniform token[] xformOpOrder = $(OpList $true ($null -ne $rotate) $true)"
    Add ($indent + '}')
}

function Add-Cylinder($indent, $name, $mat, $translate, [double]$radius, [double]$height, $rotate = $null) {
    Add ($indent + 'def Cylinder "' + $name + '"')
    Add ($indent + '{')
    Add "$indent    rel material:binding = </ComputeSatelliteCustom/_Materials/$mat>"
    Add "$indent    double radius = $(Num $radius)"
    Add "$indent    double height = $(Num $height)"
    Add "$indent    double3 xformOp:translate = $(Vec $translate)"
    if ($null -ne $rotate) {
        Add "$indent    double3 xformOp:rotateXYZ = $(Vec $rotate)"
    }
    Add "$indent    uniform token[] xformOpOrder = $(OpList $true ($null -ne $rotate) $false)"
    Add ($indent + '}')
}

function Add-Sphere($indent, $name, $mat, $translate, [double]$radius) {
    Add ($indent + 'def Sphere "' + $name + '"')
    Add ($indent + '{')
    Add "$indent    rel material:binding = </ComputeSatelliteCustom/_Materials/$mat>"
    Add "$indent    double radius = $(Num $radius)"
    Add "$indent    double3 xformOp:translate = $(Vec $translate)"
    Add "$indent    uniform token[] xformOpOrder = ["xformOp:translate"]"
    Add ($indent + '}')
}

function Add-Instance($indent, $name, $refPath, $translate, $rotate = $null) {
    Add ($indent + 'def Xform "' + $name + '" (')
    Add "$indent    instanceable = true"
    Add "$indent    prepend references = <$refPath>"
    Add ($indent + ')')
    Add ($indent + '{')
    Add "$indent    double3 xformOp:translate = $(Vec $translate)"
    if ($null -ne $rotate) {
        Add "$indent    double3 xformOp:rotateXYZ = $(Vec $rotate)"
    }
    Add "$indent    uniform token[] xformOpOrder = $(OpList $true ($null -ne $rotate) $false)"
    Add ($indent + '}')
}

$bodyHalfX = 68.0
$bodyHalfY = 36.0
$bodyHalfZ = 74.0

Add '#usda 1.0'
Add '('
Add '    defaultPrim = "ComputeSatelliteCustom"'
Add '    metersPerUnit = 0.01'
Add '    upAxis = "Y"'
Add ')'
Add ''
Add 'def Xform "ComputeSatelliteCustom"'
Add '{'

Add '    def Scope "_Materials"'
Add '    {'
Add '        def Material "Kapton"'
Add '        {'
Add '            token outputs:surface.connect = </ComputeSatelliteCustom/_Materials/Kapton/Shader.outputs:surface>'
Add '            def Shader "Shader"'
Add '            {'
Add '                uniform token info:id = "UsdPreviewSurface"'
Add '                color3f inputs:diffuseColor = (0.84, 0.56, 0.16)'
Add '                float inputs:metallic = 0.34'
Add '                float inputs:roughness = 0.19'
Add '                color3f inputs:specularColor = (1.0, 0.95, 0.72)'
Add '                float inputs:clearcoat = 0.56'
Add '                float inputs:clearcoatRoughness = 0.10'
Add '                token outputs:surface'
Add '            }'
Add '        }'
Add ''
Add '        def Material "ShellDark"'
Add '        {'
Add '            token outputs:surface.connect = </ComputeSatelliteCustom/_Materials/ShellDark/Shader.outputs:surface>'
Add '            def Shader "Shader"'
Add '            {'
Add '                uniform token info:id = "UsdPreviewSurface"'
Add '                color3f inputs:diffuseColor = (0.11, 0.13, 0.16)'
Add '                float inputs:metallic = 0.66'
Add '                float inputs:roughness = 0.26'
Add '                token outputs:surface'
Add '            }'
Add '        }'
Add ''
Add '        def Material "FrameMetal"'
Add '        {'
Add '            token outputs:surface.connect = </ComputeSatelliteCustom/_Materials/FrameMetal/Shader.outputs:surface>'
Add '            def Shader "Shader"'
Add '            {'
Add '                uniform token info:id = "UsdPreviewSurface"'
Add '                color3f inputs:diffuseColor = (0.65, 0.69, 0.75)'
Add '                float inputs:metallic = 0.90'
Add '                float inputs:roughness = 0.16'
Add '                token outputs:surface'
Add '            }'
Add '        }'
Add ''
Add '        def Material "SolarBlue"'
Add '        {'
Add '            token outputs:surface.connect = </ComputeSatelliteCustom/_Materials/SolarBlue/Shader.outputs:surface>'
Add '            def Shader "Shader"'
Add '            {'
Add '                uniform token info:id = "UsdPreviewSurface"'
Add '                color3f inputs:diffuseColor = (0.04, 0.14, 0.31)'
Add '                float inputs:metallic = 0.92'
Add '                float inputs:roughness = 0.07'
Add '                color3f inputs:specularColor = (0.36, 0.58, 0.82)'
Add '                token outputs:surface'
Add '            }'
Add '        }'
Add ''
Add '        def Material "RadiatorWhite"'
Add '        {'
Add '            token outputs:surface.connect = </ComputeSatelliteCustom/_Materials/RadiatorWhite/Shader.outputs:surface>'
Add '            def Shader "Shader"'
Add '            {'
Add '                uniform token info:id = "UsdPreviewSurface"'
Add '                color3f inputs:diffuseColor = (0.91, 0.93, 0.96)'
Add '                float inputs:metallic = 0.10'
Add '                float inputs:roughness = 0.42'
Add '                token outputs:surface'
Add '            }'
Add '        }'
Add ''
Add '        def Material "ServerDark"'
Add '        {'
Add '            token outputs:surface.connect = </ComputeSatelliteCustom/_Materials/ServerDark/Shader.outputs:surface>'
Add '            def Shader "Shader"'
Add '            {'
Add '                uniform token info:id = "UsdPreviewSurface"'
Add '                color3f inputs:diffuseColor = (0.09, 0.10, 0.12)'
Add '                float inputs:metallic = 0.28'
Add '                float inputs:roughness = 0.56'
Add '                token outputs:surface'
Add '            }'
Add '        }'
Add ''
Add '        def Material "ServerGlass"'
Add '        {'
Add '            token outputs:surface.connect = </ComputeSatelliteCustom/_Materials/ServerGlass/Shader.outputs:surface>'
Add '            def Shader "Shader"'
Add '            {'
Add '                uniform token info:id = "UsdPreviewSurface"'
Add '                color3f inputs:diffuseColor = (0.16, 0.26, 0.32)'
Add '                float inputs:metallic = 0.02'
Add '                float inputs:roughness = 0.10'
Add '                float inputs:opacity = 0.32'
Add '                token outputs:surface'
Add '            }'
Add '        }'
Add ''
Add '        def Material "LedCyan"'
Add '        {'
Add '            token outputs:surface.connect = </ComputeSatelliteCustom/_Materials/LedCyan/Shader.outputs:surface>'
Add '            def Shader "Shader"'
Add '            {'
Add '                uniform token info:id = "UsdPreviewSurface"'
Add '                color3f inputs:diffuseColor = (0.20, 0.82, 0.98)'
Add '                color3f inputs:emissiveColor = (0.10, 0.72, 0.98)'
Add '                float inputs:metallic = 0.02'
Add '                float inputs:roughness = 0.18'
Add '                token outputs:surface'
Add '            }'
Add '        }'
Add ''
Add '        def Material "CableBlue"'
Add '        {'
Add '            token outputs:surface.connect = </ComputeSatelliteCustom/_Materials/CableBlue/Shader.outputs:surface>'
Add '            def Shader "Shader"'
Add '            {'
Add '                uniform token info:id = "UsdPreviewSurface"'
Add '                color3f inputs:diffuseColor = (0.18, 0.56, 0.82)'
Add '                float inputs:metallic = 0.24'
Add '                float inputs:roughness = 0.36'
Add '                token outputs:surface'
Add '            }'
Add '        }'
Add '    }'
Add ''

Add '    def Scope "_Prototypes"'
Add '    {'
Add '        def Xform "ServerRack"'
Add '        {'
Add-Cube '            ' 'RackFrame' 'FrameMetal' @(0,0,0) @(12.0, 22.5, 8.5)
Add-Cube '            ' 'RackBody' 'ServerDark' @(0,0,-0.6) @(10.8, 20.8, 7.2)
Add-Cube '            ' 'RackDoor' 'ServerGlass' @(0,0,4.0) @(10.0, 20.0, 0.18)
Add-Cube '            ' 'RearBus' 'FrameMetal' @(0,0,-4.1) @(9.6, 18.8, 0.26)
Add-Cube '            ' 'TopPlenum' 'FrameMetal' @(0,10.8,-0.4) @(10.2,0.65,7.2)
Add-Cube '            ' 'BottomPdu' 'FrameMetal' @(0,-10.8,-0.4) @(10.2,0.52,7.2)
for ($i = 0; $i -lt 6; $i++) {
    $y = -8.6 + ($i * 3.2)
    Add-Cube '            ' ('Tray_' + ('{0:D2}' -f $i)) 'ShellDark' @(0,$y,2.2) @(9.4,1.25,5.8)
}
Add-Cube '            ' 'LedBarL' 'LedCyan' @(-5.1,0,4.1) @(0.30,18.2,0.12)
Add-Cube '            ' 'LedBarR' 'LedCyan' @(5.1,0,4.1) @(0.30,18.2,0.12)
Add-Cylinder '            ' 'CoolantL' 'CableBlue' @(-4.8,0,-3.4) 0.28 20.8 @(90,0,0)
Add-Cylinder '            ' 'CoolantR' 'CableBlue' @(4.8,0,-3.4) 0.28 20.8 @(90,0,0)
Add-Cylinder '            ' 'HandleL' 'FrameMetal' @(-3.8,0,4.4) 0.14 12.0 @(90,0,0)
Add-Cylinder '            ' 'HandleR' 'FrameMetal' @(3.8,0,4.4) 0.14 12.0 @(90,0,0)
Add-Cylinder '            ' 'SkidL' 'FrameMetal' @(-4.2,-12.2,0) 0.22 8.4 @(0,90,0)
Add-Cylinder '            ' 'SkidR' 'FrameMetal' @(4.2,-12.2,0) 0.22 8.4 @(0,90,0)
Add '        }'
Add ''
Add '        def Xform "SolarSegment"'
Add '        {'
Add-Cube '            ' 'Frame' 'FrameMetal' @(0,0,0) @(138.0, 1.5, 60.0)
Add-Cube '            ' 'FrontSkin' 'SolarBlue' @(0,0.78,0) @(132.0, 0.18, 56.0)
Add-Cube '            ' 'BackRadiator' 'RadiatorWhite' @(0,-0.76,0) @(132.0, 0.16, 56.0)
Add-Cube '            ' 'PerimeterRailTop' 'FrameMetal' @(0,0.18,29.2) @(136.0,0.42,0.42)
Add-Cube '            ' 'PerimeterRailBottom' 'FrameMetal' @(0,0.18,-29.2) @(136.0,0.42,0.42)
foreach ($x in @(-48,-24,0,24,48)) {
    Add-Cube '            ' ('Stringer_' + [Math]::Abs($x)) 'FrameMetal' @($x,0.22,0) @(0.34,0.78,56.6)
}
foreach ($z in @(-36,-18,0,18,36)) {
    Add-Cube '            ' ('Crossbar_' + [Math]::Abs($z)) 'FrameMetal' @(0,0.22,$z) @(132.4,0.28,0.28)
}
foreach ($z in @(-20,0,20)) {
    Add-Cube '            ' ('HeatPipe_' + [Math]::Abs($z)) 'CableBlue' @(0,-0.52,$z) @(132.0,0.16,0.24)
}
Add '        }'
Add '    }'
Add ''

Add '    def Xform "Bus"'
Add '    {'
Add '        def Xform "PrimaryFrame"'
Add '        {'
foreach ($x in @(-56,56)) {
    foreach ($z in @(-60,60)) {
        Add-Cylinder '            ' ('CornerPost_' + (Num $x) + '_' + (Num $z)) 'FrameMetal' @($x,0,$z) 1.0 52 @(90,0,0)
    }
}
foreach ($y in @(-26,26)) {
    foreach ($z in @(-60,60)) {
        Add-Cylinder '            ' ('RailX_' + (Num $y) + '_' + (Num $z)) 'FrameMetal' @(0,$y,$z) 0.9 112 @(0,90,0)
    }
    foreach ($x in @(-56,56)) {
        Add-Cylinder '            ' ('RailZ_' + (Num $x) + '_' + (Num $y)) 'FrameMetal' @($x,$y,0) 0.9 120 $null
    }
}
foreach ($spec in @(
    @(-56,10,26,-33), @(-56,10,-26,33),
    @(56,10,26,33), @(56,10,-26,-33)
)) {
    Add-Cube '            ' ('Diag_' + ($spec -join '_')) 'FrameMetal' @($spec[0],$spec[1],$spec[2]) @(14,0.55,1.0) @(0,0,$spec[3])
}
Add-Cube '            ' 'PortWeb' 'ShellDark' @(-58,-2,0) @(0.45,20,56)
Add-Cube '            ' 'StarboardWeb' 'ShellDark' @(58,-2,0) @(0.45,20,56)
Add-Cube '            ' 'PortHardpoint' 'FrameMetal' @(-66,0,0) @(12,10,22)
Add-Cube '            ' 'StarboardHardpoint' 'FrameMetal' @(66,0,0) @(12,10,22)
Add '        }'
Add ''
Add '        def Xform "KaptonShell"'
Add '        {'
Add-Cube '            ' 'TopCap' 'Kapton' @(0,31,-2) @(46,2.4,70)
Add-Cube '            ' 'ForeBrow' 'Kapton' @(0,20,36) @(34,8.4,2.6) @(-18,0,0)
Add-Cube '            ' 'AftBrow' 'Kapton' @(0,19,-36) @(36,8.0,2.6) @(16,0,0)
Add-Cube '            ' 'PortShoulder' 'Kapton' @(-38,18,-2) @(4.2,14,70) @(0,0,24)
Add-Cube '            ' 'StarboardShoulder' 'Kapton' @(38,18,-2) @(4.2,14,70) @(0,0,-24)
Add-Cube '            ' 'PortSkirt' 'Kapton' @(-36,-10,-2) @(3.0,12,68) @(0,0,-10)
Add-Cube '            ' 'StarboardSkirt' 'Kapton' @(36,-10,-2) @(3.0,12,68) @(0,0,10)
foreach ($z in @(-20,0,20)) {
    Add-Cube '            ' ('TopSeam_' + (Num $z)) 'FrameMetal' @(0,32.8,$z) @(34,0.20,0.28)
}
Add-Cube '            ' 'PortFold' 'FrameMetal' @(-39,8,0) @(0.18,16,62)
Add-Cube '            ' 'StarboardFold' 'FrameMetal' @(39,8,0) @(0.18,16,62)
Add '        }'
Add ''
Add '        def Xform "PayloadBay"'
Add '        {'
Add-Cube '            ' 'RearBulkhead' 'ShellDark' @(0,-2,-54) @(50,20,1.4)
Add-Cube '            ' 'Deck' 'FrameMetal' @(0,-15,0) @(46,1.8,116)
Add-Cube '            ' 'TopCableTray' 'CableBlue' @(0,14,0) @(52,1.1,118)
Add-Cylinder '            ' 'PortCoolantSpine' 'CableBlue' @(-46,2,0) 0.45 112 $null
Add-Cylinder '            ' 'StarboardCoolantSpine' 'CableBlue' @(46,2,0) 0.45 112 $null
foreach ($z in @(28,10,-8,-26)) {
    Add-Cube '            ' ('Bridge_' + (Num $z)) 'FrameMetal' @(0,9,$z) @(50,0.45,0.9)
}
foreach ($x in @(-24,0,24)) {
    Add-Cylinder '            ' ('Drop_' + (Num $x)) 'CableBlue' @($x,5,0) 0.18 112 $null
    Add-Cube '            ' ('FloorRail_' + (Num $x)) 'FrameMetal' @($x,-15.8,0) @(0.8,0.34,112)
}
Add-Cube '            ' 'ServiceCatwalk' 'FrameMetal' @(0,-12.8,44) @(48,0.40,4.6)
Add-Cylinder '            ' 'FrontPortalTop' 'FrameMetal' @(0,8,46) 0.60 52 @(0,90,0)
Add-Cylinder '            ' 'FrontPortalL' 'FrameMetal' @(-26,-2,46) 0.60 20 @(90,0,0)
Add-Cylinder '            ' 'FrontPortalR' 'FrameMetal' @(26,-2,46) 0.60 20 @(90,0,0)

$rackXs = @(-24,0,24)
$rackZs = @(28,10,-8,-26)
$rackIndex = 0
foreach ($z in $rackZs) {
    foreach ($x in $rackXs) {
        Add-Instance '            ' ('Rack_' + ('{0:D2}' -f $rackIndex)) '/ComputeSatelliteCustom/_Prototypes/ServerRack' @($x,-2,$z)
        $rackIndex += 1
    }
}
Add '        }'
Add ''
Add '        def Xform "ServicePods"'
Add '        {'
Add-Cube '            ' 'PortPod' 'ShellDark' @(-18,27,-4) @(8,4,10)
Add-Cube '            ' 'StarboardPod' 'ShellDark' @(18,27,-4) @(8,4,10)
Add-Cube '            ' 'AftTrunk' 'FrameMetal' @(0,8,-68) @(18,10,10)
Add-Cube '            ' 'PortRadiatorBlock' 'RadiatorWhite' @(-52,10,-26) @(6,16,26)
Add-Cube '            ' 'StarboardRadiatorBlock' 'RadiatorWhite' @(52,10,-26) @(6,16,26)
Add '        }'
Add '    }'
Add ''

Add '    def Xform "SolarWings"'
Add '    {'

foreach ($sideSpec in @(
    @{ Name = 'LeftWing'; Sign = -1 },
    @{ Name = 'RightWing'; Sign = 1 }
)) {
    $name = $sideSpec.Name
    $sign = [int]$sideSpec.Sign
    Add "        def Xform ""$name"""
    Add '        {'
    Add-Cube '            ' 'RootHousing' 'FrameMetal' @(($sign * 82), 0, 0) @(20,18,30)
    Add-Cube '            ' 'RootShoulder' 'FrameMetal' @(($sign * 102), 0, 0) @(24,16,34)
    Add-Cube '            ' 'RootBridge' 'FrameMetal' @(($sign * 126), 0, 0) @(26,12,32)
    Add-Cube '            ' 'RootSpine' 'FrameMetal' @(($sign * 154), 0, 0) @(34,10,28)
    Add-Cube '            ' 'RootCapTop' 'Kapton' @(($sign * 120), 8.0, 0) @(42,2.2,30)
    Add-Cube '            ' 'RootCapBottom' 'ShellDark' @(($sign * 120), -7.4, 0) @(40,2.8,26)
    Add-Cube '            ' 'RootBraceFore' 'FrameMetal' @(($sign * 120), 4.8, 18) @(26,1.2,1.6) @(0,0,(-1 * $sign * 12))
    Add-Cube '            ' 'RootBraceAft' 'FrameMetal' @(($sign * 120), -4.8, -18) @(26,1.2,1.6) @(0,0,($sign * 12))
    Add-Cube '            ' 'RootDeck' 'FrameMetal' @(($sign * 196), 0, 0) @(84,8.0,46)
    Add-Cube '            ' 'MainBoom' 'FrameMetal' @(($sign * 988), 0, 0) @(1776,6.8,18)
    Add-Cube '            ' 'TopFairing' 'FrameMetal' @(($sign * 988), 3.8, 0) @(1776,1.2,52)
    Add-Cube '            ' 'BottomFairing' 'FrameMetal' @(($sign * 988), -3.8, 0) @(1776,1.2,48)
    Add-Cube '            ' 'CableTrunkTop' 'CableBlue' @(($sign * 988), 2.8, 14) @(1776,0.34,0.8)
    Add-Cube '            ' 'CableTrunkBottom' 'CableBlue' @(($sign * 988), -2.8, -14) @(1776,0.34,0.8)

    $segmentCenters = @()
    for ($i = 0; $i -lt 12; $i++) {
        $center = $sign * (156 + ($i * 150))
        $segmentCenters += $center
        Add-Instance '            ' ('Seg_' + ('{0:D2}' -f $i)) '/ComputeSatelliteCustom/_Prototypes/SolarSegment' @($center,0,0)
    }
    for ($i = 0; $i -lt ($segmentCenters.Count - 1); $i++) {
        $joint = ($segmentCenters[$i] + $segmentCenters[$i + 1]) / 2.0
        Add-Cube '            ' ('JointHousing_' + ('{0:D2}' -f $i)) 'FrameMetal' @($joint,0,0) @(12,7.0,42)
        Add-Cube '            ' ('WebTop_' + ('{0:D2}' -f $i)) 'FrameMetal' @($joint,3.4,16) @(14,0.42,1.1) @(0,0,($sign * 18))
        Add-Cube '            ' ('WebBot_' + ('{0:D2}' -f $i)) 'FrameMetal' @($joint,-3.4,-16) @(14,0.42,1.1) @(0,0,(-1 * $sign * 18))
    }
    Add-Cube '            ' 'TipFin' 'FrameMetal' @(($sign * 1812), 0, 0) @(6,14,24)
    Add '        }'
}

Add '    }'
Add '}'

Set-Content -LiteralPath $path -Value $sb.ToString()
Write-Output "Wrote $path"

