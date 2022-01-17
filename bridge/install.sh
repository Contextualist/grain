#!/usr/bin/env bash
set -e
PREF=~/.local/bin
mkdir -p $PREF
rm -f $PREF/grain-bridge
echo "Downloading the executable..."
curl -fsSL https://github.com/Contextualist/grain/releases/latest/download/grain-bridge-linux-amd64 -o $PREF/grain-bridge
chmod +x $PREF/grain-bridge

cat > $PREF/grain-bridge-daemon <<EOF
#!/usr/bin/env bash
set -e
if ! screen -list | grep -q 'grain-bridge'; then
	screen -dmS grain-bridge
fi
if ! pgrep -x 'grain-bridge' > /dev/null; then
	screen -r grain-bridge -X stuff \$'grain-bridge\n'
fi
echo "The Bridge server is running in Screen session 'grain-bridge'."
echo "Dial/listen with this Bridge server by using one of the following URLs:"
IPs=\$(hostname -I)
for IP in \$IPs; do
        h=\$(host \$IP | rev | cut -d' ' -f1 | rev)
        h=\${h%?}
        echo -e "\tbridge://YOUR-KEY-NAME@\$h:9555"
        echo -e "\tbridge://YOUR-KEY-NAME@\$IP:9555"
done
EOF
chmod +x $PREF/grain-bridge-daemon

echo "Bridge server 'grain-bridge' has been installed at $PREF; please make sure that it is on your \$PATH."
echo "Use wrapper script 'grain-bridge-daemon' to start the server in background."
