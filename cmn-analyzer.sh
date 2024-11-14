#!/bin/bash

: ${RELOAD_CMN:=no}

reload_cmn_driver_on_exit() {
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    if [ ${RELOAD_CMN} = no ]; then
        echo "this program may break cmn driver, unload and reload arm_cmn"
        echo "kernel module if it behaves abnormal, e.g., outputs all zero"
    else
        if lsmod | grep arm_cmn &> /dev/null; then
            echo "reload cmn driver on exit"
            if ! sudo rmmod arm_cmn; then
                echo "failed to unload cmn driver!"
            elif ! sudo modprobe arm_cmn; then
                echo "failed to load cmn driver!"
            else
                echo "done"
            fi
        fi
    fi
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
}

write_cmn=0
show_help=0
for arg in "$@"; do
    case ${arg} in
        info|stat|trace):
            write_cmn=1
            ;;
        -h|--help):
            show_help=1
            ;;
    esac
done
if [ ${write_cmn} = 1 ] && [ ${show_help} = 0 ]; then
    trap "reload_cmn_driver_on_exit" EXIT
fi

python3 "$(dirname "$0")/cmn-analyzer" "$@"
