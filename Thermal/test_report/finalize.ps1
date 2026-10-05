# Refresh the table of contents of the generated test report in Word and save it, then export a PDF.
# The export runs in a fresh PowerShell process on a temporary copy: a second Word session started from the
# same process hangs in SaveAs2 on this document.
param([string]$Name = "SDTwin_Thermal_Test_Report_CN")
$dir = Split-Path -Parent $PSScriptRoot
$docx = Join-Path $dir "$Name.docx"
$pdf = Join-Path $dir "$Name.pdf"

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $doc = $word.Documents.Open($docx, $false, $false, $false)
    foreach ($toc in $doc.TablesOfContents) { $toc.Update() }
    $doc.Save()
    "toc updated, pages: " + $doc.ComputeStatistics(2)
    $doc.Close($false)
} finally {
    $word.Quit()
}

$copy = Join-Path $env:TEMP "$Name`_export.docx"
Copy-Item $docx $copy -Force
$job = Start-Job -ScriptBlock {
    param($src, $dst)
    $w = New-Object -ComObject Word.Application
    $w.Visible = $false
    $w.DisplayAlerts = 0
    try {
        $d = $w.Documents.Open($src, $false, $true, $false)
        $d.SaveAs2($dst, 17)
        $d.Close($false)
        "pdf saved"
    } finally { $w.Quit() }
} -ArgumentList $copy, $pdf
if (Wait-Job $job -Timeout 120) { Receive-Job $job } else {
    "pdf export timed out"
    Get-CimInstance Win32_Process -Filter "Name='WINWORD.EXE'" | Where-Object { $_.CommandLine -like '*Automation*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
}
Remove-Job $job -Force
Remove-Item $copy -Force -ErrorAction SilentlyContinue
