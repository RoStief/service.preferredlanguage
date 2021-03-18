import xbmc
import xbmcaddon
import websocket
import thread
import simplejson as json
import xml.etree.ElementTree as ET

import xbmcgui

configurationFile = "special://home/media/PreferredLanguage.xml"

def FindAudioStream(showName):
    global configurationFile
    try:
        tree = ET.parse(xbmc.translatePath(configurationFile))
            
        root = tree.getroot()
        if root is None:
            return -1
    except:
        return -1
        
    for child in root:
        if showName == child.get('name'):
            return int(child.get('AudioStreamIndex'))
    return -1

def saveAudioStream(showName, index):
    global configurationFile
    tree = None
    root = None
    try:
        tree = ET.parse(xbmc.translatePath(configurationFile))
    except:
        tree = None

    if tree is not None:
        root = tree.getroot()
    
    if root is None:
        root = ET.Element('PreferredLanguage')
        tree = ET.ElementTree(root)
    
    element = ET.Element('TVShow')
    element.set('name', showName)
    element.set('AudioStreamIndex', str(index))
    root.insert(0,element)

    #import web_pdb; web_pdb.set_trace()
    
    with open(xbmc.translatePath(configurationFile), 'w') as file:
        tree.write(file, encoding='UTF-8')
    
def send_message(ws, method):
    msg = { "jsonrpc": "2.0",
            "method": method,
            "id": method }
    
    ws.send(json.dumps(msg))

#todo: support multiple players: 
# 1. encode PlayerId into msgId, 
# 2. remember in dictionary over msgId
# 3. clear on stopping of video
playerId = -1
preferredStream = -1
showtitle = ""

def on_message(ws, message):
    global playerId
    global preferredStream
    global showtitle
    
    xbmc.log("PREFLANG: Received Message [%s]" % (message))
    reply = json.loads(message)

    msgId = reply.get('id')
    error = reply.get('error')
    if error:
        xbmc.log("PREFLANG: %s" % error[0], xbmc.LOGERROR)
        
    if msgId:
        result = reply.get('result')
        
        if result:
            #---------------------------------------------------------
            # 1. GetActivePlayers: on startup / onAVStart
            #---------------------------------------------------------
            if msgId == "Player.GetActivePlayers":
                xbmc.log("PREFLANG: Got Active Player: [%s]" % result)
                
                playerId = result[0].get('playerid')
                
                if playerId:
                    msg = { "jsonrpc": "2.0",
                            "method": "Player.GetItem",
                            "params" : {"properties": ["showtitle","file", "title"], 
                            "playerid": playerId},
                            "id": "Player.GetItem"
                            }
                    
                    ws.send(json.dumps(msg))
            #---------------------------------------------------------
            # 2. GetItem: Find TV Show info / Lookup preferred audio
            #---------------------------------------------------------
            if msgId == "Player.GetItem":
                xbmc.log("PREFLANG: Got Item: [%s]" % message)
                
                showtitle = result.get('item').get('showtitle')
                
                # NOTE: with streams (amazon/netflix) after the next start of an episode no lookup will be done
                if showtitle is not None and showtitle != "":
                    # is a tv show
                    xbmc.log("PREFLANG: Looking up Streams for: [%s]" % showtitle)
                    preferredStream = FindAudioStream(showtitle)
                    xbmc.log("PREFLANG: Preferred Stream: [%s]" % preferredStream)
                    
                    msg = { "jsonrpc": "2.0",
                            "method": "Player.GetProperties",
                            "params" : {"properties": ["audiostreams","currentaudiostream"], 
                            "playerid": playerId},
                            "id": "Player.GetProperties"
                            }

                    ws.send(json.dumps(msg))
                    
            #---------------------------------------------------------
            # 3. Get Audiostreams for playing TV Show Episode / Change Audio if required
            #---------------------------------------------------------
            if msgId == "Player.GetProperties":
                xbmc.log("PREFLANG: Got Properties: [%s]" % message)
                currentAudio = result.get('currentaudiostream')
                currentLanguage = currentAudio.get('language')
                currentStream = currentAudio.get('index')
                #xbmc.log("PREFLANG: Current Played Language: [%s]" % currentLanguage)
                if preferredStream == -1:

                    # no preferred Stream yet: open window and save selection                    
                    audioStreams = result.get('audiostreams')
                    # TODO: optimize stream language ( audio description )
                    streamNames = [stream.get('language') +" - " +stream.get('name') +" - Channels: " + str(stream.get('channels')) for stream in audioStreams]
                    selectedIndex = xbmcgui.Dialog().select("Select Language", streamNames)
                    if selectedIndex is not None and selectedIndex >= 0:
                        xbmc.log("PREFLANG: Selected AudioStream Number: [%s]" % selectedIndex, level=xbmc.LOGINFO)
                        preferredStream = audioStreams[selectedIndex].get('index')
                        saveAudioStream(showtitle,preferredStream)
                        
                if preferredStream >= 0:
                    if preferredStream != currentStream:
                            xbmc.log("PREFLANG: Changing Stream to: [%s]" % preferredStream, level=xbmc.LOGINFO)
                            msg = { "jsonrpc": "2.0",
                                "method": "Player.SetAudioStream",
                                "params" : {"stream": preferredStream, 
                                "playerid": playerId},
                                "id": "Player.SetAudioStream"
                            }
                            ws.send(json.dumps(msg))
    else:
        method = reply.get('method')
        #---------------------------------------------------------
        # Hook for Player start -> GetActivePlayer(s)
        #---------------------------------------------------------
        if method == "Player.OnAVStart":
            send_message(ws, "Player.GetActivePlayers")
        #---------------------------------------------------------
        # Hook for Player Stop -> Remove Active Player(s)
        #---------------------------------------------------------
        if method == "Player.OnStop":
            playerId = -1
            preferredStream = -1
            showtitle = ""
            
def on_error(ws, error):
    xbmc.log("PREFLANG: %s" % error,level=xbmc.LOGERROR)

def on_close(ws):
    xbmc.log("PREFLANG: ### closed ###")

def on_open(ws):
    def run(*args):
        while not monitor.abortRequested():
            if monitor.waitForAbort(60):
                break
        ws.close()
    xbmc.log("PREFLANG: Socket Opened")
    send_message(ws, "Player.GetActivePlayers")
    # start thread which waits for service to be closed
    thread.start_new_thread(run, ())   

if __name__ == '__main__':
    settings = xbmcaddon.Addon(id='service.preferredlanguage')
    
    monitor = xbmc.Monitor();
    #websocket.enableTrace(True)
    ws = websocket.WebSocketApp("ws://127.0.0.1:9090/jsonrpc",
                                on_open = on_open,
                                on_message = on_message,
                                on_error = on_error,
                                on_close = on_close)

    ws.run_forever()
