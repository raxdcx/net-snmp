# rax-net-snmp — Rocky/RHEL 9 packaging

Parallel-install net-snmp CLI utilities with DES-CBC left enabled,
built against the system OpenSSL 3.x. Installs under
`/opt/rax-net-snmp/` so it coexists with the system `net-snmp`
package.

## Why this exists

Rocky 9 ships `net-snmp-5.9.1-<N>.el9` built with `--disable-des`,
so the stock `snmpget` rejects `-x DES` during argument parsing:

```
$ /usr/bin/snmpget -v3 -l authPriv -x DES ...
Invalid privacy protocol specified after -3x flag: DES
```

That is the entire reason for a parallel build. net-snmp enables
DES by default, so this package simply declines to disable it.

No bundled OpenSSL is required. The low-level DES API that
`snmplib/scapi.c` calls — `DES_key_sched`, `DES_ncbc_encrypt`,
`DES_cbc_encrypt` — is **deprecated since OpenSSL 3.0 but still
exported and functional** by `libcrypto.so.3`:

```
$ nm -D --defined-only /lib64/libcrypto.so.3 | grep DES_key_sched
0000000000151d40 T DES_key_sched@@OPENSSL_3.0.0
```

The build emits `'DES_key_sched' is deprecated: Since OpenSSL 3.0`
warnings and works.

Earlier revisions of this package (5.9.1-1) bundled OpenSSL 1.0.2u
on the belief that these functions had been removed in OpenSSL 3.5.
That was incorrect, and the bundle has been dropped as of 5.9.1-2.

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
└── share/snmp/
    └── (runtime data files)
```

The binaries link the system `libcrypto.so.3` / `libssl.so.3`, so
there is no bundled crypto tree and no `RPATH` or
`LD_LIBRARY_PATH` machinery.

## Building locally

Requires Docker (or podman aliased as docker). Runs everything
inside a Rocky 9 container so the build is reproducible.

```
cd packaging/el9
./build.sh
```

Output RPM lands at `packaging/el9/rpms/rax-net-snmp-*.rpm`.

Subsequent builds reuse the cached tarball at
`packaging/el9/sources/`.

## Versioning

Package version tracks the net-snmp release we build. The
`Release:` field bumps for packaging changes that don't advance
net-snmp itself:

- `rax-net-snmp-5.9.1-1.el9.x86_64.rpm` — first build, bundled
  OpenSSL 1.0.2u.
- `rax-net-snmp-5.9.1-2.el9.x86_64.rpm` — same net-snmp, bundle
  dropped, system OpenSSL 3.x.
- `rax-net-snmp-5.10-1.el9.x86_64.rpm` — net-snmp 5.10, if we
  move (see below).

## Verification

5.9.1-2 was validated against a live DES-only device —
`f22-9-8it.iad3` in staging, a `C2950-I6K2L2Q4-M` running IOS
`12.1(22)EA14` — using SNMPv3 `authPriv` with SHA auth and DES
privacy. `sysDescr`, `sysUpTime` and `sysName` all returned
identically to the 5.9.1-1 bundled build, and the stock system
`snmpget` rejected the same request. The device refuses AES
(`Unknown Report message`), confirming DES is the only privacy
protocol it accepts.

## Related upstream work

Both contributions previously wanted here have now **landed on
net-snmp master** (targeting 5.10):

1. `b28cc6d96` — `libsnmp: Load OpenSSL 3.0+ providers`, which
   calls `OSSL_PROVIDER_load(NULL, "legacy")` in `sc_init()`.
2. `768dd0922` — `libsnmp: Port DES support to OpenSSL EVP API`.
   (`a2fd47857` removes the now-stale `sc_shutdown()` declaration
   and is needed alongside them.)

Master built from those was also verified against the same
Catalyst 2950 and works. It carries **zero** references to the
deprecated low-level `DES_*` symbols, routing DES through EVP plus
the legacy provider instead — confirmed by the fact that emptying
`OPENSSL_MODULES` (so `legacy.so` cannot load) makes master fail
with `USM encryption error` while 5.9.1 is unaffected.

That makes moving to 5.10 the durable follow-up once it is
released: it removes reliance on a deprecated API rather than
merely tolerating it. Backporting the three commits to 5.9.1 is
possible but only partly effective — 15 low-level `DES_*` call
sites remain in the 5.9.1 tree, so patched 5.9.1 still rides the
deprecated path.

See net-snmp/net-snmp#294 and #518 for the discussion and test
results.
