sudo systemctl enable --now squid

sudo iptables -I OUTPUT 1 -o lo -j ACCEPT
sudo iptables -I OUTPUT 2 -m owner --uid-owner proxy -p tcp --dport 443 -j ACCEPT
sudo iptables -I OUTPUT 3 -p tcp --dport 443 -j REJECT --reject-with tcp-reset

curl -I --connect-timeout 5 https://github.com
curl -I --connect-timeout 5 https://openai.com