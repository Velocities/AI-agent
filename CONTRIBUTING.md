# Contributing

Setup is the [README quick start](README.md#quick-start). Run the tests with `pytest` from the repo root, using the project virtualenv.

## Comments

Write a short comment when the intent is not obvious from the name. One or two lines is enough. Say what the step is for, in plain language.

```python
# Check if the model's command is allowed, and whether it is safe enough
# to auto-approve without the user
```

Skip the trailing period when the comment is one sentence. Use periods only when it is more than one sentence.

Put these notes on the higher-level flow, especially the agent loop in `ai_agent/agent/agent.py`. That method is the only place that orders parse, policy, permission, and execution. Add a comment in a helper only when a branch is easy to misread, such as a workflow container skipping host policy.

## Avoiding security regressions

Read this before adding commands, tools, or policy rules.

### 1. Never add shell execution

```python
# FORBIDDEN
subprocess.run(command_string, shell=True)
subprocess.run(["/bin/sh", "-c", model_output])
```

```python
# CORRECT
subprocess.run(argv_list, shell=False)
```

### 2. Never trust model output

All tool arguments are **attacker-controlled input**. Validate structure (Pydantic) **and** semantics (policy engine).

### 3. Do not parse shell syntax from strings

If you need new chaining behavior, add a new **`CommandExpr` type** and validate it explicitly — do not regex-match user/model strings.

### 4. Expand allow-lists carefully

When adding policy rules, specify:

- binary name
- subcommand (if applicable)
- path argument requirements
- network restrictions (if applicable)
- risk level

Default for unmatched commands is **FORBIDDEN**.

### 5. Beware implicit privilege escalation

| Change | Risk |
|--------|------|
| Adding `ai` to `docker` group | Near-root access |
| Allowing `docker run` | Container escape / mount host FS |
| Allowing remote `curl` | Data exfiltration |
| Allowing `\| sh` or `xargs` | Full shell bypass |
| Broadening readable paths to `/` | Credential exposure |

### 6. Chain risk aggregation

When adding operators, compute effective risk as **max(segment risks)** and reject the whole expression if any segment is FORBIDDEN.

### 7. Do not let the model self-approve

Never encode approval as a tool result the model can write. Approval must come from the CLI input layer.

### 8. Test policy, not just happy paths

Add tests for:

- forbidden patterns
- path traversal
- network exfil attempts
- chained bypass attempts
- confirmation gates
- audit records on denial

Run tests:

```bash
pytest
```
