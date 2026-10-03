"""Verbatim POV 6.10.01 fixtures; source SHA256 1f86cd53338e32630ebfa5dbc50cf5a0877a0fdd851b7b0e97dfae2ef7364d99."""
def cache_mdbl_object(function, string, url):
	dbcur = MDBLCache().dbcur
	dbcur.execute(MC_BASE_GET, (string,))
	cached_data = dbcur.fetchone()
	try:
		if cached_data: return json.loads(cached_data[0])
	except: pass
	result = function(url)
	dbcur.execute(MC_BASE_SET, (string, json.dumps(result)))
	return result
