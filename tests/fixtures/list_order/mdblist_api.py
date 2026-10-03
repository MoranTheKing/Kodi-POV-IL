"""Official POV 6.10.01 personal list fixture."""
def get_mdbl_list_contents(list_type, list_id):
	string = 'mdbl_list_contents_%s_%s' % (list_type, list_id)
	if list_type == 'external': url = '/external/lists/%s/items?unified=true' % list_id
	else: url = '/lists/%s/items?unified=true' % list_id
	return mdbl_cache.cache_mdbl_object(_get_mdbl_paginated_list, string, url)['items']
