### Install Tools

sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y git ansible aptitude python3-pip python3-venv
sudo python3 -m pip install --upgrade packaging setuptools
sudo apt-get install -y docker.io
sudo systemctl start docker
sudo systemctl enable docker

git clone https://github.com/containernet/containernet.git
cd ~/containernet/ansible
sudo ansible-playbook -i "localhost," -c local install.yml
sudo python3 -m pip install -e . --no-build-isolation

### Install Ryu Controller

git clone https://github.com/faucetsdn/ryu.git
cd ryu
sed -i 's/ryu.hooks.save_orig()/# ryu.hooks.save_orig()/g' setup.py
sudo python3 -m pip install eventlet==0.30.2
sudo python3 -m pip install .
