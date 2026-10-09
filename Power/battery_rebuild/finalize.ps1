param([string[]]$Names=@('SDTwin_Power_Design_Report_CN_v19','SDTwin_Power_Design_Report_EN_v19','SDTwin_Battery_EKF_RLS_Test_Report_CN'))
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$word=New-Object -ComObject Word.Application
$word.Visible=$false;$word.DisplayAlerts=0
try {
 foreach($name in $Names) {
  $docx=[System.IO.Path]::GetFullPath((Join-Path $root "$name.docx")).Replace('\','/')
  $pdf=[System.IO.Path]::GetFullPath((Join-Path $root "$name.pdf")).Replace('\','/')
  if(Test-Path -LiteralPath $pdf){
   $versions=Join-Path $PSScriptRoot 'qa/pdf_versions';New-Item -ItemType Directory -Force -Path $versions | Out-Null
   Move-Item -LiteralPath $pdf -Destination (Join-Path $versions "$name-$(Get-Date -Format 'yyyyMMdd-HHmmss-fff').pdf")
  }
  $doc=$word.Documents.Open($docx,$false,$false,$false)
  foreach($toc in $doc.TablesOfContents){$toc.Update()}
  $doc.Repaginate()
  foreach($toc in $doc.TablesOfContents){$toc.UpdatePageNumbers()}
  $doc.Save();$doc.SaveAs2([string]$pdf,17)
  Write-Output "$name pages=$($doc.ComputeStatistics(2))"
  $doc.Close($false)
 }
} finally {$word.Quit()}
