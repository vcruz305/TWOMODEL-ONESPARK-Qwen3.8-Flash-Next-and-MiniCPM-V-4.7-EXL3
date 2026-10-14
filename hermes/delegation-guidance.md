## Delegating to MiniCPM subagents

Your subagents run on a smaller local model (MiniCPM-V 4.7, 3B active parameters). They follow
instructions well and use tools reliably, but they make mistakes when they do exact work in their head.
When you delegate:

- Put everything a subagent needs in its goal: exact file paths, the exact question, and the form of the
  answer you want. Subagents cannot see this conversation.
- For anything that must be exact (counting, sums, arithmetic, parsing numbers or fields out of files,
  comparisons), tell the subagent in its goal to compute it with the terminal or execute_code tool and to
  report the value that the command printed, not a value worked out in its reply.
- Give each subagent its own output location if it writes files. Never have subagents write scratch files
  into a shared directory.
- Treat subagent results as claims: check them against each other and spot-check anything the user will
  rely on before you answer.
