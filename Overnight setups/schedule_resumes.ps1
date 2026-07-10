# Run this script ONCE tonight after you know what time your Pro limit resets.
# Edit the $resetTime variable to match your reset time.
# Example: if limit hits at 11:30pm and resets after 5 hours, set to "04:30"

param(
    [string]$resetTime = "06:00"   # <-- change this to your actual reset time (24hr format)
)

$dir = "C:\Users\Siddhant Gupta\Documents\ShiaanX\Overnight setups"

$tasks = @(
    @{ Name = "ShiaanX-Resume-Task1"; Script = "resume_task1.ps1" },
    @{ Name = "ShiaanX-Resume-Task2"; Script = "resume_task2.ps1" },
    @{ Name = "ShiaanX-Resume-Task4"; Script = "resume_task4.ps1" }
)

foreach ($t in $tasks) {
    $action  = New-ScheduledTaskAction -Execute "powershell.exe" `
                 -Argument "-NonInteractive -File `"$dir\$($t.Script)`"" `
                 -WorkingDirectory "C:\Users\Siddhant Gupta\Documents\ShiaanX"
    $trigger = New-ScheduledTaskTrigger -Once -At $resetTime
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 8) `
                  -WakeToRun

    Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger `
      -Settings $settings -RunLevel Highest -Force | Out-Null

    Write-Host "Scheduled $($t.Name) to run at $resetTime"
}

Write-Host "`nAll resume tasks scheduled. Check Task Scheduler to confirm."
Write-Host "To cancel: Get-ScheduledTask -TaskName 'ShiaanX-*' | Unregister-ScheduledTask -Confirm:`$false"
