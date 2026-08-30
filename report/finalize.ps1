# Opens every built .docx in Word, updates all fields (table of contents, page numbers),
# saves the .docx in place and exports a PDF copy next to it.  ASCII-only on purpose:
# Windows PowerShell 5.1 reads un-BOMed scripts as ANSI, so documents are located by
# pattern instead of by name.
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$docs = Get-ChildItem -Path $dir -Filter "*.docx" | Where-Object { $_.Name -notlike "~*" }
if ($docs.Count -eq 0) { throw "no .docx found in $dir" }
$w = New-Object -ComObject Word.Application
$w.Visible = $false
foreach ($doc in $docs) {
    $src = $doc.FullName
    $pdf = [System.IO.Path]::ChangeExtension($src, ".pdf")
    $d = $w.Documents.Open($src)
    $d.Fields.Update() | Out-Null
    $d.TablesOfContents | ForEach-Object { $_.Update() }
    $d.Save()
    $d.ExportAsFixedFormat($pdf, 17)
    $pages = $d.ComputeStatistics(2)
    $d.Close(0)
    "saved docx and pdf, pages: $pages"
}
$w.Quit()
