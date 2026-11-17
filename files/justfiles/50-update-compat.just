# Stage the OS update, then update Flatpaks and Distrobox containers
update-all:
    #!/usr/bin/bash
    set -eu
    pkexec bootc upgrade
    flatpak update -y
    distrobox upgrade --all
