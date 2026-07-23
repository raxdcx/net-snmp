#!/bin/bash
# Build the rax-net-snmp RPM inside a Rocky 9 container.
#
# Layout:
#   $PWD                 mounted at /work
#   $PWD/rax-net-snmp.spec  the spec file
#   $PWD/sources/        cached upstream tarballs (source0/source1)
#   $PWD/rpms/           output RPMs land here
set -euo pipefail

: "${IMAGE:=rockylinux:9}"
: "${SPEC:=rax-net-snmp.spec}"

mkdir -p sources rpms

# Fetch sources if not already cached
[ -f sources/net-snmp-5.9.1.tar.gz ] || \
    curl -sSLo sources/net-snmp-5.9.1.tar.gz \
        https://downloads.sourceforge.net/project/net-snmp/net-snmp/5.9.1/net-snmp-5.9.1.tar.gz
[ -f sources/openssl-1.0.2u.tar.gz ] || \
    curl -sSLo sources/openssl-1.0.2u.tar.gz \
        https://www.openssl.org/source/old/1.0.2/openssl-1.0.2u.tar.gz

docker run --rm --platform linux/amd64 \
    -v "$PWD":/work \
    -w /work \
    "$IMAGE" bash -c '
set -euo pipefail
# Base image ships curl-minimal; asking for `curl` here triggers
# a conflict and dnf refuses to install anything. Skip curl — we
# only need it inside the container if we were fetching sources
# there, but they are already staged under /work/sources.
dnf install -y --setopt=install_weak_deps=False \
    rpm-build rpmdevtools \
    gcc make perl-core perl-Text-Tabs+Wrap \
    zlib-devel elfutils-libelf-devel \
    diffutils file which \
    tar gzip patch

# Set up a private rpmbuild tree under /work so the output lands
# in a place we mounted from the host. Override _topdir via
# --define so we don not depend on the default $HOME/rpmbuild path.
TOPDIR=/work/.rpmbuild
mkdir -p "$TOPDIR"/{BUILD,BUILDROOT,RPMS,SRPMS,SOURCES,SPECS}
cp /work/sources/* "$TOPDIR/SOURCES/"
cp /work/'"$SPEC"' "$TOPDIR/SPECS/"

rpmbuild --define "_topdir $TOPDIR" -bb "$TOPDIR/SPECS/'"$SPEC"'"

# Publish the resulting RPMs to a stable output path
cp -v "$TOPDIR"/RPMS/*/*.rpm /work/rpms/
'
echo
echo "=== output ==="
ls -la rpms/
