#arguments: <world dir>
import sys
import sqlite3

with sqlite3.connect(sys.argv[1] + '/players.sqlite') as players:
    with sqlite3.connect(sys.argv[1] + '/mod_storage.sqlite') as mod_storage:
        playersCur = players.cursor()
        msCur = mod_storage.cursor()
        playersCur.execute("SELECT name,posX,posY,posZ FROM player;")
        while True:
            entry = playersCur.fetchone()
            if not entry:
                break
            msCur.execute("INSERT OR REPLACE INTO entries VALUES ('discord_bridge',?,?)", [sqlite3.Binary(('_' + entry[0]).encode('utf-8')),
                sqlite3.Binary(('(' + str(entry[1]/10) + ',' + str(entry[2]/10) + ',' + str(entry[3]/10) + ')').encode('utf-8'))])