# rax-net-snmp: a parallel-install net-snmp with DES-CBC privacy
# support, bundled with its own OpenSSL 1.0.2u so DES-CBC stays
# functional regardless of what the system OpenSSL 3.x provider
# stack decides to expose.
#
# Installed under /opt/rax-net-snmp so there's no collision with
# the stock net-snmp package. The caller (fire-engine's fe_snmp_cli)
# routes DES-requiring device sessions to /opt/rax-net-snmp/bin/snmpget
# and leaves everything else on the system snmpget.
#
# Intended lifetime: stop-gap until the last handful of DES-only
# switches (~8 Cisco Catalyst 2950s in the current fleet) retire.
# When they do, drop this package from the ansible fleet.

# The two upstream releases we bundle. Keep pinned; the whole point
# is a reproducible build against known-good sources.
%global netsnmp_version 5.9.1
%global openssl10_version 1.0.2u

# Install prefix. Everything (net-snmp + bundled openssl 1.0.2u)
# lives under here.
%global rax_prefix /opt/rax-net-snmp
%global rax_openssl %{rax_prefix}/openssl10

# rpmbuild's default policy tries to build a debug subpackage; net-snmp
# with our slimmed feature set has almost no debug info worth shipping
# and the debug package tries to reach into system paths we've bypassed.
%global debug_package %{nil}

# We don't want rpmbuild's automatic Requires: scan to add a hard
# dependency on our own bundled libcrypto.so.10 (it lives inside our
# own prefix; there's no external provider). Filter it out.
%global __provides_exclude_from ^%{rax_openssl}/lib/.*\\.so.*$
%global __requires_exclude ^libcrypto\\.so\\.1\\.0\\.0|^libssl\\.so\\.1\\.0\\.0

Name:           rax-net-snmp
Version:        %{netsnmp_version}
Release:        1%{?dist}
Summary:        net-snmp CLI tools with DES-CBC support (bundled OpenSSL 1.0.2u)
License:        BSD and OpenSSL
URL:            https://github.com/raxdcx/net-snmp

Source0:        https://downloads.sourceforge.net/project/net-snmp/net-snmp/%{netsnmp_version}/net-snmp-%{netsnmp_version}.tar.gz
Source1:        https://www.openssl.org/source/old/1.0.2/openssl-%{openssl10_version}.tar.gz

BuildRequires:  gcc make perl-core
BuildRequires:  perl-Text-Tabs+Wrap
BuildRequires:  zlib-devel elfutils-libelf-devel
BuildRequires:  diffutils file which

# System net-snmp is unaffected. This package coexists with it.
Conflicts:      %{name} < %{version}

%description
Parallel-installed net-snmp CLI utilities (snmpget, snmpset, snmpwalk,
snmpbulkget, snmpbulkwalk, snmptrap, snmptranslate, etc.) with the DES-CBC
SNMPv3 privacy protocol re-enabled. Bundles OpenSSL 1.0.2u under the same
prefix so DES-CBC stays functional regardless of the system OpenSSL 3.x
version.

All files install under %{rax_prefix}. The system net-snmp package is
untouched.

Intended as a stop-gap for legacy switches that require SNMPv3 with DES
privacy. When those devices retire, this package can be removed with no
impact on the rest of the fleet.


%prep
%setup -q -n net-snmp-%{netsnmp_version}
# Second tarball unpacks alongside the net-snmp source. We build
# openssl first from openssl-%{openssl10_version}/ then net-snmp
# from the parent.
tar xf %{SOURCE1}


# Stage dir for the bundled openssl 1.0.2u. rpmbuild wipes
# %%{buildroot} between %%build and %%install, so anything we
# install there in %%build would be lost. Stage under _builddir
# (which persists) and copy to buildroot in %%install.
%global openssl_stage %{_builddir}/openssl10-stage


%build
# --- Phase 1: build openssl 1.0.2u into the stage dir ---
pushd openssl-%{openssl10_version}
./Configure linux-%{_arch} shared no-ssl2 no-ssl3 \
    --prefix=%{rax_openssl} \
    --openssldir=%{rax_openssl}/ssl \
    -Wl,-rpath,%{rax_openssl}/lib
# openssl 1.0.2's Makefile is serial-only (its recursive make does
# not cooperate with GNU make's jobserver). ~90s serial is fine.
make
# install_sw = libs + headers + binary; skips the massive doc set.
# INSTALL_PREFIX is openssl 1.0.2's equivalent of DESTDIR.
rm -rf %{openssl_stage}
make INSTALL_PREFIX=%{openssl_stage} install_sw
popd

# --- Phase 2: build net-snmp against the staged openssl ---
# Link-time -L points at the stage path; RPATH points at the real
# target path so the binary finds openssl at runtime after install.
export CPPFLAGS="-I%{openssl_stage}%{rax_openssl}/include"
export LDFLAGS="-L%{openssl_stage}%{rax_openssl}/lib -Wl,-rpath,%{rax_openssl}/lib"

./configure \
    --prefix=%{rax_prefix} \
    --with-defaults \
    --with-openssl=%{openssl_stage}%{rax_openssl} \
    --enable-blumenthal-aes \
    --enable-ipv6 \
    --enable-ucd-snmp-compatibility \
    --disable-embedded-perl --without-perl-modules \
    --disable-agent \
    --disable-manuals \
    --disable-scripts

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
# net-snmp's `make install` re-links a couple of libraries as an
# installsubdirlibs step, which needs -lcrypto findable. Re-export
# the same LDFLAGS we used in %%build so those links resolve
# against the staged openssl.
export CPPFLAGS="-I%{openssl_stage}%{rax_openssl}/include"
export LDFLAGS="-L%{openssl_stage}%{rax_openssl}/lib -Wl,-rpath,%{rax_openssl}/lib"

make install DESTDIR=%{buildroot}

# Copy staged openssl into buildroot at the final location.
# `-a` preserves symlinks (libcrypto.so → libcrypto.so.1.0.0).
mkdir -p %{buildroot}%{rax_openssl}
cp -a %{openssl_stage}%{rax_openssl}/. %{buildroot}%{rax_openssl}/

# --- Trim what we don't want to ship ---
# We're a runtime-only utils package. No headers, no static libs,
# no libtool archives, no pkg-config, no daemon.
rm -rf %{buildroot}%{rax_prefix}/include
rm -rf %{buildroot}%{rax_prefix}/share/man
rm -rf %{buildroot}%{rax_prefix}/lib/pkgconfig
rm -rf %{buildroot}%{rax_openssl}/include
rm -rf %{buildroot}%{rax_openssl}/share
rm -rf %{buildroot}%{rax_openssl}/lib/pkgconfig
find %{buildroot}%{rax_prefix} -name "*.la" -delete
find %{buildroot}%{rax_prefix} -name "*.a"  -delete
find %{buildroot}%{rax_openssl} -name "*.a" -delete
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

# --- Trim what we don't need to ship ---
# We're a runtime-utils package. No headers, no static libs, no
# pkg-config files, no libtool archives, no man pages we opted out
# of, no perl bindings.
rm -rf %{buildroot}%{rax_prefix}/include
rm -rf %{buildroot}%{rax_prefix}/share/man
rm -rf %{buildroot}%{rax_openssl}/include
rm -rf %{buildroot}%{rax_openssl}/share
find %{buildroot}%{rax_prefix} -name "*.la" -delete
find %{buildroot}%{rax_prefix} -name "*.a" -delete
find %{buildroot}%{rax_openssl} -name "*.a" -delete
rm -rf %{buildroot}%{rax_prefix}/lib/pkgconfig

# net-snmp-config is a build-time helper for THIRD-party projects
# to link against net-snmp; we're not a devel package, so drop it.
rm -f %{buildroot}%{rax_prefix}/bin/net-snmp-config


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

%dir %{rax_openssl}
%dir %{rax_openssl}/bin
%dir %{rax_openssl}/lib
%dir %{rax_openssl}/ssl
%{rax_openssl}/bin/openssl
%{rax_openssl}/bin/c_rehash
%{rax_openssl}/lib/lib*.so.*
%{rax_openssl}/lib/lib*.so
%{rax_openssl}/lib/engines
%{rax_openssl}/ssl


%changelog
* Wed Jul 22 2026 Sam Warters <sam.warters@rackspace.com> - 5.9.1-1
- Initial parallel-install build; bundles OpenSSL 1.0.2u; DES-CBC
  re-enabled in net-snmp %{netsnmp_version}. Coexists with the stock
  net-snmp package. See raxdcx/net-snmp packaging-el9 branch for
  build details.
