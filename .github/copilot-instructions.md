## Terminal Commands

Always use `mcp_gatekeeper_run_approved_command` for all shell commands in this repo instead of the raw terminal tool.

- Use `mcp_gatekeeper_run_approved_command` for commands such as `ls`, `pwd`, `git status`, `python`, `pytest`, `make`, and other shell work.
- Do not call the plain terminal command tool directly for commands that would execute on the local machine.
- If a command is safe and auto-approved, still use the GateKeeper approval wrapper so the request is routed through the configured approval flow.

This ensures all terminal execution is reviewed through the configured GateKeeper approval path.
