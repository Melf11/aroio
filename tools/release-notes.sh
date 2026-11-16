#!/bin/sh
# Release text for GitHub: tools/release-notes.sh VERSION "news; separated; by semicolons"
# The bullet lines become the notes in the Aroio app (aroiod/updates.py, notes_from_body).
V="$1"
echo "## Neu in $V"
echo
printf '%s\n' "$2" | tr ';' '\n' | sed 's/^ *//; s/ *$//' | sed -n '/./s/^/- /p'
echo
echo "## Installation"
echo
echo "- **Update:** Aroios mit AroioOS-Neubau finden das Update selbst (Einstellungen › Updates)."
echo "- **SD-Karte:** \`aroio-$V-sdcard.img.xz\` mit dem Raspberry Pi Imager schreiben. Gerät und Soundkarte wählt man beim ersten Start in der App."
echo
echo "Privater Neubau ohne Gewähr, siehe README."
