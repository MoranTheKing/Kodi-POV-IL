"""Complete focused episode information from metadata already in memory."""


def complete(listitem, show, episode, episode_name):
    # Season responses can legitimately have an empty plot in the chosen
    # language. Preserve a real episode synopsis; label the show fallback.
    plot = (episode.get('plot') or '').strip()
    label = 'תקציר הפרק'
    if not plot:
        plot = (show.get('plot') or '').strip()
        label = 'תקציר הסדרה'
        if plot:
            try:
                listitem.getVideoInfoTag(offscreen=True).setPlot(plot)
            except AttributeError:
                listitem.setInfo('video', {'plot': plot})
    listitem.setProperty('povil_episode_name', episode_name or '')
    listitem.setProperty('povil_episode_plot_label', label if plot else '')
