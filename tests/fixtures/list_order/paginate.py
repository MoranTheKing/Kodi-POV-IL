def paginate_list(item_list, page, limit=20):
	if not item_list: return item_list, page
	pages = list(chunks(item_list, limit))
	total_pages = len(pages)
	return pages[page - 1], total_pages
