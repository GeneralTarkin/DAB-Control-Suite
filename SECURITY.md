# SECURITY

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.x | ✅ |
| 0.x Alpha/Beta | ⚠ Best effort |

---

## Reporting Security Issues

Please do **not** report security vulnerabilities through public GitHub issues.

Instead, contact the project maintainer directly until a dedicated security process is available.

Project Founder & Lead Developer:

**Michael Willner**

---

## Security Goals

The DAB Control Suite is designed with the following principles:

- Least privilege where practical
- Input validation
- Authenticated administration
- Secure REST API
- Safe file uploads
- Verified software updates
- Backup before update
- Rollback on failed updates
- No arbitrary command execution through the API

---

## Planned Security Features

### Authentication

- Administrator login
- Session management
- Optional API tokens

### File Uploads

- PNG validation
- File size limits
- Filename sanitization
- Path traversal protection

### Updates

- GitHub Releases only
- SHA-256 checksum verification
- Automatic backup before update
- Rollback support

### Logging

- Administrative actions
- Update history
- Authentication events
- Error reporting

---

## Responsible Disclosure

If you discover a vulnerability, please provide:

- Software version
- Operating system
- Hardware
- Steps to reproduce
- Expected behaviour
- Actual behaviour
- Proof of concept (if available)

Please allow reasonable time for investigation before public disclosure.

---

Thank you for helping improve the security of the DAB Control Suite.
