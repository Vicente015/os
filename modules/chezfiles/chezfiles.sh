#!/usr/bin/env bash

# Tell build process to exit if there are any errors.
set -euo pipefail

echo "Checking if /usr/bin/chezmoi exists"
if [ -e /usr/bin/chezmoi ]; then
	echo "chezmoi binary already exists, no need to redownload it"
else
	echo "Checking if curl is installed and executable at /usr/bin/curl"
	if [ -x /usr/bin/curl ]; then
		echo "Downloading chezmoi binary from the latest Github release"
		/usr/bin/curl -Ls https://github.com/twpayne/chezmoi/releases/latest/download/chezmoi-linux-amd64 -o /usr/bin/chezmoi
		echo "Ensuring chezmoi is executable"
		/usr/bin/chmod 755 /usr/bin/chezmoi
	else
		echo "ERROR: curl could not be found in /usr/bin/."
		echo "Please make sure curl is installed on the system you are building your image."
		exit 1
	fi
fi

nu $MODULE_DIRECTORY/chezfiles/chezfiles.nu --recipe $1 --module-directory $MODULE_DIRECTORY --config-directory $CONFIG_DIRECTORY