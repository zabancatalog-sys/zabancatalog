<#
    רושם משימה יומית במתזמן המשימות של Windows שמריצה את Publish-Catalog.ps1.
    להרצה פעם אחת, כמנהל, על שרת הלקוח.

    דוגמה:
        .\Register-PublishTask.ps1 -At 06:30
        .\Register-PublishTask.ps1 -At 06:30 -User 'DOMAIN\svc_priority'

    בלי -User המשימה תרוץ תחת SYSTEM. שים לב: ל-SYSTEM אין את פרטי הכניסה
    ל-GitHub ששמרת כמשתמש רגיל, ולכן ה-push ייכשל. אם ה-remote לא מכיל
    טוקן — הרץ תחת חשבון משתמש עם -User.
#>

[CmdletBinding()]
param(
    [string]$TaskName = 'ZabanCatalog Publish',
    [string]$At       = '06:30',
    [string]$Script   = 'D:\sites\zabanCatalog\tools\Publish-Catalog.ps1',
    [string]$User,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $Script)) {
    throw "לא נמצא הסקריפט: $Script"
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing -and -not $Force) {
    throw "המשימה '$TaskName' כבר קיימת. הוסף -Force כדי להחליף אותה."
}
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "המשימה הקודמת הוסרה"
}

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument (
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $Script)

$trigger = New-ScheduledTaskTrigger -Daily -At $At

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 15)

$params = @{
    TaskName    = $TaskName
    Action      = $action
    Trigger     = $trigger
    Settings    = $settings
    Description = 'בונה את קטלוג הסניפים מדוחות Priority ומפרסם ל-GitHub Pages'
}

if ($User) {
    $cred = Get-Credential -UserName $User -Message "סיסמה עבור $User (המשימה תרוץ תחת החשבון הזה)"
    Register-ScheduledTask @params -User $cred.UserName `
        -Password $cred.GetNetworkCredential().Password -RunLevel Highest | Out-Null
    Write-Host "נרשמה משימה '$TaskName' לשעה $At תחת $User"
} else {
    Register-ScheduledTask @params -User 'SYSTEM' -RunLevel Highest | Out-Null
    Write-Host "נרשמה משימה '$TaskName' לשעה $At תחת SYSTEM"
    Write-Warning 'תחת SYSTEM אין גישה לפרטי הכניסה ל-GitHub. ודא שה-remote מכיל טוקן, אחרת הרץ שוב עם -User.'
}

Write-Host ''
Write-Host 'בדיקה מיידית:'
Write-Host "    Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "    Get-ScheduledTaskInfo -TaskName '$TaskName'"
