# claude-bash-no-ssh-agent — Bash-tool subshells can't reach user's ssh-agent

**Type:** incident
**Status:** active
**Updated:** 2026-05-29

## Summary
The user's interactive gpvm shell has a working `ssh-agent` (forwarded from
laptop via `ssh -A`, or started by a long-lived screen/tmux), so
`git push` to GitHub via `git@github.com:...` Just Works for them. But
Claude's Bash tool launches subprocesses that do NOT inherit
`SSH_AUTH_SOCK`, and even when the env var IS set in the subshell, the
socket path resolves to "No such file or directory" — agent inherits
through real `ssh -A` parentage, not via env-var copy. Net effect:
Claude cannot `git push` on the user's behalf even though the user can.

## Root cause
`ssh-agent` uses a Unix-domain socket whose access is bounded by the
session/uid that created it. Bash-tool subprocesses are spawned by the
Claude CLI as a sibling of the user's interactive shell, not as a
descendant — so the kernel's session-keyring + socket-perm chain that
makes the agent reachable from the user's shell doesn't extend to
Claude's subshell.

## Workarounds (in order of preference)

1. **User runs the push themselves.** Claude stages files + commits +
   provides the exact `git push` / `gh repo create` lines; user
   executes them in their own shell. Cleanest, no auth fight.

2. **User starts a path-pinned agent Claude can reach:**
   ```bash
   eval $(ssh-agent -s -a /tmp/ssh-oksuzian-agent)
   ssh-add ~/.ssh/id_ed25519
   chmod 660 /tmp/ssh-oksuzian-agent   # if needed
   ```
   Then Claude can `SSH_AUTH_SOCK=/tmp/ssh-oksuzian-agent git push`.
   Survives across Bash subshells for the agent's lifetime.

3. **Personal Access Token via gh CLI:**
   ```bash
   echo "ghp_xxx..." | gh auth login --with-token
   ```
   Persists in `~/.config/gh/hosts.yml` across sessions; Claude can
   then use `gh repo create` and HTTPS `git push`.

4. **HTTPS push with embedded PAT** — `git push https://oksuzian:ghp_xxx@github.com/owner/repo.git`.
   Token leaks into shell history; only do this for one-off pushes.

## Key facts

- **`gh auth status` shows `not logged into any GitHub hosts`** by
  default on a fresh Claude session, even though the user can
  `git push` from their own shell. The two auth surfaces are
  independent.
- **Three candidate SSH keys exist** at `~/.ssh/`:
  `id_ed25519` (newest), `github_rsa`, `id_rsa`. None are individually
  reachable from a Claude subshell without the agent (the `id_ed25519`
  key has a passphrase; a non-interactive `ssh -i ~/.ssh/id_ed25519`
  fails with `Permission denied (publickey)` because the key file
  isn't actually loaded without the agent unlocking it).
- **User's interactive `$SSH_AUTH_SOCK` lives at
  `/tmp/ssh-XXXXv4gZfn/agent.<pid>`** — but copying that path into a
  Bash-tool subshell still produces `Error connecting to agent: No
  such file or directory`. Don't waste time trying to inherit it;
  use workaround 1, 2, or 3.

## Cross-links
- Related: [[slack-bot-dm-channel-not-found]] (parallel pattern —
  different auth identities, can't piggyback on each other's session)
- External: [GitHub SSH key setup](https://docs.github.com/en/authentication/connecting-to-github-with-ssh)

## Open questions / TODO
- Test whether `agent.<pid>` becomes reachable if the user `chmod a+rwx`
  the parent `/tmp/ssh-XXXX*/` dir — gpvm `/tmp` is shared, so this
  might be a perm rather than a session issue.
