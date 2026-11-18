# Filter for soloist -v (see soloist-run). Verbose lines: "10:17:04.464 I [f:347   ] text"
function save(   tmp) {
    tmp = OUT ".tmp"
    printf "{\"codec\": \"%s\", \"bitrate\": %d, \"rate\": %d}\n", codec, bitrate, rate > tmp
    close(tmp)
    system("mv " tmp " " OUT)
}
BEGIN { OUT = "/run/aroio/soloist-format" }
{
    gsub(/\033\[[0-9;]*m/, "")
    if ($0 !~ /^[0-9:.]+ [DIWE] \[f:[^]]*\] /) { print; fflush(); next }
    level = $2
    text = $0
    sub(/^[^]]*\] /, "", text)
    if (text ~ /^Opening sink for playback/) { codec = ""; bitrate = 0; rate = 0; next }
    if (text ~ /^    codec: /) { codec = text; sub(/^    codec: /, "", codec); next }
    if (text ~ /^    bitrate: /) { bitrate = text; gsub(/[^0-9]/, "", bitrate); next }
    if (text ~ /^    sample rate: /) { rate = text; gsub(/[^0-9]/, "", rate); if (codec != "") save(); next }
    # PulseAudio is used on purpose; Soloist tries PipeWire first every time
    if (text ~ /PipeWire|Pipewire/) next
    if (level == "W" || level == "E") { print level ": " text; fflush(); next }
    if (text ~ /^(soloist |client expires|api: |ready|restoring session|running|waiting for login|logged in|became|playing |paused |stopped|shutting down|error)/) { print text; fflush() }
}
