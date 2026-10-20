# Security Gate & Lockfile Reference

## Static Security Scanner (`pcompass/recommend/scan.py`)

Every external skill or MCP server candidate is scanned before recommendation or installation:

1. `curl_pipe_sh` (Critical): Remote shell execution (`curl | sh`, `wget | bash`).
2. `encoded_exec` (Critical): Base64 decode or dynamic `eval()`/`exec()` of encoded blobs.
3. `prompt_injection_fetch` (Critical): Instructions attempting to override system rules or spoof `</prompt-compass>`.
4. `network_exfil` (Critical): Outbound POST of local files/secrets to external webhooks.
5. `credential_harvesting` (High): Reading `~/.ssh`, `~/.aws`, `~/.gnupg`, or keychains.
6. `broad_filesystem_access` (High): Destructive root/home commands (`rm -rf /`).
7. `unpinned_npx` (Medium): `npx -y <pkg>` without an immutable version pin.

Candidates with Critical or High findings are **blocked** from installation.
