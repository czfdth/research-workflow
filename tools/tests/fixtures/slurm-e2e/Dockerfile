# A scripted stand-in for a Slurm login node, used by the opt-in end-to-end
# test (CCFA_SLURM_E2E=1). It runs a real sshd over a real port and answers
# sbatch/squeue/scancel through the scripts in ./bin. Those scripts are NOT a
# Slurm implementation: they exist so the client protocol, the SSH transport,
# the poll loop and the ledger receipt can be exercised without a cluster.
FROM alpine:3.20

# The default CDN is unreachable from some networks; pass
# --build-arg APK_MIRROR=mirrors.aliyun.com (or any Alpine mirror) to swap it.
ARG APK_MIRROR=dl-cdn.alpinelinux.org
RUN sed -i "s|dl-cdn.alpinelinux.org|${APK_MIRROR}|g" /etc/apk/repositories \
    && apk add --no-cache openssh bash

COPY bin/sbatch /usr/local/bin/sbatch
COPY bin/squeue /usr/local/bin/squeue
COPY bin/scancel /usr/local/bin/scancel
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /usr/local/bin/sbatch /usr/local/bin/squeue \
        /usr/local/bin/scancel /entrypoint.sh

EXPOSE 22
ENTRYPOINT ["/entrypoint.sh"]
