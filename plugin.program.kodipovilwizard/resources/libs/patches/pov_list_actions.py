"""Keep translated labels separate from the provider's stable action IDs."""


def default_choices(manager, scope, provider):
    if provider == 'tmdb' and (manager.params.get('trakt_list_name') or
                               manager.params.get('mdbl_list_name')):
        return []
    names = [('watchlist', 'watchl_str'), ('favorites', 'fav_str')]
    if provider == 'trakt':
        names.append(('collection', 'coll_str'))
    choices = [(key, scope[name], '', manager.icon) for key, name in names]
    if provider == 'trakt' and manager.mediatype == 'tvshow':
        choices.append(('dropped', 'Toggle Dropped', '', manager.icon))
    return choices
