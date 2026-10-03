"""Official Umbrella 6.7.90 getFavourites fixture."""
from sqlite3 import dbapi2 as database
def getFavourites(content):
	try:
		dbcon = database.connect(favouritesFile)
		dbcur = dbcon.cursor()
		items = dbcur.execute("SELECT * FROM %s" % content).fetchall()
		if content == 'episode':
			items = [(i[0], i[1], i[2], eval(i[3])) for i in items]
		else:
			items = [(i[0], eval(i[1])) for i in items]
	except: items = []
	finally:
		dbcur.close() ; dbcon.close()
	return items
