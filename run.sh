#!/bin/bash

if ! ls /dev/armcmn:* > /dev/null 2>&1; then
    echo "cmnctl kernel module not loaded!"
    exit 1
fi

exec python3 "$(dirname "$0")/cmn-analyzer" "$@"
