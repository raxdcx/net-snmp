# rax-net-snmp — Rocky/RHEL 9 packaging

Parallel-install net-snmp CLI utilities with DES-CBC re-enabled,
bundled with OpenSSL 1.0.2u. Installs under `/opt/rax-net-snmp/`
so it coexists with the system `net-snmp` package.

## Why this exists

Rocky 9 ships `net-snmp-5.9.1-<N>.el9` built with `--disable-des`
against OpenSSL 3.x. On OpenSSL 3.5+, even loading the legacy
provider is not enough to restore the low-level `DES_*` API that
net-snmp's `snmplib/scapi.c` calls (the direct DES functions in
`openssl/des.h` have been retired, not merely deprecated).

Rewriting the DES paths in `scapi.c` to use the modern EVP API
would be the proper upstream fix, but is out of scope for
"unblock a handful of legacy switches before they retire."

Instead: build our own net-snmp with `--disable-des` removed, and
bundle it with OpenSSL 1.0.2u — where DES-CBC is a first-class
cipher and no provider machinery is involved. The result is an
`snmpget/snmpset/snmpwalk` at `/opt/rax-net-snmp/bin/` that can
still speak SNMPv3 with `-x DES`.

## Consumers

The primary consumer is fire-engine's `fe_snmp_cli`, which routes
sessions to `/opt/rax-net-snmp/bin/snmpget` for devices whose
capability list says they need DES (currently the Cisco Catalyst
2950 fleet). Everything else stays on the system `snmpget`.

## Layout

```
/opt/rax-net-snmp/
├── bin/
│   ├── snmpget snmpset snmpwalk snmpbulkget snmpbulkwalk
│   ├── snmptrap snmptranslate snmptable snmpstatus snmpusm ...
│   └── (~16 utils)
├── lib/
│   └── libnetsnmp.so.40  libnetsnmpagent.so.40  ...
├── share/snmp/
│   └── (runtime data files)
└── openssl10/
    ├── bin/openssl bin/c_rehash
    ├── lib/libcrypto.so.1.0.0  lib/libssl.so.1.0.0  lib/engines/
    └── ssl/openssl.cnf ssl/certs/ ssl/private/
```

The binaries carry `RPATH=/opt/rax-net-snmp/openssl10/lib`, so no
`LD_LIBRARY_PATH` wrapper is needed at runtime.

## Building locally

Requires Docker (or podman aliased as docker). Runs everything
inside a Rocky 9 container so the build is reproducible.

```
cd packaging/el9
./build.sh
```

Output RPM lands at `packaging/el9/rpms/rax-net-snmp-*.rpm`.

First build takes ~4 minutes (dnf deps + openssl compile serial +
net-snmp compile parallel). Subsequent builds reuse the cached
tarballs at `packaging/el9/sources/`.

## Versioning

Package version tracks the net-snmp release we bundle. The
`Release:` field's `.raxN` suffix bumps for packaging changes
that don't advance net-snmp itself:

- `rax-net-snmp-5.9.1-1.el9.x86_64.rpm` — first build.
- `rax-net-snmp-5.9.1-2.el9.x86_64.rpm` — same net-snmp, spec
  fix.
- `rax-net-snmp-5.9.5-1.el9.x86_64.rpm` — net-snmp 5.9.5, if
  we ever move.

## Bundled OpenSSL

OpenSSL 1.0.2u (final release of the 1.0.2 line, 2019-12-20) is
End-of-Life upstream and receives no CVE fixes. The security
tradeoff for this package is:

- The bundled libcrypto/libssl are *only* used by our
  `/opt/rax-net-snmp/bin/*` binaries. They are not exposed to
  the system's dynamic linker default search path.
- These binaries only ever *initiate* outbound SNMPv3 sessions
  to devices we own. They do not accept inbound cryptographic
  input from anywhere, so the risk surface is limited to the
  device side of a session we started.

If that changes (e.g. we ever host an snmptrap listener from
this binary), reassess. Otherwise, the package should live
until the last DES-only device retires.

## Related upstream work

net-snmp does not currently offer a supported story for DES on
OpenSSL 3.5+. Two upstream contributions would fix the root
cause and let us retire this package early:

1. `OSSL_PROVIDER_load(NULL, "legacy")` at library init when
   built against OpenSSL 3.x.
2. Rewrite the DES paths in `snmplib/scapi.c` to use the EVP
   API (mirrors the AES path already in the same file).

See net-snmp/net-snmp#294 and #518 for the ongoing discussion.
