<#
    שולף מתוך דוח Priority שנשמר כ-HTM את כל הפניות התמונות,
    ומעתיק את קבצי התמונה עצמם לתיקיית יעד אחת.

    הרצה על המחשב שבו קיים כונן D: של Priority.

    דוגמה:
        .\Copy-ReportImages.ps1
        .\Copy-ReportImages.ps1 -Html "C:\...\p123.htm" -Dest "C:\temp\pic"
#>

[CmdletBinding()]
param(
    [string]$Html = 'C:\Users\freetech.sys\AppData\Local\Temp\p1832400277.htm',
    [string]$Dest = 'C:\temp\pic'
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $Html)) {
    Write-Error "לא נמצא הקובץ: $Html"
    return
}

if (-not (Test-Path -LiteralPath $Dest)) {
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
}

$content = Get-Content -LiteralPath $Html -Raw -Encoding UTF8
$htmlDir = Split-Path -LiteralPath $Html -Parent

# כל הפניה לקובץ תמונה: file:///d:/..., נתיב מלא C:\..., או נתיב יחסי
$pattern = '(?i)(?:file:///)?[a-z]:[\\/][^"''()<>\s]+?\.(?:jpg|jpeg|png|gif|bmp|webp|ico|svg)|(?<=["''(])[^"''()<>\s:]+?\.(?:jpg|jpeg|png|gif|bmp|webp|ico|svg)'

$refs = [regex]::Matches($content, $pattern) | ForEach-Object { $_.Value } | Sort-Object -Unique
Write-Host "נמצאו $($refs.Count) הפניות לתמונות בקובץ" -ForegroundColor Cyan

$copied  = 0
$skipped = 0
$missing = New-Object System.Collections.Generic.List[string]

foreach ($ref in $refs) {

    # file:///d:/priority/... -> D:\priority\...
    $path = $ref -replace '(?i)^file:/+', ''
    $path = [System.Uri]::UnescapeDataString($path)
    $path = $path -replace '/', '\'

    # נתיב יחסי -> ביחס לתיקיית ה-HTM
    if ($path -notmatch '^[a-zA-Z]:\\') {
        $path = Join-Path $htmlDir $path
    }

    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        $missing.Add($ref)
        continue
    }

    $target = Join-Path $Dest (Split-Path -LiteralPath $path -Leaf)

    if (Test-Path -LiteralPath $target) {
        $skipped++
        continue
    }

    Copy-Item -LiteralPath $path -Destination $target -Force
    $copied++
}

Write-Host ''
Write-Host "הועתקו : $copied"  -ForegroundColor Green
Write-Host "קיימות : $skipped" -ForegroundColor DarkGray
Write-Host "חסרות  : $($missing.Count)" -ForegroundColor Yellow

if ($missing.Count -gt 0) {
    Write-Host ''
    Write-Host 'לא נמצאו על הדיסק:' -ForegroundColor Yellow
    $missing | ForEach-Object { Write-Host "   $_" }
}

Write-Host ''
Write-Host "היעד: $Dest" -ForegroundColor Cyan
