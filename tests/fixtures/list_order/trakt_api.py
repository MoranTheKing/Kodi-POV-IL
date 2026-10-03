"""Official POV 6.10.01 personal list fixture."""
def get_trakt_list_contents(list_type, list_id, user, slug):
	string = 'trakt_list_contents_%s_%s_%s' % (list_type, user, slug)
	if 'my_lists' in list_type: url = '/users/%s/lists/%s/items' % ('me', list_id)
	else: url = '/users/%s/lists/%s/items' % (user, list_id)
	return trakt_cache.cache_trakt_object(_get_trakt_paginated_list, string, url)
