# Security Policy

## Reporting a Vulnerability

PentAGI is a penetration testing tool — vulnerabilities are our 9-to-5.

**If you find a security issue in PentAGI itself** (not a target you tested with it):

1. **Do not** open a public GitHub issue
2. Email: `security@pentagi.io` (or DM `@asdek` on Telegram)
3. Include:
   - Description of the issue
   - Steps to reproduce
   - Affected version / commit hash
   - Suggested fix (optional)

You'll receive an acknowledgment within 48 hours. We'll aim for a fix within 7 days.

## Scope

We care about:
- Remote code execution (in the PentAGI runtime, not in targets)
- Credential / API key leakage
- Privilege escalation via the Docker socket
- Data exfiltration from the sandbox

Out of scope:
- Vulnerabilities in pentest targets discovered *by* PentAGI (that's the point)
- Theoretical issues requiring physical access
- Dependency CVEs with no practical exploit path

## Safe Harbor

We won't pursue legal action against researchers who:
- Report issues through the above channel
- Do not exfiltrate or damage data
- Do not publicly disclose before a fix ships

## Recognition

We maintain a security hall of fame. Reporters who submit valid issues will be credited in the release notes (opt-out available).
