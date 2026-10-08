#!/bin/sh
# Virtual display for the bot's headed Chromium, exposed through noVNC so a captcha can be solved by hand.
rm -f /tmp/.X99-lock
Xvfb :99 -screen 0 1280x900x24 -nolisten tcp &
export DISPLAY=:99
sleep 1
x11vnc -display :99 -forever -shared -nopw -localhost -rfbport 5900 -quiet &
websockify --web /usr/share/novnc 6080 localhost:5900 &
exec python3 dashboard.py
