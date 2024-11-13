#!/bin/bash

: ${RELOAD_CMN:=no}

reload_cmn_driver_on_exit() {
    if [ ${RELOAD_CMN} = no ]; then
        echo "NOTE: this program may break cmn driver, reload arm_cmn driver" \
             "if it behaves abnormal, e.g., outputs all zero"
    else
        if lsmod | grep arm_cmn &> /dev/null; then
            echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
            echo "reload cmn driver on exit"
            if ! sudo rmmod arm_cmn; then
                echo "failed to unload cmn driver!"
            elif ! sudo modprobe arm_cmn; then
                echo "failed to load cmn driver!"
            else
                echo "done"
            fi
            echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        fi
    fi
}

trap "reload_cmn_driver_on_exit" EXIT
python3 "$(dirname "$0")/cmn-analyzer" "$@"
