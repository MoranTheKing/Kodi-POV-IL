def trakt_collection(mediatype, page_no):
	original_list = trakt_fetch_collection_watchlist('collection', mediatype)
	sort_key = settings.lists_sort_order('collection')
	if   sort_key == 2: original_list.sort(key=itemgetter('premiered'), reverse=True)
	elif sort_key == 1: original_list.sort(key=itemgetter('collected_at'), reverse=True)
	else: original_list = sort_for_article(original_list, 'title', settings.ignore_articles())
	if settings.paginate(): return paginate_list(original_list, page_no, settings.page_limit())
	return original_list, 1

def trakt_favorites(mediatype, page_no):
	original_list = trakt_fetch_collection_watchlist('favorites', mediatype)
	sort_key = settings.lists_sort_order('collection')
	if   sort_key == 2: original_list.sort(key=itemgetter('premiered'), reverse=True)
	elif sort_key == 1: original_list.sort(key=itemgetter('collected_at'), reverse=True)
	else: original_list = sort_for_article(original_list, 'title', settings.ignore_articles())
	if settings.paginate(): return paginate_list(original_list, page_no, settings.page_limit())
	return original_list, 1

def trakt_watchlist(mediatype, page_no):
	def first_aired(item):
		if not item.get('premiered'): return False
		return jsondate_to_datetime(item['premiered']).astimezone().date() <= current_date
	original_list = trakt_fetch_collection_watchlist('watchlist', mediatype)
	if not settings.show_unaired_watchlist():
		current_date = get_datetime()
		original_list = [i for i in original_list if first_aired(i)]
	sort_key = settings.lists_sort_order('watchlist', mediatype)
	if   sort_key == 2: original_list.sort(key=itemgetter('premiered'), reverse=True)
	elif sort_key == 1: original_list.sort(key=itemgetter('collected_at'), reverse=True)
	else: original_list = sort_for_article(original_list, 'title', settings.ignore_articles())
	if settings.paginate(): return paginate_list(original_list, page_no, settings.page_limit())
	return original_list, 1
