<#
    בונה את הקטלוג מדוחות Priority ודוחף ל-GitHub Pages.
    מיועד להרצה יומית מתוך מתזמן המשימות של Windows על שרת הלקוח.

    דוגמה:
        .\Publish-Catalog.ps1
        .\Publish-Catalog.ps1 -Source 'D:\priority\zabanCatalog' -Repo 'D:\sites\zabanCatalog'

    דרישות על השרת: Python 3 עם Pillow, Git, וכניסה ל-GitHub שמורה
    (git credential manager או PAT בכתובת ה-remote) כדי ש-push לא ישאל כלום.
#>

[CmdletBinding()]
param(
    [string]$Source   = 'D:\priority\zabanCatalog',
    [string]$Repo     = 'D:\sites\zabanCatalog',
    [string]$LogDir   = 'D:\sites\logs',
    [string[]]$ImgRoot = @('D:\priority\system\mail\Pics',
                           'D:\priority\system\images',
                           'D:\priority\system\images\coral\images',
                           'D:\priority\system\mail'),
    [int]$MaxEdge     = 220,
    [int]$Quality     = 72,
    [int]$MaxSiteMb   = 950,     # GitHub Pages מוגבל ל-1024; נעצרים לפני
    [switch]$Reindex,
    [int]$KeepLogs    = 30
)

$ErrorActionPreference = 'Stop'
$started = Get-Date

if (-not (Test-Path -LiteralPath $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$log = Join-Path $LogDir ('publish-{0:yyyy-MM-dd}.log' -f $started)

function Write-Log {
    param([string]$Message, [string]$Level = 'INFO')
    $line = '{0:yyyy-MM-dd HH:mm:ss}  {1,-5}  {2}' -f (Get-Date), $Level, $Message
    Add-Content -LiteralPath $log -Value $line -Encoding UTF8
    Write-Host $line
}

function Invoke-Step {
    param([string]$What, [scriptblock]$Command)
    Write-Log $What
    $out = & $Command 2>&1
    $code = $LASTEXITCODE
    if ($out) { $out | ForEach-Object { Write-Log "    $_" 'OUT' } }
    if ($null -ne $code -and $code -ne 0) {
        throw "$What נכשל (exit $code)"
    }
}

try {
    Write-Log '================ התחלה ================'
    Write-Log "מקור: $Source"
    Write-Log "מאגר: $Repo"

    foreach ($p in @($Source, $Repo)) {
        if (-not (Test-Path -LiteralPath $p)) { throw "נתיב לא קיים: $p" }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Repo '.git'))) {
        throw "$Repo אינו מאגר git"
    }

    $reports = Get-ChildItem -LiteralPath $Source -File |
               Where-Object { $_.Extension -match '(?i)^\.(mht|mhtml|htm|html)$' }
    if ($reports.Count -eq 0) { throw "לא נמצאו דוחות ב-$Source" }
    Write-Log "נמצאו $($reports.Count) דוחות"

    Push-Location -LiteralPath $Repo
    try {
        # מיישרים קו עם המאגר המרוחק לפני הבנייה, כדי ש-push לא יידחה
        Invoke-Step 'git fetch' { git fetch --quiet origin }
        Invoke-Step 'git reset' { git reset --quiet --hard origin/main }

        $buildArgs = @((Join-Path $Repo 'build.py'), '--src', $Source,
                       '--max-edge', $MaxEdge, '--quality', $Quality)
        if ($Reindex) { $buildArgs += '--reindex' }
        foreach ($r in $ImgRoot) {
            if (Test-Path -LiteralPath $r) { $buildArgs += @('--img-root', $r) }
            else { Write-Log "תיקיית תמונות לא קיימת, מדולגת: $r" 'WARN' }
        }
        # הפלט מופנה לקובץ ולא לצינור. צינור אל ForEach-Object נראה כמו
        # דרך נוחה לרשום התקדמות, אבל אם PowerShell לא מרוקן אותו מספיק
        # מהר מאגר ה-pipe מתמלא ו-print() ב-Python נחסם לנצח — הבנייה
        # קופאת בלי CPU ובלי שורה אחת ביומן. קובץ לא נחסם, ואפשר לעקוב
        # אחריו בזמן אמת עם Get-Content -Wait
        $buildLog = Join-Path $LogDir ('build-{0:yyyy-MM-dd-HHmm}.log' -f (Get-Date))
        Write-Log "בניית האתר (פלט מלא: $buildLog)"
        $buildArgs = @('-u') + $buildArgs
        & python @buildArgs *> $buildLog
        $buildCode = $LASTEXITCODE
        if (Test-Path -LiteralPath $buildLog) {
            Get-Content -LiteralPath $buildLog -Encoding UTF8 |
                ForEach-Object { Write-Log "    $_" 'OUT' }
        }
        if ($buildCode -ne 0) { throw "הבנייה נכשלה (exit $buildCode)" }

        # בלם נפח: GitHub Pages מפסיק להגיש אתר שחורג מ-1GB. עדיף להשאיר
        # את הגרסה הקודמת באוויר מאשר לדחוף גרסה שתשבור את האתר
        $published = @(Get-ChildItem -LiteralPath $Repo -Recurse -File -ErrorAction SilentlyContinue |
                       Where-Object { $_.FullName -notlike "*\.git\*" })
        $siteMb = [math]::Round((($published | Measure-Object Length -Sum).Sum) / 1MB, 0)
        Write-Log "נפח האתר: $siteMb MB מתוך $MaxSiteMb MB מותרים ($($published.Count) קבצים)"
        if ($siteMb -gt $MaxSiteMb) {
            throw "האתר תופס $siteMb MB, מעל הסף של $MaxSiteMb MB. לא פורסם. הקטן את MaxEdge והרץ שוב."
        }

        $dirty = git status --porcelain
        if (-not $dirty) {
            Write-Log 'אין שינויים — לא נדרש פרסום'
        } else {
            $count = ($dirty | Measure-Object).Count
            Write-Log "$count קבצים השתנו"
            Invoke-Step 'git add'    { git add -A }
            Invoke-Step 'git commit' {
                git -c core.quotepath=false commit -q -m ('Daily catalog update {0:yyyy-MM-dd HH:mm}' -f (Get-Date))
            }
            Invoke-Step 'git push'   { git push --quiet origin main }
            Write-Log 'פורסם בהצלחה'
        }
    } finally {
        Pop-Location
    }

    # ניקוי לוגים ישנים
    Get-ChildItem -LiteralPath $LogDir -Filter 'publish-*.log' |
        Sort-Object LastWriteTime -Descending |
        Select-Object -Skip $KeepLogs |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue }

    $secs = [int]((Get-Date) - $started).TotalSeconds
    Write-Log "================ סיום תקין ($secs שניות) ================"
    exit 0
}
catch {
    Write-Log $_.Exception.Message 'ERROR'
    if ($_.ScriptStackTrace) { Write-Log $_.ScriptStackTrace 'ERROR' }
    Write-Log '================ הסתיים בשגיאה ================'
    exit 1
}
