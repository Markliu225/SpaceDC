param(
    [Parameter(Mandatory = $true)]
    [string]$DocumentPath,

    [Parameter(Mandatory = $true)]
    [string]$PdfPath
)

$ErrorActionPreference = 'Stop'
$resolvedDocument = (Resolve-Path -LiteralPath $DocumentPath).Path
$resolvedPdf = [IO.Path]::GetFullPath($PdfPath)
$pdfDirectory = [IO.Path]::GetDirectoryName($resolvedPdf)
New-Item -ItemType Directory -Force -Path $pdfDirectory | Out-Null

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
$document = $null

try {
    $document = $word.Documents.Open($resolvedDocument, $false, $false)
    $document.Fields.Update() | Out-Null
    for ($index = 1; $index -le $document.TablesOfContents.Count; $index++) {
        $document.TablesOfContents.Item($index).Update()
    }
    $document.Repaginate()
    $pageCount = $document.ComputeStatistics(2)
    $document.Save()
    $document.ExportAsFixedFormat(
        $resolvedPdf,
        17,
        $false,
        0,
        0,
        1,
        $pageCount,
        0,
        $true,
        $true,
        1,
        $false,
        $true,
        $false
    )
    Write-Output "PAGES=$pageCount"
    Write-Output "PDF=$resolvedPdf"
}
finally {
    if ($null -ne $document) {
        $document.Close($false)
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($document)
    }
    $word.Quit()
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($word)
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
