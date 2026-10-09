#!/bin/bash
set -euo pipefail
exec ssh -o BatchMode=yes -o IdentitiesOnly=yes -i /Users/sapiece/.ssh/id_ed25519 -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/Users/sapiece/innovationProject/AstraLive/astralive-avatar-lab/connection/known_hosts -o ConnectTimeout=15 -p 20541 root@connect.bjb2.seetacloud.com "$@"
