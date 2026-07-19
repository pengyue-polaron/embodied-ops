# Security

Do not report credentials, device keys, or live-control details in a public issue.
Use GitHub's private vulnerability reporting for security-sensitive findings.

Backends control real devices. They must validate configuration before opening
hardware and must fail closed on malformed, stale, or non-finite commands.
