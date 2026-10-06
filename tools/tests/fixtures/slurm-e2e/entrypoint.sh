#!/bin/sh
# Start sshd with the public key the test mounts read-only at /opt.
set -eu

ssh-keygen -A >/dev/null
mkdir -p /root/.ssh /work /var/ccfa-slurm
cp /opt/authorized_keys /root/.ssh/authorized_keys
chmod 700 /root/.ssh
chmod 600 /root/.ssh/authorized_keys

exec /usr/sbin/sshd -D -e -o PermitRootLogin=yes
