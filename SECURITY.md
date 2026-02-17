# Security Policy

## Supported Versions

We release patches for security vulnerabilities. Currently supported versions:

| Version | Supported          |
| ------- | ------------------ |
| 1.2.x   | :white_check_mark: |
| 1.1.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

We take the security of RWS Tracking System seriously. If you believe you have found a security vulnerability, please report it to us as described below.

### Please do NOT:

- Open a public GitHub issue
- Disclose the vulnerability publicly before it has been addressed

### Please DO:

1. **Email us directly** at: [security contact - add your email]
2. **Provide detailed information**:
   - Type of vulnerability
   - Full paths of source file(s) related to the vulnerability
   - Location of the affected source code (tag/branch/commit or direct URL)
   - Step-by-step instructions to reproduce the issue
   - Proof-of-concept or exploit code (if possible)
   - Impact of the issue, including how an attacker might exploit it

### What to expect:

- **Acknowledgment**: We will acknowledge receipt of your vulnerability report within 48 hours
- **Updates**: We will send you regular updates about our progress
- **Timeline**: We aim to address critical vulnerabilities within 7 days
- **Credit**: We will credit you in the security advisory (unless you prefer to remain anonymous)

## Security Update Process

1. The security report is received and assigned to a primary handler
2. The problem is confirmed and a list of affected versions is determined
3. Code is audited to find any similar problems
4. Fixes are prepared for all supported versions
5. New versions are released and security advisory is published

## Security Best Practices

When using RWS Tracking System:

### Network Security
- Run API servers behind a firewall
- Use HTTPS/TLS for production deployments
- Implement authentication for API endpoints
- Use strong passwords for any credentials

### System Security
- Keep dependencies up to date
- Run with minimal required permissions
- Validate all input data
- Sanitize file paths and user inputs

### API Security
- Implement rate limiting
- Use API keys or JWT tokens
- Validate all API requests
- Log security-relevant events

## Known Security Considerations

### Camera Access
- The system requires camera access
- Ensure proper permissions are set
- Be aware of privacy implications

### Network Exposure
- API servers listen on network interfaces
- Default configuration binds to 0.0.0.0 (all interfaces)
- Consider using localhost or specific IPs in production

### Serial Port Access
- Hardware drivers require serial port access
- Ensure proper device permissions
- Validate serial communication data

## Security Advisories

Security advisories will be published at:
- GitHub Security Advisories: https://github.com/Kitjesen/RWS/security/advisories
- Release notes with security fixes will be clearly marked

## Comments on this Policy

If you have suggestions on how this process could be improved, please submit a pull request or open an issue.

---

**Last Updated**: 2024-02-17
