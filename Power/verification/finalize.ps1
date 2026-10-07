param([string]$Name = 'SDTwin_Power_Test_Report_CN')
$ErrorActionPreference = 'Stop'
$dir = Split-Path -Parent $PSScriptRoot
$docx = [System.IO.Path]::GetFullPath((Join-Path $dir "$Name.docx")).Replace('\','/')
$pdf = [System.IO.Path]::GetFullPath((Join-Path $dir "$Name.pdf")).Replace('\','/')
if (Test-Path -LiteralPath $pdf) {
    $priorDir = Join-Path $PSScriptRoot 'qa/pdf_versions'
    New-Item -ItemType Directory -Force -Path $priorDir | Out-Null
    $priorName = "$Name-$(Get-Date -Format 'yyyyMMdd-HHmmss-fff').pdf"
    Move-Item -LiteralPath $pdf -Destination (Join-Path $priorDir $priorName)
}
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    # Open the original path directly; update the inherited Orbit TOC in Word.
    $doc = $word.Documents.Open($docx, $false, $false, $false)
    foreach ($toc in $doc.TablesOfContents) { $toc.Update() }
    $doc.Repaginate()
    foreach ($toc in $doc.TablesOfContents) { $toc.UpdatePageNumbers() }
    $doc.Save()
    Write-Output 'Document fields updated; exporting PDF'
    $doc.SaveAs2([string]$pdf, 17)
    "PDF pages: " + $doc.ComputeStatistics(2)
    $doc.Close($false)
} finally {
    $word.Quit()
}
Write-Output $pdf
