# Security

Synclayer stores your files and exposes them over HTTP. Run it behind HTTPS (the bundled `synclayer deploy` helpers set up a reverse proxy) or a VPN, use a strong admin password, and keep `SL_SECRET_KEY` private. Admin MFA is available but the bundled web, desktop and CLI logins cannot complete it yet; see the README before enabling it.

To report a vulnerability, use [GitHub's private vulnerability reporting](https://github.com/KshRaven/synclayer/security/advisories/new) rather than a public issue. You will get a reply within a few days.
