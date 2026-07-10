# Resume TASK 1 after rate limit reset
# Schedule this in Windows Task Scheduler to fire when your Pro limit resets

Set-Location "C:\Users\Siddhant Gupta\Documents\ShiaanX"

$prompt = @"
The rate limit has reset. You were running TASK 1 (feature recognition audit on the Motor Mount) on branch audit/feature-recognition-motor-mount.

To resume:
1. Run: git checkout audit/feature-recognition-motor-mount
2. Read all files in the audit/ directory to understand what has been completed so far
3. Check which steps from TASK_1_feature_recognition_audit.md are done vs. still pending
4. Continue from the next incomplete step - do not redo work that is already on disk
5. When complete, write FINDINGS_feature_recognition.md

Read CLAUDE.md first for project context. Then resume.
"@

# Launch claude with the resume prompt
# -p flag runs non-interactively (single response). Remove -p for interactive mode.
$prompt | claude --dangerously-skip-permissions
