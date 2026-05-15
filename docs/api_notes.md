# DaVinci Resolve API Notes

## Connection
Requires DaVinci Resolve Studio.
Scripting needs to be enabled in Resolve preferences (System -> General -> External scripting using: Local).

## Common Limitations
- Some color grading tasks lack API hooks. Use the `automation` module for these.
- Rendering must be polled for completion.
