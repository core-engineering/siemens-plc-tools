# Security

## Reporting a vulnerability

Please report security issues **privately**, not through a public issue.

Use GitHub's private vulnerability reporting on this repository — the **Security**
tab, then **Report a vulnerability**. It opens a discussion visible only to you
and the maintainers.

If that is unavailable, email the maintainer at the address on the project's
commits (`git log -1 --format=%ae`).

Please include what you found, how to reproduce it, and the affected version or
commit. There is no bounty; there is a reply.

## Reporting a confidentiality leak

This repository is public and the toolchain is developed against PLC programs
that are not. If you find a customer name, a contract or project code, a real
document reference or an absolute developer path committed here, **report it
privately through the same channel** rather than opening an issue that quotes it
— a public issue would republish exactly what needs removing.

`tests/test_no_confidential_references.py` guards against this and runs in CI,
and [CONTRIBUTING.md](CONTRIBUTING.md) explains the rules it enforces. Neither
catches everything.

Note what a fix can and cannot do. Removing such content requires rewriting
history and force-pushing, and **GitHub continues to serve unreachable objects by
commit SHA afterwards** unless GitHub Support is asked to purge them. So a
scrubbed repository is not the same as a scrubbed remote, and anyone who cloned
in the meantime keeps their copy. Report early; the cost of a leak grows with
time.

## Scope

This is engineering tooling for Siemens TIA Portal projects. Two areas deserve
attention from anyone reviewing it:

**The web servers have no authentication.** `plc code web` and `plc sim web`
serve their UI, docs and API from one application and bind to `127.0.0.1` by
default. `plc sim` **writes PLC tags**. Pass `--host 0.0.0.0` only on a network
you control. CORS is opt-in through `PLC_WEB_ALLOWED_ORIGINS`; unset installs no
middleware at all, which is what the bundled same-origin UI needs.

**The executor runs generated Python.** `plc code test` and `plc code transpile`
translate SCL into Python and execute it in-process. Treat a `.s7dcl` file from
an untrusted source the way you would treat a script from that source.

## Supported versions

Pre-1.0. Fixes land on `main`; there are no maintained release branches yet.
