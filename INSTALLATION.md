# INSTALLATION

**DAB Control Suite – Server Installation Guide**  
**Status:** Draft (v0.1)

## Overview

This document describes the installation of the DAB Control Server on a Raspberry Pi.

The long-term goal is a one-click installer. Until then, installation is performed manually.

---

# System Requirements

## Hardware

- Raspberry Pi 4 or newer (Pi 5 recommended)
- Supported DAB receiver
- microSD card or SSD
- Network connection

## Software

- Raspberry Pi OS (64-bit) or Debian
- Python 3
- FFmpeg
- Icecast
- Git

---

# Planned Installer

Future versions will provide:

```text
install.sh

or

DAB-Control-Server.deb
```

The installer will automatically:

- install dependencies
- configure services
- enable autostart
- configure firewall (if required)
- perform health checks
- create default configuration
- verify hardware

---

# Manual Installation (Current)

1. Install operating system.
2. Update packages.
3. Install required dependencies.
4. Clone repository.
5. Install Python packages.
6. Configure the DAB receiver.
7. Start services.
8. Verify operation.

---

# Verification

After installation the following should be available:

- Web Dashboard
- Web Administration
- REST API
- Audio Stream

---

# Future Features

The installer will eventually support:

- automatic updates
- repair mode
- uninstall
- migration
- configuration backup
- restore

---

# Support

Please include the following information when requesting support:

- Operating system
- DAB Control Suite version
- Hardware
- Installation method
- Log output
- Error messages

---

Project Founder & Lead Developer

Michael Willner
