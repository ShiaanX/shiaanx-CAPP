# Resume TASK 4 after rate limit reset
Set-Location "C:\Users\Siddhant Gupta\Documents\ShiaanX"

$prompt = @"
The rate limit has reset. You were running TASK 4 (CAPP rule sheet expansion) on branch feature/rule-sheet-expansion.

To resume:
1. Run: git checkout feature/rule-sheet-expansion
2. Read audit/motor_mount_operations.json, audit/motor_mount_actual_params.json, audit/rule_coverage_matrix.md if they exist — these show what was completed
3. Check proposed_rules.json if it exists — see which materials/operations already have rules
4. Continue from the next incomplete step in TASK_4_rule_sheet_expansion.md - do not redo completed work
5. When complete, write FINDINGS_rule_expansion.md

Read CLAUDE.md first for project context. Then resume.
"@

$prompt | claude --dangerously-skip-permissions
