# Pilot safety boundary

The Pilot controller is a **PreToolUse deny-gate**: actions routed through `pre_tool_use` are checked before execution, constrained to the configured pilot workspace, and logged with blast radius. It denies merges and execution of tracked dangerous scripts before they run.

It is not a kernel, container-runtime, or Git hosting enforcement point. A process that bypasses the controller entirely cannot be intercepted by this Python hook. Production deployment must therefore keep the pilot in its workspace sandbox, grant write access only to the pilot repository, and route merge/run tools through this controller. Rollback is honest compensation (`git revert`) for an already landed commit; it is not undo.
