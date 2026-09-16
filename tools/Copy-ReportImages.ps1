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

# .NET במקום Split-Path: ב-PowerShell 5.1 אי אפשר לשלב -LiteralPath עם -Parent/-Leaf
$htmlDir = [System.IO.Path]::GetDirectoryName([System.IO.Path]::GetFullPath($Html))

# כל הפניה לקובץ תמונה. IE כותב את הנתיב בשתי צורות שונות באותו קובץ:
#   url(file:///D:/priority/...)   וגם   href="file:\\\d:\priority\..."
# ה-lookbehind מונע התאמה שמתחילה באמצע מילה — בלעדיו "file:" עצמה
# נקראת כאות כונן ("...fil[e:]\\\d:...") והנתיב יוצא מעוות
$ext = '(?:jpg|jpeg|png|gif|bmp|webp|ico|svg)'
$pattern = '(?i)(?:file:[\\/]*)?(?<![a-z0-9])[a-z]:[\\/][^"''()<>\s]+?\.' + $ext +
           '|(?<=["''(])[^"''()<>\s:]+?\.' + $ext

$refs = [regex]::Matches($content, $pattern) | ForEach-Object { $_.Value } | Sort-Object -Unique
Write-Host "נמצאו $($refs.Count) הפניות לתמונות בקובץ" -ForegroundColor Cyan

$copied  = 0
$skipped = 0
$missing = New-Object System.Collections.Generic.List[string]

foreach ($ref in $refs) {

    # file:///d:/priority/...  או  file:\\\d:\priority\...  ->  D:\priority\...
    # חותכים מאות הכונן והלאה, בלי תלות בצורת הקידומת
    $path = [System.Uri]::UnescapeDataString($ref)
    if ($path -match '(?i)(?<![a-z0-9])([a-z]:[\\/].*)$') {
        $path = $Matches[1]
    } else {
        $path = $path -replace '(?i)^file:[\\/]*', ''
    }
    $path = $path -replace '/', '\'

    # נתיב יחסי -> ביחס לתיקיית ה-HTM
    if ($path -notmatch '^[a-zA-Z]:\\') {
        $path = Join-Path $htmlDir $path
    }

    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        $missing.Add($ref)
        continue
    }

    $target = Join-Path $Dest ([System.IO.Path]::GetFileName($path))

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
