<#
    בדיקת מוכנות לפני התקנת הפרסום האוטומטי. להרצה על שרת הלקוח.
    קוראת בלבד — לא משנה כלום.
#>

$Source   = 'D:\priority\zabanCatalog'
$ImgRoots = @('D:\priority\system\mail\Pics', 'D:\priority\system\images')
$Repo     = 'D:\sites\zabanCatalog'

$ok = $true
function Say($label, $value, $good) {
    $mark = if ($good) { 'OK  ' } else { 'FAIL' }
    $color = if ($good) { 'Green' } else { 'Red' }
    Write-Host ('{0}  {1,-22} {2}' -f $mark, $label, $value) -ForegroundColor $color
    if (-not $good) { $script:ok = $false }
}

Write-Host ''
Write-Host '--- כלים ---'

try { $py = (python --version 2>&1) -join ''; Say 'Python' $py ($py -match '\d') }
catch { Say 'Python' 'not found' $false }

try { $g = (git --version 2>&1) -join ''; Say 'Git' $g ($g -match '\d') }
catch { Say 'Git' 'not found' $false }

try {
    $pil = (python -c "import PIL; print(PIL.__version__)" 2>&1) -join ''
    Say 'Pillow' $pil ($pil -match '^\d')
} catch { Say 'Pillow' 'not installed  ->  pip install pillow' $false }

Write-Host ''
Write-Host '--- נתיבים ---'

if (Test-Path -LiteralPath $Source) {
    $reports = @(Get-ChildItem -LiteralPath $Source -File |
                 Where-Object { $_.Extension -match '(?i)^\.(htm|html|mht|mhtml)$' })
    $mb = [math]::Round((($reports | Measure-Object Length -Sum).Sum) / 1MB, 1)
    Say 'דוחות' ("$($reports.Count) קבצים, $mb MB   [$Source]") ($reports.Count -gt 0)
} else {
    Say 'דוחות' "לא קיים: $Source" $false
}

$totalImg = 0; $totalMb = 0
foreach ($r in $ImgRoots) {
    if (Test-Path -LiteralPath $r) {
        $f = @(Get-ChildItem -LiteralPath $r -File -Recurse -ErrorAction SilentlyContinue |
               Where-Object { $_.Extension -match '(?i)^\.(jpg|jpeg|png|gif|bmp|webp|ico)$' })
        $mb = [math]::Round((($f | Measure-Object Length -Sum).Sum) / 1MB, 1)
        $totalImg += $f.Count; $totalMb += $mb
        Say 'תמונות' ("$($f.Count) קבצים, $mb MB   [$r]") $true
    } else {
        Say 'תמונות' "לא קיים: $r" $false
    }
}

# לא Join-Path: הוא זורק חריגה כשהכונן כולו לא קיים
if (Test-Path -LiteralPath ($Repo.TrimEnd('\') + '\.git')) {
    Push-Location -LiteralPath $Repo
    $remote = (git remote get-url origin 2>&1) -join ''
    $branch = (git rev-parse --abbrev-ref HEAD 2>&1) -join ''
    Pop-Location
    $masked = $remote -replace '://[^@/]+@', '://***@'
    Say 'מאגר git' "$branch  ->  $masked" $true
    Say 'טוקן ב-remote' $(if ($remote -match '://[^@/]+@') { 'כן - push לא יבקש סיסמה' }
                         else { 'לא - push עלול לבקש סיסמה' }) ($remote -match '://[^@/]+@')
} else {
    Say 'מאגר git' "לא משוכפל. הרץ: git clone https://github.com/zabancatalog-sys/zabancatalog.git $Repo" $false
}

Write-Host ''
Write-Host '--- הערכת נפח ---'
$estMb = [math]::Round($totalImg * 0.06, 0)
Write-Host ("  $totalImg תמונות מקור ($totalMb MB) -> כ-$estMb MB אחרי הקטנה ל-700px")
Write-Host '  מגבלת GitHub Pages: 1024 MB לאתר'
if ($estMb -gt 800) {
    Write-Host '  אזהרה: קרוב למגבלה או מעליה' -ForegroundColor Yellow
}

Write-Host ''
if ($ok) { Write-Host 'הכל תקין - אפשר להמשיך לבנייה' -ForegroundColor Green }
else     { Write-Host 'יש בעיות לטפל בהן לפני הבנייה' -ForegroundColor Red }
Write-Host ''
