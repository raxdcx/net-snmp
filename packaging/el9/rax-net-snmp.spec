# rax-net-snmp: a parallel-install net-snmp with DES-CBC privacy
# support, built against the system OpenSSL 3.x.
#
# Installed under /opt/rax-net-snmp so there's no collision with
# the stock net-snmp package. The caller (fire-engine's fe_snmp_cli)
# routes DES-requiring device sessions to /opt/rax-net-snmp/bin/snmpget
# and leaves everything else on the system snmpget.
#
# Why this package exists: Rocky 9 builds net-snmp with
# --disable-des, so the stock snmpget rejects `-x DES` during
# argument parsing. That is the whole reason for a parallel build.
# net-snmp enables DES by default, so this spec simply declines to
# disable it.
#
# It does NOT need a bundled OpenSSL. The low-level DES API
# (DES_key_sched, DES_ncbc_encrypt, DES_cbc_encrypt) is deprecated
# since OpenSSL 3.0 but is still exported and functional by
# libcrypto.so.3 — verified against 3.5.5 on Rocky 9.8, including a
# live SNMPv3/DES exchange with a Catalyst 2950. Earlier revisions of
# this package bundled OpenSSL 1.0.2u on the belief that the API had
# been removed; that was incorrect.
#
# Longer term, net-snmp master (5.10+) ports DES to the EVP API and
# loads the OpenSSL legacy provider, which removes reliance on the
# deprecated calls entirely. When 5.10 ships, bumping
# %%{netsnmp_version} is the durable follow-up.
#
# Intended lifetime: stop-gap until the last handful of DES-only
# switches (~8 Cisco Catalyst 2950s in the current fleet) retire.
# When they do, drop this package from the ansible fleet.

# The upstream release we build. Keep pinned; the whole point
# is a reproducible build against a known-good source.
%global netsnmp_version 5.9.1

# Install prefix.
%global rax_prefix /opt/rax-net-snmp

# rpmbuild's default policy tries to build a debug subpackage; net-snmp
# with our slimmed feature set has almost no debug info worth shipping
# and the debug package tries to reach into system paths we've bypassed.
%global debug_package %{nil}

Name:           rax-net-snmp
Version:        %{netsnmp_version}
Release:        2%{?dist}
Summary:        net-snmp CLI tools with DES-CBC support (system OpenSSL)
License:        BSD
URL:            https://github.com/raxdcx/net-snmp

Source0:        https://downloads.sourceforge.net/project/net-snmp/net-snmp/%{netsnmp_version}/net-snmp-%{netsnmp_version}.tar.gz

BuildRequires:  gcc make perl-core
BuildRequires:  perl-Text-Tabs+Wrap
BuildRequires:  openssl-devel
BuildRequires:  zlib-devel elfutils-libelf-devel
BuildRequires:  diffutils file which

# System net-snmp is unaffected. This package coexists with it.
Conflicts:      %{name} < %{version}

%description
Parallel-installed net-snmp CLI utilities (snmpget, snmpset, snmpwalk,
snmpbulkget, snmpbulkwalk, snmptrap, snmptranslate, etc.) with the DES-CBC
SNMPv3 privacy protocol left enabled, built against the system OpenSSL 3.x.

All files install under %{rax_prefix}. The system net-snmp package is
untouched.

Intended as a stop-gap for legacy switches that require SNMPv3 with DES
privacy. When those devices retire, this package can be removed with no
impact on the rest of the fleet.


%prep
%setup -q -n net-snmp-%{netsnmp_version}


%build
./configure \
    --prefix=%{rax_prefix} \
    --with-defaults \
    --with-openssl \
    --enable-des \
    --enable-blumenthal-aes \
    --enable-ipv6 \
    --enable-ucd-snmp-compatibility \
    --disable-embedded-perl --without-perl-modules \
    --disable-agent \
    --disable-manuals \
    --disable-scripts

# --enable-des is net-snmp's default, but state it explicitly: the
# entire purpose of this package is that DES stays compiled in, and
# an explicit flag means a future upstream default change can't
# silently turn this package into a duplicate of stock net-snmp.
#
# --enable-blumenthal-aes turns on AES-192-CFB / AES-256-CFB
# privacy protocols per draft-blumenthal-aes-usm-04. Without it,
# `snmpget -x` only accepts DES and (128-bit) AES; Cisco IOS
# commonly requires AES-256. Matches what Rocky ships.
#
# --enable-ipv6 gets pulled in by --with-defaults on modern
# net-snmp, but be explicit so a future default change doesn't
# silently drop it.
#
# --enable-ucd-snmp-compatibility installs a small set of
# tool-name symlinks matching pre-2001 UCD-SNMP names. Cheap
# insurance for any legacy ops script that still calls e.g.
# `snmpwalk` under an older alias.
#
# NOTE: don't --disable-mibs. That flag skips installing the
# MIB text files (SNMPv2-MIB.txt, IF-MIB.txt, ...) at
# %{rax_prefix}/share/snmp/mibs/. Without them, callers can only
# use numeric OIDs (`1.3.6.1.2.1.1.1.0`) — textual lookups like
# `sysDescr.0` fail with "Cannot find module (SNMPv2-MIB)". The
# MIB parser lib and -m/-M/-P CLI flags are unaffected by this
# flag either way.

make %{?_smp_mflags}


%install
make install DESTDIR=%{buildroot}

# --- Trim what we don't want to ship ---
# We're a runtime-only utils package. No headers, no static libs,
# no libtool archives, no pkg-config, no daemon.
rm -rf %{buildroot}%{rax_prefix}/include
rm -rf %{buildroot}%{rax_prefix}/share/man
rm -rf %{buildroot}%{rax_prefix}/lib/pkgconfig
find %{buildroot}%{rax_prefix} -name "*.la" -delete
find %{buildroot}%{rax_prefix} -name "*.a"  -delete
# We ship the versioned libs (.so.40, .so.40.1.0) and the unversioned
# symlinks (.so). The unversioned symlinks are useful for ad-hoc
# debugging and cost nothing since they're symlinks; keep them.

# Drop the snmpd daemon (we --disable-agent'd but snmptrapd is a
# separate app that gets built by default; strip it here).
rm -rf %{buildroot}%{rax_prefix}/sbin
rm -f  %{buildroot}%{rax_prefix}/bin/snmpinform  # symlink → snmptrap; harmless but unused
rm -rf %{buildroot}%{rax_prefix}/share/snmp/snmp_perl_trapd.pl

# net-snmp-config is a build-time helper for third-party projects
# to link against libnetsnmp; we're not shipping a devel package.
rm -f %{buildroot}%{rax_prefix}/bin/net-snmp-config
rm -f %{buildroot}%{rax_prefix}/bin/net-snmp-create-v3-user


%files
%dir %{rax_prefix}
%dir %{rax_prefix}/bin
%dir %{rax_prefix}/lib
%{rax_prefix}/bin/*
%{rax_prefix}/lib/lib*.so.*
%{rax_prefix}/lib/lib*.so
# share/snmp holds the runtime data (MIB stubs, etc.) net-snmp
# writes even with --disable-mibs. Ship the tree; it's small.
%{rax_prefix}/share


%changelog
* Tue Sep 15 2026 Sam Warters <sam.warters@rackspace.com> - 5.9.1-2
- Drop the bundled OpenSSL 1.0.2u and build against the system
  OpenSSL 3.x instead. The low-level DES API is deprecated since
  OpenSSL 3.0 but remains exported and functional in libcrypto.so.3,
  so the bundle was never required. Verified on Rocky 9.8 with
  OpenSSL 3.5.5 against a live Catalyst 2950 (C2950-I6K2L2Q4-M,
  IOS 12.1(22)EA14): SNMPv3 authPriv with DES returns sysDescr,
  sysUpTime and sysName identically to the 5.9.1-1 bundled build.
  Removes an end-of-life, unpatched OpenSSL from the package.
- Pass --enable-des explicitly rather than relying on the upstream
  default.
- De-duplicate the repeated trim block in %%install.

* Wed Jul 22 2026 Sam Warters <sam.warters@rackspace.com> - 5.9.1-1
- Initial parallel-install build; bundles OpenSSL 1.0.2u; DES-CBC
  re-enabled in net-snmp %{netsnmp_version}. Coexists with the stock
  net-snmp package. See raxdcx/net-snmp packaging-el9 branch for
  build details.
