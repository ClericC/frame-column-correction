#!/bin/bash
# Copyright (c) 2026 ClericC - MIT License - https://github.com/ClericC/frame-column-correction
# Column Correction service for the Steam Frame (runs as root).
# Applies a temperature-tracking VCOM offset on top of each panel's own factory VCOM value.
# Settings: /home/steamos/vcom-fix/vcom.conf (read as data only, never executed)
# Status:   cat /run/vcom-fix.state
CONF=/home/steamos/vcom-fix/vcom.conf
STATE=/run/vcom-fix.state
EST=/run/vcom-fix.est
DBG=/sys/kernel/debug
TZ_DIR=/sys/class/thermal
mountpoint -q $DBG || mount -t debugfs none $DBG
OFF_MIN=-10; OFF_MAX=45; TRIM_MAX=45
VCOM_LO=$((0x0100)); VCOM_HI=$((0x0400))   # plausible factory range; anything else is treated as unreadable

num() { grep -oE "^$1=-?[0-9]+" "$CONF" 2>/dev/null | head -1 | cut -d= -f2; }
clamp() { local v=$1; (( v < $2 )) && v=$2; (( v > $3 )) && v=$3; echo $v; }
cam_temp() {
  local s=0 c=0 z t
  for z in $TZ_DIR/thermal_zone*; do
    case "$(cat $z/type 2>/dev/null)" in camera*) t=$(cat $z/temp 2>/dev/null) && [ -n "$t" ] && s=$((s+t)) && c=$((c+1));; esac
  done
  [ $c -gt 0 ] && echo $((s/c))
}
interp() {
  local T=$3
  (( T < $4 )) && T=$4; (( T > $5 )) && T=$5
  local num=$(( ($2-$1)*(T-$4) )) den=$(( $5-$4 ))
  echo $(( $1 + (2*num + (num>=0?den:-den)) / (2*den) ))
}
# Factory VCOM values of this headset's panels, from the driver's copy of the panel memory (40 bytes per panel):
# bytes 13-14 = value for 108/120/144 Hz, bytes 15-16 = value for 72/80/90/96 Hz (same rule as the driver).
# Sets F120_0 F90_0 F120_1 F90_1, or returns 1 if they cannot be read.
read_factory() {
  local b
  b=($(cat "$1/panel_mfg_info" 2>/dev/null)) || return 1
  [ ${#b[@]} -ge 80 ] || return 1
  F120_0=$(( b[13]*256 + b[14] )); F90_0=$(( b[15]*256 + b[16] ))
  F120_1=$(( b[53]*256 + b[54] )); F90_1=$(( b[55]*256 + b[56] ))
  for v in $F120_0 $F90_0 $F120_1 $F90_1; do (( v >= VCOM_LO && v <= VCOM_HI )) || return 1; done
}
# Current refresh rate from the DRM state (mode line: "name": vrefresh clock ...); empty if unknown.
refresh_rate() {
  grep -hoE 'mode: "[^"]*": [0-9]+' $DBG/dri/*/state 2>/dev/null | grep -oE '[0-9]+$' | grep -v '^0$' | head -1
}

# Compatibility check, once per boot: the driver files must exist, and the factory VCOM values the driver itself
# prints in panel_info must match the raw panel-memory bytes this service reads. If the driver or its data layout
# changes (e.g. after a SteamOS update), they will not match and the service will not write anything.
compat_ok() {
  local f i b v
  for f in panel_info panel_mfg_info panel_write panel_available panel_vsync_to_photons_usec; do [ -e "$1/$f" ] || return 1; done
  b=($(cat "$1/panel_mfg_info" 2>/dev/null)); [ ${#b[@]} -ge 80 ] || return 1
  v=($(awk '/ (120|90) vcom[12] /{print $NF}' "$1/panel_info" 2>/dev/null)); [ ${#v[@]} -eq 8 ] || return 1
  local exp=(${b[13]} ${b[14]} ${b[15]} ${b[16]} ${b[53]} ${b[54]} ${b[55]} ${b[56]})
  for i in 0 1 2 3 4 5 6 7; do
    [[ ${v[$i]} =~ ^[0-9a-fA-F]+$ ]] || return 1
    (( 16#${v[$i]} == exp[$i] )) || return 1
  done
}

est=$(grep -oE '^-?[0-9]+$' $EST 2>/dev/null); last_t=$SECONDS; last_key=""; n=0; factory_ok=0; compat=""
KERNEL=$(uname -r)
while true; do
  CT=$(num COLD_TEMP); HT=$(num HOT_TEMP); LAG=$(num LAG_MIN)
  CL=$(num COLD_LEFT); CR=$(num COLD_RIGHT); HL=$(num HOT_LEFT); HR=$(num HOT_RIGHT)
  TL=$(num LEFT_TRIM); TR=$(num RIGHT_TRIM)
  EN=$(grep -oE '^ENABLED=[01]' "$CONF" 2>/dev/null | cut -d= -f2); EN=${EN:-0}
  CT=${CT:-34}; HT=${HT:-52}; CL=${CL:-0}; CR=${CR:-0}; HL=${HL:-0}; HR=${HR:-0}; LAG=${LAG:-22}
  TL=$(clamp ${TL:-0} -$TRIM_MAX $TRIM_MAX); TR=$(clamp ${TR:-0} -$TRIM_MAX $TRIM_MAX)
  (( HT <= CT )) && HT=$((CT+1)); (( LAG < 1 )) && LAG=1
  TAU=$((LAG*60))
  t=$(cam_temp)
  now=$SECONDS; dt=$((now-last_t)); last_t=$now; (( dt > TAU )) && dt=$TAU
  if [ -n "$t" ]; then
    if [ -z "$est" ]; then est=$((t*1000)); else est=$(( est + (t*1000-est)*dt/TAU )); fi
    echo $est > $EST
    e=$((est/1000))
    BL=$(interp $CL $HL $e $((CT*1000)) $((HT*1000))); BR=$(interp $CR $HR $e $((CT*1000)) $((HT*1000)))
  else
    BL=$HL; BR=$HR
  fi
  OL=$(clamp $((BL+TL)) $OFF_MIN $OFF_MAX); OR=$(clamp $((BR+TR)) $OFF_MIN $OFF_MAX)
  [ "$EN" = 0 ] && { OL=0; OR=0; }
  ERR=""; HZ=""
  P=$(dirname "$(find $DBG/dri -name panel_info 2>/dev/null | head -1)")
  if [ -f "$P/panel_write" ] && [ "$(cat "$P/panel_available" 2>/dev/null)" = 1 ]; then
    if [ $factory_ok != 1 ] && [ "$compat" != failed ]; then
      if compat_ok "$P"; then compat=ok; read_factory "$P" && factory_ok=1; else compat=failed; fi
    fi
    if [ "$compat" = failed ]; then
      ERR=unknown_driver       # never write to a driver this service was not made for
    elif [ $factory_ok = 1 ]; then
      HZ=$(refresh_rate)
      if [ -n "$HZ" ] && (( HZ >= 100 )); then FL=$F120_0; FR=$F120_1; else FL=$F90_0; FR=$F90_1; fi
      VL=$((FL+OL)); VR=$((FR+OR))
      key="$(cat "$P/panel_vsync_to_photons_usec" 2>/dev/null)|$HZ|$VL|$VR"
      if [ "$key" != "$last_key" ] || [ $n -ge 15 ]; then
        for id in 0 1; do
          [ $id = 0 ] && v=$VL || v=$VR
          echo "$id e5 1 07" > "$P/panel_write"
          printf "%d d5 2 %04x\n" $id $v > "$P/panel_write"
          echo "$id e5 1 00" > "$P/panel_write"
        done
        last_key="$key"; n=0
      fi
    else
      ERR=no_factory_values    # never write a guessed value
    fi
  else
    last_key=""
  fi
  { echo "enabled=$EN"
    echo "camera_mc=${t:-}"
    echo "display_est_mc=$([ -n "$est" ] && echo $((est/1000)))"
    echo "curve_left=$BL"; echo "curve_right=$BR"
    echo "trim_left=$TL"; echo "trim_right=$TR"
    echo "left=$OL"; echo "right=$OR"
    echo "refresh_hz=$HZ"
    echo "compat=${compat:-pending}"
    echo "kernel=$KERNEL"
    echo "version=$(cat /home/steamos/.local/lib/frame-vcom/VERSION 2>/dev/null)"
    [ $factory_ok = 1 ] && printf 'factory_left=0x%04x\nfactory_right=0x%04x\n' $FL $FR
    echo "error=$ERR"
    echo "updated=$(date +%s)"; } > $STATE.tmp && mv $STATE.tmp $STATE
  n=$((n+1)); sleep 2
done
