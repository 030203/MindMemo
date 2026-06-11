# Development Logs

This directory stores the day-by-day engineering record for MySecondBrain.

## Goal

Keep an operational record of:

1. what was completed
2. what was verified
3. what remains to do
4. what risks or blockers exist

## File naming rule

Use one file per day:

```text
YYYY-MM-DD.md
```

Example:

```text
2026-05-25.md
```

## Required sections

Each daily file should include:

1. 今日完成
2. 验证记录
3. 风险 / 阻塞
4. 明日待办

## Template

Use:

- `dev_logs/_daily_template.md`

## Automation

A daily automation should update or create the current day's log file and keep the record aligned with the actual repository state.

Current automation:

- Name: `MySecondBrain Daily Dev Log`
- Schedule: every day at `21:30` local time
