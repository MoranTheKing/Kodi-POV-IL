# Import necessary libraries
import random
import shutil
import xbmcaddon,os,xbmc
global global_var,site_id,sub_color#global
global_var=[]
from resources.lib.subs_engine import log
import requests,json
import urllib
from resources.lib.subs_engine.extract_sub import extract
from resources.lib.subs_engine.general import DEFAULT_REQUEST_TIMEOUT
from resources.lib.subs_engine import cache
import xbmcvfs
import struct
#########################################

que=urllib.parse.quote_plus
Addon=xbmcaddon.Addon()
MyScriptID=Addon.getAddonInfo('id')
MyAddonName = Addon.getAddonInfo('name')
MyAddonVersion    = Addon.getAddonInfo('version') # Module version
USER_AGENT = '%s v%s' %(MyAddonName, MyAddonVersion)
xbmc_tranlate_path=xbmcvfs.translatePath
__profile__ = xbmc_tranlate_path(Addon.getAddonInfo('profile'))
MyTmp = xbmc_tranlate_path(os.path.join(__profile__, 'temp_opensubtitles'))

########### Settings ####################
# Retrieve OS_USER_API_KEY_VALUE from settings
OS_USER_API_KEY_VALUE = Addon.getSetting("OS_USER_API_KEY_VALUE")
# Check if OS_USER_API_KEY_VALUE is not empty
USE_OS_USER_API_KEY = bool(OS_USER_API_KEY_VALUE)
#########################################

########### Constants ###################
OPS_API_BASE_URL = u"https://api.opensubtitles.com/api/v1"
# OPS_API_LOGIN_URL = f"{OPS_API_BASE_URL}/login"
OPS_API_SEARCH_URL = f"{OPS_API_BASE_URL}/subtitles"
OPS_API_DOWNLOAD_URL = f"{OPS_API_BASE_URL}/download"
OS_API_KEYS_URL = 'https://morantheking.github.io/Kodi-POV-IL/repository/other/DarkSubs_OpenSubtitles/darksubs_opensubtitles_api.json'
OS_API_KEYS_LOCAL_FILE = os.path.join(os.path.dirname(__file__), 'darksubs_opensubtitles_api.json')
site_id='[OpenSubtitles]'
sub_color='orange'
#########################################

###### Requests Params ##############
REQUEST_MAX_RETRIES_NUMBER = 8
REQUEST_RETRY_DELAY_IN_MS = 500
OPENSUBTITLES_SEARCH_FALLBACK_VERSION = 4
#########################################

def _base_search_query(lang_string):
    return {
        'languages': lang_string,
        'hearing_impaired': 'include',
        'ai_translated': 'include',
        'foreign_parts_only': 'include',
        'machine_translated': 'include',
    }


def _clean_imdb_id(imdb_id):
    if imdb_id.startswith('tt'):
        return imdb_id[2:]
    return imdb_id


def _add_if_value(querystring, key, value):
    if value not in (None, ''):
        querystring[key] = value


def _build_query_variants(video_data, lang_string):
    title = video_data.get('OriginalTitle', '')
    season = video_data.get('season', '')
    episode = video_data.get('episode', '')
    year = video_data.get('year', '')
    imdb_id = video_data.get('imdb', '')
    media_type = video_data.get('media_type', '')

    variants = []

    if imdb_id.startswith('tt'):
        imdb_numeric = _clean_imdb_id(imdb_id)
        if media_type == 'tv':
            by_parent_imdb = _base_search_query(lang_string)
            _add_if_value(by_parent_imdb, 'parent_imdb_id', imdb_numeric)
            _add_if_value(by_parent_imdb, 'season_number', season)
            _add_if_value(by_parent_imdb, 'episode_number', episode)
            variants.append(('parent_imdb_id', by_parent_imdb))

            by_query = _base_search_query(lang_string)
            _add_if_value(by_query, 'query', title)
            _add_if_value(by_query, 'season_number', season)
            _add_if_value(by_query, 'episode_number', episode)
            variants.append(('tv_query', by_query))
        else:
            by_imdb = _base_search_query(lang_string)
            _add_if_value(by_imdb, 'imdb_id', imdb_numeric)
            variants.append(('imdb_id', by_imdb))

            by_query_year = _base_search_query(lang_string)
            _add_if_value(by_query_year, 'query', title)
            _add_if_value(by_query_year, 'year', year)
            variants.append(('movie_query_year', by_query_year))
    else:
        by_query = _base_search_query(lang_string)
        _add_if_value(by_query, 'query', title)
        if media_type == 'tv':
            _add_if_value(by_query, 'season_number', season)
            _add_if_value(by_query, 'episode_number', episode)
            variants.append(('tv_query', by_query))
        else:
            _add_if_value(by_query, 'year', year)
            variants.append(('movie_query_year', by_query))

    # Last-resort title-only search catches cases where metadata year/episode
    # is wrong but OpenSubtitles still has relevant entries for the title.
    if title:
        title_only = _base_search_query(lang_string)
        title_only['query'] = title
        variants.append(('title_only', title_only))

    unique_variants = []
    seen = set()
    for label, querystring in variants:
        signature = tuple(sorted(querystring.items()))
        if signature not in seen:
            seen.add(signature)
            unique_variants.append((label, querystring))
    return unique_variants


def _search_with_key(headers, querystring):
    querystring = dict(querystring)
    response = None
    for attempt_number in range(REQUEST_MAX_RETRIES_NUMBER):
        try:
            response = requests.get(OPS_API_SEARCH_URL, headers=headers, params=querystring, timeout=DEFAULT_REQUEST_TIMEOUT)
            if response.status_code in (406, 503):
                log.warning(f"DEBUG | [OpenSubtitles] | OpenSubtitles SearchSubtitles key unavailable ({response.status_code}); trying next API key.")
                return None, 'key_unavailable'
            response.raise_for_status()
            response_json = response.json()

            total_subs_count = response_json.get('total_count', 0)
            total_pages = response_json.get('total_pages', 0)
            log.warning(f"DEBUG | [OpenSubtitles] | Opensubtitles SearchSubtitles search result: Total subs count: {repr(total_subs_count)} |  Number of pages - {repr(total_pages)}")

            search_data = response_json.get('data', [])

            if total_pages > 1:
                for _page in range(2, total_pages + 1):
                    querystring['page'] = _page
                    response = requests.get(OPS_API_SEARCH_URL, headers=headers, params=querystring, timeout=DEFAULT_REQUEST_TIMEOUT)
                    if response.status_code in (406, 503):
                        log.warning(f"DEBUG | [OpenSubtitles] | OpenSubtitles SearchSubtitles pagination key unavailable ({response.status_code}).")
                        return search_data, 'partial'
                    response.raise_for_status()
                    response_json = response.json()
                    search_data.extend(response_json.get('data', []))
                    xbmc.sleep(100)

            return search_data, 'ok'

        except requests.exceptions.ConnectionError as ce:
            log.warning('DEBUG | [OpenSubtitles] | OpenSubtitles SearchSubtitles connection error: ' + repr(ce))
            if attempt_number < REQUEST_MAX_RETRIES_NUMBER - 1:
                log.warning(f"DEBUG | [OpenSubtitles] | OpenSubtitles SearchSubtitles | Retrying... Attempt {attempt_number + 2} of {REQUEST_MAX_RETRIES_NUMBER}")
                continue
            return None, 'connection_error'
        except Exception as e:
            log.warning('DEBUG | [OpenSubtitles] | OpenSubtitles SearchSubtitles error: ' + repr(e))
            if response is not None and getattr(response, 'status_code', None) in (406, 503):
                return None, 'key_unavailable'
            return None, 'error'

    return None, 'error'


def api_search_subtitles(video_data, all_lang_override):

    # For settings changes to take effect.
    Addon=xbmcaddon.Addon()

    # New OpenSubtitles.com API Search docs:
    # https://opensubtitles.stoplight.io/docs/opensubtitles-api/a172317bd5ccc-search-for-subtitles
    

    selected_lang=[]

    # Language codes from: https://opensubtitles.stoplight.io/docs/opensubtitles-api/1de776d20e873-languages
    if Addon.getSetting("language_hebrew")=='true':
        selected_lang.append('heb')
    if Addon.getSetting("language_english")=='true':
        selected_lang.append('eng')
    if Addon.getSetting("language_russian")=='true':
        selected_lang.append('rus')
    if Addon.getSetting("language_arab")=='true':
        selected_lang.append('ara')
    if len(Addon.getSetting("other_lang"))>0:
        all_lang=Addon.getSetting("other_lang").split(",")
        for items in all_lang:
            selected_lang.append(str(items))
    # If 'all_lang' is enabled OR all_lang_override=True (retry search) - override selected_lang to 'ALL' only (required 'ALL' only in new API)
    if Addon.getSetting("all_lang")=='true' or all_lang_override:
        selected_lang = ['ALL']
    else:   
        for index, lang_code in enumerate(selected_lang):
            selected_lang[index] = xbmc.convertLanguage(lang_code, xbmc.ISO_639_1) or lang_code
       
    lang_string = ','.join(selected_lang)
    query_variants = _build_query_variants(video_data, lang_string)
    
    # Determine which API keys to try for Search. Search used to use one
    # random shared key only; if that key was exhausted, all results were 0.
    if USE_OS_USER_API_KEY:
        api_keys = [("User_Setting_API_Key", OS_USER_API_KEY_VALUE)]
    else:
        api_keys = get_api_keys(shuffle_keys=True)

    for variant_name, querystring in query_variants:
        log.warning("DEBUG | [OpenSubtitles] | Opensubtitles SearchSubtitles query variant: " + variant_name + " | " + repr(querystring))

        for OS_API_KEY_NAME, OS_API_KEY_VALUE in api_keys:
            log.warning(f"DEBUG | [OpenSubtitles] | Opensubtitles SearchSubtitles OS_API_KEY_NAME={OS_API_KEY_NAME}")

            headers = {
                "User-Agent": USER_AGENT,
                "Api-Key": OS_API_KEY_VALUE
            }

            search_data, status = _search_with_key(headers, querystring)
            if search_data:
                return search_data
            if status == 'key_unavailable':
                continue
            if status in ('connection_error', 'error'):
                break

    return []
       
       
def get_subs(video_data, all_lang_override=False):

    # For settings changes to take effect.
    Addon=xbmcaddon.Addon()
    
    global global_var
    log.warning('DEBUG | [OpenSubtitles] | Searching Opensubtitles')
    subtitle_list = []
    
    search_data = api_search_subtitles(video_data, all_lang_override)
    
    if search_data is not None:

        for search_item in search_data:
        
            attributes = search_item.get('attributes', {})
            SubRating = attributes.get("ratings", '0')
            hearing_impaired = "true" if attributes.get("hearing_impaired", False) else "false"
            
            thumbnailImageLanguageName = attributes.get("language")
            if thumbnailImageLanguageName is None:
                # Skip this iteration of the loop if thumbnailImageLanguageName is None
                continue

            # Attempt language conversion; if it fails, assign the original thumbnailImageLanguageName
            FullLanguageName = xbmc.convertLanguage(thumbnailImageLanguageName, xbmc.ENGLISH_NAME) or thumbnailImageLanguageName
            
            try:
                if attributes['files']:
                    # Attempt to access 'file_name' and 'file_id' if 'files' exist and have elements
                    SubFileName = attributes['release'] or attributes['files'][0]['file_name']  # Get 'file_name'
                    file_id = str(attributes['files'][0]['file_id'])  # Get 'file_id' and convert to string
                else:
                    # If 'files' or its elements are missing or empty, proceed to the next search_item
                    continue
            
            except:
                # Handle cases where 'file_name' or 'file_id' are missing or incorrectly structured
                # Go to the next search_item
                continue

            # Define characters that might break the filename (It caused writing problem to MyTmp dir)
            characters_to_remove = '\\/:*?"<>|\''
            # Remove characters that might cause issues in the filename
            SubFileName = ''.join(c for c in SubFileName if c not in characters_to_remove)
        
            # Remove "תרגום אולפנים"
            SubFileName = SubFileName.replace("תרגום אולפנים", "").replace("אולפנים", "").strip()
            
            download_data={}
            download_data['filename']=SubFileName
            download_data['id']=file_id
            download_data['format']="srt"
            # Send Hearing Impaired (HI) flag to determine if to clean HI tags or not.
            download_data['hearing_imp'] = hearing_impaired
            
            url = "plugin://%s/?action=download&filename=%s&language=%s&download_data=%s&source=opensubtitles" % (MyScriptID,
                                                                                                que(SubFileName),
                                                                                                FullLanguageName,
                                                                                                que(json.dumps(download_data))
                                                                                                )

            json_data={'url':url,
                    'label':FullLanguageName,
                    'label2':site_id+' '+SubFileName,
                    'iconImage':str(int(round(float(SubRating)/2))),
                    'thumbnailImage':thumbnailImageLanguageName,
                    'hearing_imp':hearing_impaired,
                    'site_id':site_id,
                    'sub_color':sub_color,
                    'filename':SubFileName,
                    'sync': "false"}

            
               
            subtitle_list.append(json_data)
            
        global_var=subtitle_list


def download(download_data,MySubFolder):

    # New OpenSubtitles.com API Download docs:
    # https://opensubtitles.stoplight.io/docs/opensubtitles-api/6be7f6ae2d918-download
    
    try:
        shutil.rmtree(MyTmp)
    except: pass
    xbmcvfs.mkdirs(MyTmp)
    file_id=download_data['id']
    format=download_data['format']
    filename=download_data['filename']
    
    subFile = os.path.join(MyTmp, "%s.%s" %(str(filename), format))
    log.warning(f'DEBUG | [OpenSubtitles] | Desired sub file_id: {file_id} | subFile: {subFile}')
    
    # Subtitle File ID
    payload = {"file_id": int(file_id), "sub_format": "srt"}

    response = None
    success = False
    
    # Get subtitle download link
    for api_key_attempt_number in range(1, REQUEST_MAX_RETRIES_NUMBER + 1):
    
        # Determine which API key to use for Download
        if USE_OS_USER_API_KEY:
            OS_API_KEY_NAME = "User_Setting_API_Key"
            OS_API_KEY_VALUE = OS_USER_API_KEY_VALUE  # Use OS_USER_API_KEY_VALUE from settings
        else:
            OS_API_KEY_NAME,OS_API_KEY_VALUE = get_random_key()
            
        log.warning(f"DEBUG | [OpenSubtitles] | Opensubtitles DownloadSubtitles | api_key_attempt_number={api_key_attempt_number} | OS_API_KEY_NAME={OS_API_KEY_NAME} | OS_API_KEY_VALUE={OS_API_KEY_VALUE}")

        headers = {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Api-Key": OS_API_KEY_VALUE
            # "Authorization": f"Bearer {osdb_token}" # Download works also only with API key, without username/password token authentication, although the API docs. Strange..
        }
        
        retry_number = 1
        while retry_number <= REQUEST_MAX_RETRIES_NUMBER:
            try:
                log.warning(f"DEBUG | [OpenSubtitles] | Opensubtitles DownloadSubtitles | Get sub URL download |  Starting retry_number {retry_number}.")
                log.warning(f"DEBUG | [OpenSubtitles] | Opensubtitles DownloadSubtitles payload: {repr(payload)}")
                response = requests.post(OPS_API_DOWNLOAD_URL, json=payload, headers=headers, timeout=DEFAULT_REQUEST_TIMEOUT)
                log.warning(f"DEBUG | [OpenSubtitles] | Opensubtitles DownloadSubtitles response.status_code: {repr(response.status_code)}")
                
                if response.status_code == 503 or response.status_code == 406:
                    break # 503 - Wrong API Key | 406 - max usage quota reached for the API key.
                response.raise_for_status()  # Raise HTTPError for bad status codes (4xx, 5xx)
                
                response_json = response.json()
                log.warning(f"DEBUG | [OpenSubtitles] | Opensubtitles DownloadSubtitles result: {repr(response_json)}")
                subtitle_download_url = response_json['link']
                success = True # Set flag to break both loops
                break

            except requests.RequestException as req_err:
                if isinstance(req_err, (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError)):
                    log.warning(f"DEBUG | [OpenSubtitles] | OpenSubtitles DownloadSubtitles RequestException error: {repr(req_err)}")
                    if response:
                        log.warning(f"DEBUG | [OpenSubtitles] | OpenSubtitles DownloadSubtitles response.status_code: {response.status_code}")
                    retry_number += 1
                    if retry_number > REQUEST_MAX_RETRIES_NUMBER:
                        raise RuntimeError("Reached maximum retry_number for ReadTimeout or ConnectionError error")
                    xbmc.sleep(REQUEST_RETRY_DELAY_IN_MS)
                else:
                    log.warning('DEBUG | [OpenSubtitles] | OpenSubtitles DownloadSubtitles error: ' + repr(req_err))
                    raise RuntimeError("OpenSubtitles DownloadSubtitles error")
                    
        if success:
            break  # Break the for loop if the flag is set

    if not success:
        log.warning("DEBUG | [OpenSubtitles] | OpenSubtitles DownloadSubtitles error | No success in getting sub URL download from any API key")
        raise RuntimeError(f"OpenSubtitles DownloadSubtitles error | Looped through {REQUEST_MAX_RETRIES_NUMBER} API keys unsucessfully.")
            
    # Download subtitle file
    for attempt_number in range(1, REQUEST_MAX_RETRIES_NUMBER + 1):
        log.warning(f"DEBUG | [OpenSubtitles] | Opensubtitles DownloadSubtitles | Download sub file | Starting attempt_number {attempt_number}.")
        try:
            sub_download_response = requests.get(subtitle_download_url, timeout=DEFAULT_REQUEST_TIMEOUT)
            log.warning(f"DEBUG | [OpenSubtitles] | Opensubtitles DownloadSubtitles sub_download_response: {sub_download_response.status_code}")
            sub_download_response.raise_for_status()  # Raise HTTPError for bad status codes (4xx, 5xx)

            with open(subFile, 'wb') as temp_subFile:
                temp_subFile.write(sub_download_response.content)
            sub_file=extract(subFile,MySubFolder)
            return sub_file

        except requests.HTTPError as http_err:
            if attempt_number < REQUEST_MAX_RETRIES_NUMBER:
                log.warning(f"DEBUG | [OpenSubtitles] | Opensubtitles DownloadSubtitles error: {repr(http_err)} on attempt_number {attempt_number}. Retrying in {REQUEST_RETRY_DELAY_IN_MS} seconds...")
                xbmc.sleep(REQUEST_RETRY_DELAY_IN_MS)
                continue  # Retry the request
            else:
                log.warning('DEBUG | [OpenSubtitles] | OpenSubtitles DownloadSubtitles error: ' + repr(http_err))
                raise RuntimeError("OpenSubtitles DownloadSubtitles HTTPError reached maximum tries.")

def c_get_os_api_keys_v2():
    try:
        response = requests.get(OS_API_KEYS_URL, timeout=DEFAULT_REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        log.warning('DEBUG | [OpenSubtitles] | Failed to fetch remote API keys, using local fallback: ' + repr(e))
        with open(OS_API_KEYS_LOCAL_FILE, 'r', encoding='utf-8') as fallback_file:
            return json.load(fallback_file)

def get_api_keys(shuffle_keys=False):
    OS_API_KEYS = cache.get(c_get_os_api_keys_v2, 24, table='subs') or []
    api_keys = [(item["OS_API_KEY_NAME"], item["OS_API_KEY_VALUE"]) for item in OS_API_KEYS if item.get("OS_API_KEY_VALUE")]
    if shuffle_keys:
        random.shuffle(api_keys)
    return api_keys
    
def get_random_key():
    api_keys = get_api_keys(shuffle_keys=True)
    return api_keys[0]




####################################################################
####################################################################
######################### UNUSED ###################################


# Create an instance of OSDBServer
# osdb_server = OSDBServer()

# Retrieve the osdb_token value using the get_osdb_token() method
# osdb_token = osdb_server.get_osdb_token()
###########################################

# The class is currently UNUSED - was able to Search+Download with API keys authentication ONLY, without username/password authentication.
# class OSDBServer:
    # def __init__( self, *args, **kwargs ):
    
        # self.osdb_token = None
        # self.login_to_osdb()
        

    # def login_to_osdb(self):
        # try:
            # usernameSettings = Addon.getSetting("OSuser")
            # passSettings = Addon.getSetting("OSpass")
            # username = usernameSettings if len(usernameSettings) > 0 else DEFAULT_USERNAME
            # password = passSettings if len(passSettings) > 0 else DEFAULT_PASSWORD
            # username = DEFAULT_USERNAME
            # password = DEFAULT_PASSWORD

            # payload = {
                # "username": username,
                # "password": password
            # }

            # Determine which API key to use
            # if USE_OS_USER_API_KEY:
                # OS_API_KEY_NAME = "User_Setting_API_Key"
                # OS_API_KEY_VALUE = OS_USER_API_KEY_VALUE  # Use OS_USER_API_KEY_VALUE from settings
            # else:
                # OS_API_KEY_NAME,OS_API_KEY_VALUE = get_random_key()
            
            # headers = {
                # "Content-Type": "application/json",
                # "Accept": "application/json",
                # "User-Agent": USER_AGENT,
                # "Api-Key": OS_API_KEY_VALUE
            # }

            # response = requests.post(OPS_API_LOGIN_URL, json=payload, headers=headers, timeout=DEFAULT_REQUEST_TIMEOUT)
            # response.raise_for_status()  # Raise HTTPError for bad status codes (4xx, 5xx)

            # if response.status_code == 200:
                # response_json = response.json()

                # log.warning('DEBUG | [OpenSubtitles] | OpenSubtitles Login: Succeeded')
                # log.warning('DEBUG | [OpenSubtitles] | OpenSubtitles Login: response json - ' + repr(response_json))

                # self.osdb_token = response_json.get('token')
            # else:
                # log.warning('DEBUG | [OpenSubtitles] | OpenSubtitles Login: Failed - status code: ' + repr(response.status_code))
                # error_message = 'Failed with status code: ' + str(response.status_code)
                # notify_for_api_error(error_message, response_json)

        # except Exception as e:
            # log.warning('DEBUG | [OpenSubtitles] | OpenSubtitles Login error: ' + repr(e))

        
    # def get_osdb_token(self):
        # return self.osdb_token
