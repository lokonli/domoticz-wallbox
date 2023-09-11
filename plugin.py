# Plugin for Wallbox
#
# Author: lokonli
# Mods: sincze
#
"""
<plugin key="Wallbox" name="Wallbox-0.0.4" author="lokonli" version="0.0.4" wikilink="https://github.com/lokonli/domoticz-wallbox" externallink="https://github.com/lokonli/domoticz-wallbox">
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
            <li>Total Energy - Total Energy charged. </li>
            <li>Total Green Energy - Total Green Energy charged. </li>
            <li>Firmware - Information about the installed firmware. </li>
        </ul>
        <h3>Configuration</h3>
        Fill in your Wallbox email and password.
        Select Day Hour and Minute to auto update your Historic Sessions periodicly. 
    </description>
    <params>
        <param field="Username" label="Username:" width="200px" required="true" default="name@gmail.com"/>
        <param field="Password" label="Password" width="200px" required="true" default="" password="true"/>
        <param field="Mode1" label="Day" width="75px">
            <options>
                <option label="Monday" value="0"/>
                <option label="Tuesday" value="1"/>
                <option label="Wednesday" value="2"/>
                <option label="Thursday" value="3"/>
                <option label="Friday" value="4"/>
                <option label="Saturday" value="5"/>
                <option label="Sunday" value="6" default="true" />
            </options>
        </param>
        <param field="Mode2" label="Hour" width="75px" required="true" default="03"/>
        <param field="Mode3" label="Minute" width="75px" required="true" default="00"/>
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
    DEVICETOTALENERGY = 8
    DEVICEFIRMWARE = 9
    DEVICETOTALCOUNTER = 10
    DEVICETOTALGREENCOUNTER = 11

    def __init__(self):
        self.messageQueue = queue.Queue()
        self.countDownInit = 3         # Update devices every countDownInit * 10 seconds
        self.chargerList = []
        self.countDown = 1
        self.lastValue = 0
        self.totalEnergy = 0
        self.totalGreenEnergy = 0      # We will be using this to calculate GREEN energy
        self.pluginJustStarted = True  # Used to prevent dual entries set to True if plugin starts!
        self.lastRunDate = "1990-01-01"

    def wbThread(self):
        Domoticz.Log('Start Wallbox thread')

        self.startday = int(Parameters["Mode1"])

        try:
            self.starthour = int(Parameters["Mode2"])
        except:
            message = Parameters["Mode2"]
            Domoticz.Error(f"Invalid starthour value: {message}")
            return
        
        if (not is_valid_hour(self.starthour)):
            Domoticz.Error(f"Invalid starthour (0-23): {self.starthour}")
            return

        try:
            self.startminute = int(Parameters["Mode3"])
        except:
            message = Parameters["Mode3"]
            Domoticz.Error(f"Invalid startminute value: {message}")
            return

        if (not is_valid_minute(self.startminute)):
            Domoticz.Error(f"Invalid startminute (0-59): {self.startminute}")
            return
        
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

        self.chargerList = w.getChargersList()
        if len(self.chargerList):
            for chargerId in self.chargerList:
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
                    for chargerId in self.chargerList:
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
#            debugpy.breakpoint()
        else:
            Domoticz.Log("onStart called")

        if Parameters["Mode6"] != "0":
            Domoticz.Debugging(int(Parameters["Mode6"]))
            DumpConfigToLog()

        self.messageThread = threading.Thread(name="QueueThread", target=WallboxPlugin.wbThread, args=(self,))
        self.messageThread.start()
        Domoticz.Log('Thread started')
        heartBeat = 10     # heartBeat can be changed in debug session
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
                "Type": 243,
                "Subtype": 19,
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
                "Name": "Charging Power",
                "Type": 248,
                "Subtype": 1,
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
                          "AddDBLogEntry" : "true"
                }
            },
            { #8
                "Unit": self.DEVICETOTALENERGY,
                "Name": "Total Energy",
                "Type": 243,
                "Subtype": 29,
            },
            { #9
                "Unit": self.DEVICEFIRMWARE,
                "Name": "Firmware Update",
                "Type": 243,
                "Subtype": 19,
            },
            { #10 Total Power Consumed counter 
                "Unit": self.DEVICETOTALCOUNTER,
                "Name": "Total Grid kWh",
                "Type": 113,
                "Subtype": 0,
            },
            { #11 Total Green Power Consumed Counter
                "Unit": self.DEVICETOTALGREENCOUNTER,
                "Name": "Total Green kWh",
                "Type": 113,
                "Subtype": 0,
            }
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

        # Domoticz Ticket created for that: https://github.com/domoticz/domoticz/issues/5809
        # Fill the device variable with the amount of energy supplied already 
        self.fillHistoricEnergyData(chargerId)

    def fillHistoricEnergyData(self, chargerId):
        # Loads all session data, and send daily sum to Domoticz database
        Domoticz.Debug('Fill historic data')

        if self.debugging:
            self.debugpy.breakpoint()
        myUnit = Devices[str(chargerId)].Units[self.DEVICEENERGY]
        message = f"Fill historic data myUnit: {myUnit}"
        Domoticz.Debug(message) #myUnit: Unit: 7, Name: 'Session Energy', nValue: 0, sValue: '237416;0', LastUpdate: 2023-09-04 13:30:57
        w=self.wallbox
        endDate = datetime.datetime.now()
        startDate = datetime.datetime(1990,1,1)
        sessionList = w.getSessionList(chargerId, startDate, endDate)
        Domoticz.Debug('Fill historic data Dump SessionList')
        dumpJson('sessionList: ', sessionList)
        currentDate=""
        totalEnergy = 0
        previousEnergy = 0

        totalGreenEnergy = 0
        previousGreenEnergy = 0
        Domoticz.Debug('Fill historic data Start Processing SessionList')
        for session in reversed(sessionList["data"]):
            Domoticz.Debug('Start Processing SessionList (2)')
            if session["type"]=="charger_log_session":
                dt_object   = datetime.datetime.fromtimestamp(session["attributes"]["start"])
                sessionDate = dt_object.strftime("%Y-%m-%d")
                if currentDate=="":
                    currentDate=sessionDate
                if currentDate != sessionDate:
                    delta=totalEnergy - previousEnergy
                    previousEnergy = totalEnergy
                    sValue = f"{totalEnergy};{delta};{sessionDate}"

                    message = f"Fill historic data Session myUnit: {myUnit}"
                    Domoticz.Debug(message) #myUnit: Unit: 7, Name: 'Session Energy', nValue: 0, sValue: '237416;0', LastUpdate: 2023-09-04 13:30:57

                    myUnit.sValue = sValue
                    myUnit.nValue = 0
                    myUnit.Update(Log=True)
                    Domoticz.Debug(f"Fill historic data Forced Updating FINISHED! nValue {myUnit.nValue} and sValue {myUnit.sValue}")
                    sessionDate=currentDate

                    deltaGreen=totalGreenEnergy - previousGreenEnergy # I want to know all about Green Historic Energy
                    previousGreenEnergy = totalGreenEnergy            # I want to know all about Green Historic Energy
                totalEnergy=totalEnergy+int(session["attributes"]["energy"]*1000)
                totalGreenEnergy=totalGreenEnergy+int(session["attributes"]["green_energy"]*1000) # I want to know all about Green Historic Energy

        delta=totalEnergy - previousEnergy
        deltaGreen=totalGreenEnergy - previousGreenEnergy             # I want to know all about Green Historic Energy

        sValue = f"{totalEnergy};{delta}"
        Domoticz.Debug(f"Fill historic data: {sValue}")
        myUnit.Update(Log=True)

        Domoticz.Debug('Fill historic data Start Processing SessionList (7)')
        Domoticz.Debug(f"Total energy {totalEnergy} Total Green energy {totalGreenEnergy}") # I want to know all about Green Historic Energy
        self.totalEnergy = totalEnergy
        self.totalGreenEnergy = totalGreenEnergy

    def runScheduledTask(self):
        # Run this tasks for all chargers in the list.
        if len(self.chargerList):
            now = datetime.datetime.now()
            nowAsDateString = now.strftime("%Y-%m-%d")
            # Check if it's Sunday (day 6) and the time is 03:00    
            if nowAsDateString > self.lastRunDate and now.weekday() == self.startday and now.hour == self.starthour and now.minute == self.startminute:
                self.lastRunDate = nowAsDateString
                Domoticz.Log(f"Updated lastRunDate to: {nowAsDateString}")
                for chargerId in self.chargerList:
                    Domoticz.Log(f"Running scheduled task for charger {chargerId} to fill historic energy data...")
                 # Charger ID to use
                    self.fillHistoricEnergyData(chargerId)
        else:
           Domoticz.Log('No charger configured.')

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

        ## 5: Charging current (This is represented in kW), not in 'A' what 'current' is.
        myUnit = Devices[chargerId].Units[self.DEVICECURRENT]
        chargingCurrent = str(round(chargerStatus["charging_power"]*1000,1))
        sValue = f"{chargingCurrent}"
        if myUnit.sValue != sValue:
            myUnit.sValue = sValue
            myUnit.Update(Log=True)
            Domoticz.Debug('Charging Power changed to: ' + chargingCurrent)

        ## 6: Charging stop start
        myUnit = Devices[chargerId].Units[self.DEVICESTARTSTOP]
        chargingCmd = 1 if chargingStatus=='CHARGING' else 0
        if myUnit.nValue != chargingCmd:
            myUnit.nValue = chargingCmd
            myUnit.Update(Log=True)
            Domoticz.Debug('Charging status changed to: ' + str(chargingCmd))

        #added_energy
        ## 7: Energy (Counter;Usage)
        myUnit = Devices[chargerId].Units[self.DEVICEENERGY]
        addedEnergy = int(chargerStatus["added_energy"] * 1000)
        sValue = f"{self.totalEnergy};{addedEnergy}"
        Domoticz.Debug('Added Energy changed to: ' + str(sValue))
        # Set counter to -1 if you can't know the counter absolute value
        # sValue must 3 semicolon separated values, the last value being a date a space and a time ("%Y-%m-%d %H:%M:%S" format) to update last days history.
        if myUnit.sValue != sValue:
            myUnit.sValue = sValue
            myUnit.nValue = 0
            myUnit.Update()
            Domoticz.Debug('Added Energy changed to: ' + str(sValue))

        ## 8: Total Energy
        # Calculate new cumulative
        myUnit = Devices[chargerId].Units[self.DEVICETOTALENERGY]
        delta = 0
        if self.lastValue>0 and addedEnergy<self.lastValue:   # probably started new session, reset lastValue
            Domoticz.Log("resetting lastValue; start new session")
            self.lastValue = 0

        if addedEnergy>self.lastValue:
            delta = addedEnergy - self.lastValue
        self.lastValue = addedEnergy

        # get current cumulative value, and increment
        sValues = myUnit.sValue.split(";")
        if len(sValues)==2:
            currentValue = sValues[1]
        else:
            currentValue = "0"

        newValue = 0
        if currentValue.isnumeric():
            newValue = int(currentValue) + delta

        chargingCurrent = round(chargerStatus["charging_power"]*1000,1)

        if self.pluginJustStarted:  # We don't want double values
            Domoticz.Debug('First run of plugin! Caution Do not Update')
            self.pluginJustStarted = False    # Going for round 2
        else: 
            myUnit.sValue = f"{chargingCurrent};{newValue}"
            myUnit.nValue = 0
            myUnit.Update(Log=True)

       ## 9: Device Firmware Update
        myUnit = Devices[chargerId].Units[self.DEVICEFIRMWARE]

        updateAvailable = chargerStatus["config_data"]["software"]["updateAvailable"]
        currentVersion =  chargerStatus["config_data"]["software"]["currentVersion"]
        latestVersion =   chargerStatus["config_data"]["software"]["latestVersion"]

        if updateAvailable:
            sValue = f"Update Available \nCurrent Version: {currentVersion}\nLatest Version: {latestVersion}"
        else:
            sValue = f"No Update Available\nCurrent Version: {currentVersion}\nLatest Version: {latestVersion}"

        Domoticz.Debug('Firmware DEBUG status: ' + sValue)

        if myUnit.sValue != sValue:
            myUnit.sValue = sValue
            myUnit.Update(Log=True)
            Domoticz.Debug('Firmware status changed to: ' + sValue)

# FUN
        chargingSpeed = chargerStatus["charging_speed"]
        addedRange = chargerStatus["added_range"]
        addedEnergy = chargerStatus["added_energy"]
        addedGreenEnergy = chargerStatus["added_green_energy"]
        addedGridEnergy = chargerStatus["added_grid_energy"]

        factsMessage= f"ChargingSpeed: {chargingSpeed} AddedRange: {addedRange} AddedEnergy: {addedEnergy} AddedGreenEnergy: {addedGreenEnergy} AddedGridEnergy: {addedGridEnergy}"
        Domoticz.Debug('Wallbox Fun Facts: ' + factsMessage)

        lastSync = chargerStatus["last_sync"]
        statusID = chargerStatus["status_id"]
        currentMode = chargerStatus["current_mode"]
        finished = chargerStatus["finished"]

        factsMessage2 = f"Last Sync: {lastSync} StatusID: {statusID} currentMode: {currentMode} Finished: {finished} Total Energy all sessions {self.totalEnergy}"
        Domoticz.Debug('Wallbox Fun Facts: ' + factsMessage2)

        totalcounter = self.totalEnergy + (addedEnergy * 1000)
        factsMessage3 = f"Total Energy all sessions {self.totalEnergy} plus charged now is {addedEnergy} brings total to: {totalcounter} something to remember ?"
        Domoticz.Debug('Wallbox Fun Facts: ' + factsMessage3)
# FUN

        ## 10: RFXCounter Total Energy Added since install
        myUnit = Devices[chargerId].Units[self.DEVICETOTALCOUNTER]
        addedEnergy = int(chargerStatus["added_energy"] * 1000)
        totalcounter = self.totalEnergy + addedEnergy
        sValue = f"{totalcounter}"
        Domoticz.Debug('Wallbox Sensor Total Energy Added since install: ' + sValue)

        if myUnit.sValue != sValue:
            myUnit.sValue = sValue
            myUnit.Update(Log=True)
            Domoticz.Debug('Wallbox Added Energy counter changed to: ' + sValue)

        ## 11: RFXCounter Total Green Energy Added since install
        myUnit = Devices[chargerId].Units[self.DEVICETOTALGREENCOUNTER]
        addedGreenEnergy = int(chargerStatus["added_green_energy"] * 1000)
        totalGreencounter = self.totalGreenEnergy + addedGreenEnergy
        sValue = f"{totalGreencounter}"
        Domoticz.Debug('Wallbox Sensor Total Green Energy Added since install: ' + sValue)

        if myUnit.sValue != sValue:
            myUnit.sValue = sValue
            myUnit.Update(Log=True)
            Domoticz.Debug('Wallbox Added Green Energy Counter changed to: ' + sValue)


    def onStop(self):
        Domoticz.Log("onStop called")
        Domoticz.Debug('onStop called - Threads still active: {} (should be 1 = {})'.format(threading.active_count(), threading.current_thread().name))
        # signal queue thread to exit
        self.messageQueue.put(None)
        self.messageQueue.join()

        Domoticz.Debug('Threads still active: {} (should be 1)'.format(threading.active_count()))
        endTime = time.time() + 70
        while (threading.active_count() > 1) and (time.time() < endTime):
            for thread in threading.enumerate():
                if thread.name != threading.current_thread().name:
                    Domoticz.Debug('Thread {} is still running, waiting otherwise Domoticz will abort on plugin exit.'.format(thread.name))
            time.sleep(1.0)

        Domoticz.Debug('Plugin stopped - Threads still active: {} (should be 1)'.format(threading.active_count()))

    def onConnect(self, Connection, Status, Description):
        Domoticz.Debug('onConnect called ({}) with status={}'.format(Connection.Name, Status))        
        Domoticz.Log("onConnect called")

    def onMessage(self, Connection, Data):
        Domoticz.Debug('onMessage called ({})'.format(Connection.Name))
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
        Domoticz.Debug('onDisconnect called ({})'.format(Connection.Name))
        Domoticz.Log("onDisconnect called")

    def onHeartbeat(self):
        self.countDown = self.countDown-1
        Domoticz.Debug(f"onHeartbeat called {self.countDown}")
        if self.countDown <= 0:
            self.countDown = self.countDownInit
            self.messageQueue.put(
                {"Type":"Update", 
                })
        # Check for the scheduled task
        self.runScheduledTask()

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
def is_valid_hour(hour):
    return 0 <= hour <= 23

def is_valid_minute(minute):
    return 0 <= minute <= 59

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
    ## https://github.com/zekitez/WandDeuze
    # 0, "NOT Connected to my.wallbox.com . Power Off-On (fuse) the wallbox.", unknown thus no
    # 161, "Ready", no
    # 179, "Connected: waiting for next schedule", yes
    # 180, "Connected: waiting for car demand", yes
    # 181, "Connected: waiting for car demand", yes
    # 182, "Paused by user", yes
    # 185, "Connected, PowerBoost reports: NOT ENOUGH POWER AVAILABLE to start charging", yes
    # 194, "Charging", yes
    # 209, "Locked", no
    # 210, "waiting_to_unlock", yes

    # https://community.jeedom.com/t/pluging-wallbox/85244/3
    # WAITING = 164, 180, 181, 183, 184, 185, 186, 187, 188, 189,
    # CHARGING = 193, 194, 195,
    # READY = 161, 162,
    # PAUSED = 178, 182,
    # SCHEDULED = 177, 179,
    # DISCHARGING = 196,
    # ERROR = 14, 15,
    # DISCONNECTED = 0, 163, None,
    # LOCKED = 209, 210, 165,
    # UPDATING = 166

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

#UPDATE THE DEVICE
def UpdateDevice(AlwaysUpdate, Devices, Unit, nValue, sValue, **kwargs):
    Updated = False
    if Unit in Devices:
        kwargs = { key : value for key, value in kwargs.items() if value != getattr(Devices[Unit], key, None) }
        default_kwargs = { 'TimedOut': 0 }
        kwargs = { **default_kwargs, **kwargs }
        if AlwaysUpdate or Devices[Unit].nValue != int(nValue) or Devices[Unit].sValue != str(sValue) or Devices[Unit].TimedOut != kwargs['TimedOut'] or len(kwargs)>1:
            Domoticz.Debug('Update {}: nValue {} - sValue {} - Other: {}'.format(Devices[Unit].Name, nValue, sValue, kwargs))
            Devices[Unit].Update(nValue=int(nValue), sValue=str(sValue), **kwargs)
            Updated = True
        else:
            if not kwargs.get('TimedOut', 0):
                Devices[Unit].Touch()
    return Updated
