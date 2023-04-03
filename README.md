# Wallbox integration for Domoticz.

## Installation

Assuming Domoticz is installed in ~/domoticz:

```
cd ~/domoticz/plugins
git clone https://github.com/lokonli/domoticz-wallbox.git wallbox
cd wallbox
sudo pip install -r requirements.txt
sudo systemctl restart domoticz.service
```

## Update

To update the plugin to the latest version:
```
cd ~/domoticz/plugins/wallbox
git pull
sudo systemctl restart domoticz.service
```

## Configuration

In Domoticz -> Hardware select the Wallbox plugin.
Configure email and password as registered on https://my.wallbox.com/

## Usage
The plugin will create several Domoticz devices for each Wallbox charger you own.
