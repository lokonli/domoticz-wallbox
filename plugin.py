# Plugin for Wallbox
#
# Author: lokonli
#
"""
<plugin key="Wallbox" name="Wallbox" author="lokonli" version="0.0.1" wikilink="https://github.com/lokonli/domoticz-wallbox" externallink="https://github.com/lokonli/domoticz-wallbox">
    <description>
        <h2>Wallbox plugin for Domoticz</h2><br/>
        <h3>Features</h3>
        <ul style="list-style-type:square">
            <li>Automatic detection of all your Wallbox chargers</li>
        </ul>
        <h3>Devices</h3>
        For each Wallbox charger the following devices will be created:
        <ul style="list-style-type:square">
            <li>Charger Lock - To Lock and Unlock the Wallbox charger</li>
            <li>Charger Status - Device to show the actual Wallbox status (read-only)</li>
            <li>Resume charging - Push On button to resume charging</li>
            <li>Pause charging - Push On button to pause charging</li>
            <li>Charging current - Device to show the actual charging current</li>
            <li>Charging Start Stop - Device to start/stop charging. </li>
            <li>Session Energy - Total Energy charged during the last session. </li>
        </ul>
        <h3>Configuration</h3>
        Fill in your Wallbox email and password. 
    </description>
    <params>
        <param field="Username" label="Username:" width="200px" required="true" default="name@gmail.com"/>
        <param field="Password" label="Password" width="200px" required="true" default="" password="true"/>
        <param field="Mode6" label="Debug" width="150px">
            <options>
                <option label="None" value="0"  default="true" />
                <option label="Python Only" value="2"/>
                <option label="Basic Debugging" value="62"/>
                <option label="Basic+Messages" value="126"/>
                <option label="Queue" value="128"/>
                <option label="Connections Only" value="16"/>
                <option label="Connections+Queue" value="144"/>
                <option label="All" value="-1"/>
            </options>
        </param>
    </params>
</plugin>
"""
import DomoticzEx as Domoticz
from wallbox import Wallbox, Statuses
import time
import datetime
import queue
import threading
import json

def dumpJson(name, msg):
    messageJson = json.dumps(msg,
                skipkeys = True,
                allow_nan = True,
                indent = 6)
    Domoticz.Debug('Message: '+name )
    Domoticz.Debug(messageJson)

class WallboxPlugin:
    enabled = False
    DEVICELOCK = 1
    DEVICESTATUS = 2
    DEVICERESUME = 3
    DEVICEPAUSE = 4
    DEVICECURRENT = 5
    DEVICESTARTSTOP = 6
    DEVICEENERGY = 7


    def __init__(self):
        self.messageQueue = queue.Queue()
        self.countDownInit = 3 #Update devices every countDownInit * 10 seconds
        self.countDown = 1

    def wbThread(self):
        Domoticz.Log('Start Wallbox thread')
        self.wallbox = Wallbox(Parameters["Username"], Parameters["Password"])
        w=self.wallbox
        self.authenticated = False
        try:
            w.authenticate()
        except:
            Domoticz.Error('Wallbox authentication problem. Check username password')
            return
        
        self.authenticated = True
        if self.debugging:
            self.debugpy.breakpoint()

        chargerList = w.getChargersList()
        if len(chargerList):
            for chargerId in chargerList:
                self.initDevices(chargerId)
        else:
            Domoticz.Log('No charger configured.')
        
        Domoticz.Debug("Entering message handler")
        while True:
            try:
                Message = self.messageQueue.get(block=True)
                if self.debugging:
                    self.debugpy.breakpoint()

                if Message is None:
                    Domoticz.Debug("Exiting message handler")
                    self.messageQueue.task_done()
                    break

                dumpJson('Message', Message)
                try:
                    w.authenticate()
                except:
                    Domoticz.Error('Wallbox authentication problem. Check username password')
                    raise("Authentication problem")


                if (Message["Type"] == "Update"):
                    for chargerId in chargerList:
                        self.updateDevices(str(chargerId))                    
                elif (Message["Type"] == "Command"):
                    deviceID = Message["DeviceID"]
                    try: 
                        if Message["Unit"]==1:
                            if Message["Command"]=='Off':
                                res=w.unlockCharger(deviceID)
                            else:
                                res=w.lockCharger(deviceID)
                            dumpJson('Result', res)
                            try:
                                locked = res["data"]["chargerData"]["locked"]
                                myUnit = Devices[deviceID].Units[1]       
                                myUnit.nValue = locked
                                myUnit.Update(Log=True)

                            except:
                                Domoticz.Debug('Unexpected response data, no locked info')
                        elif Message["Unit"]==3: #Resume
                            res=w.resumeChargingSession(deviceID)
                            dumpJson('Result', res)
                        elif Message["Unit"]==4: #Pause
                            res=w.pauseChargingSession(deviceID)
                            dumpJson('Result', res)
                        elif Message["Unit"]==6: #Charging start stop
                            chargerStatus = w.getChargerStatus(deviceID)
                            dumpJson('Status: ', chargerStatus)
                            chargingStatus = Statuses(chargerStatus["status_id"])
                            stateUpdated = False
                            if Message["Command"]=='On':
                                if chargingStatus== Statuses.LOCKED:
                                    res=w.unlockCharger(deviceID)
                                    dumpJson('Unlock: ', res)
                                    time.sleep(2)
                                    chargerStatus = w.getChargerStatus(deviceID)
                                    dumpJson('Status: ', chargerStatus)
                                    chargingStatus = Statuses(chargerStatus["status_id"])
                                    stateUpdated = True
                                if chargingStatus != Statuses.CHARGING:
                                    res=w.resumeChargingSession(deviceID)
                                    dumpJson('Resume: ', res)
                                    stateUpdated = True
                            else:
                                if chargingStatus == Statuses.CHARGING:
                                    res=w.pauseChargingSession(deviceID)
                                    dumpJson('Pause: ', res)
                                    stateUpdated = True
                            if stateUpdated:
                                time.sleep(2)
                                self.updateDevices(deviceID)
                    except Exception as err:
                        Domoticz.Error("Command error: "+str(err))
                elif (Message["Status"] == "Error"):
                    Domoticz.Status("handleMessage: '"+Message["Text"]+"'.")
                    #if 401 client error, then probably authorization expired.
                elif (Message["Type"] == "Error"):
                    Domoticz.Error("handleMessage: '"+Message["Text"]+"'.")
                self.messageQueue.task_done()

            except Exception as err:
                Domoticz.Error("handleMessage: "+str(err))

    def onStart(self):
        self.debugging=False
        if Parameters["Mode6"] == "-1":
            Domoticz.Debugging(1)
            Domoticz.Log("Debugger started, use '0.0.0.0 5678' to connect")
            import debugpy
            self.debugging=True
            self.debugpy=debugpy
            debugpy.listen(("0.0.0.0", 5678))
##            debugpy.wait_for_client()
            time.sleep(10)
            debugpy.breakpoint()
        else:
            Domoticz.Log("onStart called")
        if Parameters["Mode6"] != "0":
            Domoticz.Debugging(int(Parameters["Mode6"]))
            DumpConfigToLog()
        
        self.messageThread = threading.Thread(name="QueueThread", target=WallboxPlugin.wbThread, args=(self,))
        self.messageThread.start()
        Domoticz.Log('Thread started')
        heartBeat = 10     #heartBeat can be changed in debug session
        Domoticz.Heartbeat(heartBeat)
    
    def initDevices(self, chargerId):

        defaultUnits = [
            { #1
                "Unit": self.DEVICELOCK,
                "Name": "Charger Lock",
                "Type": 244,
                "Switchtype": 19,
            },
            { #2
                "Unit": self.DEVICESTATUS,
                "Name": "Charger Status",
#                "TypeName": "Selector Switch",
                "Type": 243,
                "Subtype": 19,
#                "Options": {
#                    "LevelActions": "|| ||",
#                    "LevelNames": "Waiting|Charging|Ready|Paused|Scheduled|Discharging|Error|Disconnected|Locked|Updating",
#                    "LevelOffHidden": "false",
#                    "SelectorStyle": "1"
 #               },
#                "Type": 244,
#                "Subtype": 62,
#                "Switchtype": 18,
            },
            { #3
                "Unit": self.DEVICERESUME,
                "Name": "Resume Charging",
                "Type": 244,
                "Switchtype": 9,
            },
            { #4
                "Unit": self.DEVICEPAUSE,
                "Name": "Pause Charging",
                "Type": 244,
                "Switchtype": 9,
            },
            { #5
                "Unit": self.DEVICECURRENT,
                "Name": "Charging current",
                "Type": 243,
                "Subtype": 23,
            },
            { #6
                "Unit": self.DEVICESTARTSTOP,
                "Name": "Charging start stop",
                "Type": 244,
                "Switchtype": 0,
            },
            { #7
                "Unit": self.DEVICEENERGY,
                "Name": "Session Energy",
                "Type": 243,
                "Subtype": 33,
                "Switchtype": 0,
                "Options": {
                          "DisableLogAutoUpdate" : "true",
                          "AddDBLogEntry" : "true",
#                          "Custom": "1;kWh"
                    }
            },
        ]
        id=str(chargerId)
        try:
            device=Devices[id]
            for defaultUnit in defaultUnits:
                unit = defaultUnit["Unit"]
                if unit in device.Units:
                    myUnit = device.Units[unit]
                else:
                    myUnit = Domoticz.Unit(DeviceID=id, Used=1, **defaultUnit)
                    myUnit.Create()
        except:
            for defaultUnit in defaultUnits:
                myUnit = Domoticz.Unit(DeviceID=id, Used=1, **defaultUnit)
                myUnit.Create()
        #Filling historic data doesn't work unfortunately
        #self.fillHistoricEnergyData(chargerId)

    def fillHistoricEnergyData(self, chargerId):
        #Loads all session data, and send daily sum to Domoticz database
        #Doesn't work, unfortunately ...
        Domoticz.Debug('Fill historic data')
        if self.debugging:
            self.debugpy.breakpoint()
        device = Devices[str(chargerId)].Units[self.DEVICEENERGY]
        w=self.wallbox
        endDate = datetime.datetime.now()
        startDate = datetime.datetime(1990,1,1)
        sessionList = w.getSessionList(chargerId, startDate, endDate)
        currentDate=""
        totalEnergy = 0
        previousEnergy = 0
        for session in reversed(sessionList["data"]):
            if session["type"]=="charger_log_session":
                sessionDate = datetime.datetime.fromtimestamp(session["attributes"]["start"]).date()
                if currentDate=="":
                    currentDate=sessionDate
                if currentDate != sessionDate:
                    delta=totalEnergy - previousEnergy
                    previousEnergy = totalEnergy
                    device.nValue = 0
                    device.sValue = f"{totalEnergy};{delta};{sessionDate}"
                    Domoticz.Debug(device.sValue)
                    device.Update(Log=True)
                    sessionDate=currentDate
                totalEnergy=totalEnergy+int(session["attributes"]["energy"]*1000)

        delta=totalEnergy - previousEnergy
        device.sValue = f"{totalEnergy};{delta};{currentDate}"
        Domoticz.Debug(device.sValue)
        device.Update(Log=True)
        Domoticz.Debug(f"Total energy {totalEnergy}")



    def updateDevices(self, chargerId):
        chargerStatus = self.wallbox.getChargerStatus(chargerId)

        dumpJson("Status: ", chargerStatus)

        ## 1: Charger Lock
        lockStatus = "Locked" if chargerStatus["config_data"]["locked"] else "Unlocked"
        myUnit = Devices[chargerId].Units[self.DEVICELOCK]
        Domoticz.Debug('Current lock status: '+str(myUnit.nValue))
        if myUnit.nValue != chargerStatus["config_data"]["locked"]:
            myUnit.nValue = chargerStatus["config_data"]["locked"]
            myUnit.Update(Log=True)
            Domoticz.Debug('Lock status changed to: ' + str(chargerStatus["config_data"]["locked"]))
        
        ## 2: Charger status
        myUnit = Devices[chargerId].Units[self.DEVICESTATUS]
        chargingStatus = Statuses(chargerStatus["status_id"]).name.capitalize()
        if myUnit.sValue != chargingStatus:
            myUnit.sValue = chargingStatus
            myUnit.Update(Log=True)
            Domoticz.Debug('Charging status changed to: ' + chargingStatus)

        ## 5: Charging current
        myUnit = Devices[chargerId].Units[self.DEVICECURRENT]
        chargingCurrent = str(round(chargerStatus["charging_power"],1))
        sValue = f"{chargingCurrent};{chargingCurrent}"
        if myUnit.sValue != sValue:
            myUnit.sValue = sValue
            myUnit.Update(Log=True)
            Domoticz.Debug('Charging current changed to: ' + chargingCurrent)
        
        ## 6: Charging stop start
        myUnit = Devices[chargerId].Units[self.DEVICESTARTSTOP]
        chargingCmd = 1 if chargingStatus=='CHARGING' else 0
        if myUnit.nValue != chargingCmd:
            myUnit.nValue = chargingCmd
            myUnit.Update(Log=True)
            Domoticz.Debug('Charging status changed to: ' + str(chargingCmd))

        #added_energy
        ## 7: Energy
        myUnit = Devices[chargerId].Units[self.DEVICEENERGY]
        addedEnergy = int(chargerStatus["added_energy"] * 1000)
#        addedEnergy = chargerStatus["added_energy"]
        sessionDate = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        sValue = f"{addedEnergy};{addedEnergy}"
        if myUnit.sValue != sValue:
            myUnit.sValue = sValue
            myUnit.nValue = 0
            myUnit.Update()
            Domoticz.Debug('Added Energy changed to: ' + str(sValue))


    def onStop(self):
        Domoticz.Log("onStop called")
        # signal queue thread to exit
        self.messageQueue.put(None)
        Domoticz.Log("Clearing message queue...")
        self.messageQueue.join()

        # Wait until queue thread has exited
        Domoticz.Log("Threads still active: "+str(threading.active_count())+", should be 1.")
        while (threading.active_count() > 1):
            for thread in threading.enumerate():
                if (thread.name != threading.current_thread().name):
                    Domoticz.Log("'"+thread.name+"' is still running, waiting otherwise Domoticz will abort on plugin exit.")
            time.sleep(1.0)
        if self.debugging:
            import pydevd
            pydevd.stoptrace()
        

    def onConnect(self, Connection, Status, Description):
        Domoticz.Log("onConnect called")

    def onMessage(self, Connection, Data):
        Domoticz.Log("onMessage called")

    def onCommand(self, DeviceID, Unit, Command, Level, Color):
        Domoticz.Log("onCommand called for Device " + str(DeviceID) + " Unit " + str(Unit) + ": Parameter '" + str(Command) + "', Level: " + str(Level))
        self.messageQueue.put(
            {"Type":"Command", 
             "DeviceID": DeviceID,
             "Unit": Unit,
             "Command": Command,
             "Level": Level
            })

    def onNotification(self, Name, Subject, Text, Status, Priority, Sound, ImageFile):
        Domoticz.Log("Notification: " + Name + "," + Subject + "," + Text + "," + Status + "," + str(Priority) + "," + Sound + "," + ImageFile)

    def onDisconnect(self, Connection):
        Domoticz.Log("onDisconnect called")

    def onHeartbeat(self):
        Domoticz.Log("onHeartbeat called")
        self.countDown = self.countDown-1
        if self.countDown <= 0:
            self.countDown = self.countDownInit
            self.messageQueue.put(
                {"Type":"Update", 
                })


global _plugin
_plugin = WallboxPlugin()

def onStart():
    global _plugin
    _plugin.onStart()

def onStop():
    global _plugin
    _plugin.onStop()

def onConnect(Connection, Status, Description):
    global _plugin
    _plugin.onConnect(Connection, Status, Description)

def onMessage(Connection, Data):
    global _plugin
    _plugin.onMessage(Connection, Data)

def onCommand(DeviceID, Unit, Command, Level, Color):
    global _plugin
    _plugin.onCommand(DeviceID, Unit, Command, Level, Color)

def onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile):
    global _plugin
    _plugin.onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile)

def onDisconnect(Connection):
    global _plugin
    _plugin.onDisconnect(Connection)

def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()

# Generic helper functions
def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug( "'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for DeviceName in Devices:
        Device = Devices[DeviceName]
        Domoticz.Debug("Device ID:       '" + str(Device.DeviceID) + "'")
        Domoticz.Debug("--->Unit Count:      '" + str(len(Device.Units)) + "'")
        for UnitNo in Device.Units:
            Unit = Device.Units[UnitNo]
            Domoticz.Debug("--->Unit:           " + str(UnitNo))
            Domoticz.Debug("--->Unit Name:     '" + Unit.Name + "'")
            Domoticz.Debug("--->Unit nValue:    " + str(Unit.nValue))
            Domoticz.Debug("--->Unit sValue:   '" + Unit.sValue + "'")
            Domoticz.Debug("--->Unit LastLevel: " + str(Unit.LastLevel))
    return

def statusAsLevelSwitch(self):
    ## Not used at the moment. Backup only
    ## 2: Charger status
    myUnit = Devices[chargerId].Units[self.DEVICESTATUS]
    chargingStatus = Statuses(chargerStatus["status_id"])
    statusLevel = {
        Statuses.WAITING: 0,
        Statuses.CHARGING: 10,
        Statuses.READY: 20,
        Statuses.PAUSED: 30,
        Statuses.SCHEDULED: 40,
        Statuses.DISCHARGING: 50,
        Statuses.ERROR: 60,
        Statuses.DISCONNECTED: 70,
        Statuses.LOCKED: 80,
        Statuses.UPDATING: 90
    }
    level = str(statusLevel[chargingStatus])
    

    if myUnit.sValue != level:
        myUnit.sValue = level
        myUnit.Update(Log=True)
        Domoticz.Debug('Charging status changed to: ' + level)


#http://build:8080/json.htm?type=command&param=udevice&idx=120&nvalue=0&svalue=1234;123;2023-04-01