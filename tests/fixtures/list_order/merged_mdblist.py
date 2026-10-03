def mdblist_collection(mediatype, page_no):
	original_list = mdbl_collection_watchlist_items('collection', mediatype)
	sort_key = settings.lists_sort_order('collection')
	if   sort_key == 2: original_list.sort(key=lambda k: k.get('year') or '', reverse=True)
	elif sort_key == 1: original_list.sort(key=lambda k: k['collected_at'], reverse=True)
	else: original_list = sort_for_article(original_list, 'title', settings.ignore_articles())
	if settings.paginate(): return paginate_list(original_list, page_no, settings.page_limit())
	return original_list, 1

def mdblist_watchlist(mediatype, page_no):
	def first_aired(item):
		if not item.get('release_date'): return False
		return jsondate_to_datetime(item['release_date']).astimezone().date() <= current_date
	original_list = mdbl_collection_watchlist_items('watchlist', mediatype)
	if not settings.show_unaired_watchlist():
		current_date = get_datetime()
		original_list = [i for i in original_list if first_aired(i)]
	sort_key = settings.lists_sort_order('watchlist', mediatype)
	if   sort_key == 2: original_list.sort(key=lambda k: k.get('release_date') or '', reverse=True)
	elif sort_key == 1: original_list.sort(key=lambda k: k['watchlist_at'], reverse=True)
	else: original_list = sort_for_article(original_list, 'title', settings.ignore_articles())
	if settings.paginate(): return paginate_list(original_list, page_no, settings.page_limit())
	return original_list, 1
