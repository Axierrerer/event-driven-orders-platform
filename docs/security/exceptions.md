# Security exceptions

`make scan` fails on any **CRITICAL** finding and on any finding that has a fix available.
The items below are the remaining **HIGH** findings: all of them are in packages of the
Debian 13 (trixie) base image `python:3.12-slim-trixie`, and none of them has a fixed version
in Debian yet (`trivy image --severity HIGH`, 0 fixable).

| Packages | CVEs | Why it is accepted |
|----------|------|--------------------|
| util-linux family: `util-linux`, `mount`, `bsdutils`, `login`, `libmount1`, `libblkid1`, `libsmartcols1`, `libuuid1`, `liblastlog2-2` | CVE-2026-76642, CVE-2026-78408, CVE-2026-78409, CVE-2026-78410 | Essential packages of the base image. The services never call `mount`, `login` or other util-linux tools; containers run as an unprivileged user without a shell entrypoint. |
| `libsystemd0`, `libudev1` | CVE-2026-16742 | Libraries pulled in by the base image; systemd/udev do not run in the containers. |
| `ncurses-base`, `ncurses-bin`, `libncursesw6`, `libtinfo6` | CVE-2025-69720 | Terminal libraries; no interactive terminal is used by the services. |
| `perl-base` | CVE-2026-9538 | Required by Debian tooling; the services do not execute Perl. |
| `libacl1` | CVE-2026-54369 | Filesystem ACL library of the base image; the services do not manage ACLs. |

## Decisions

- The base image was moved from Debian 12 (bookworm) to Debian 13 (trixie): this removed both
  unfixed CRITICAL findings (zlib CVE-2023-45853, sqlite CVE-2025-7458) and 11 HIGH ones.
- Images are rebuilt from the latest base image on every build; when Debian publishes fixes,
  `make scan` picks them up automatically (findings with a fix fail the scan).
- Review this list when the base image is updated; remove entries that no longer appear.

## OWASP ZAP

`docs/security/zap-api-scan.md` — API scan of the gateway via its OpenAPI schema: 0 High,
0 Medium, 1 Low. The Low finding (missing `Cross-Origin-Resource-Policy`) was fixed in Nginx
right after the scan.
