# Author: Nic Wolfe <nic@wolfeden.ca>
# URL: http://code.google.com/p/sickbeard/
#
# This file is part of SickRage.
#
# SickRage is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# SickRage is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with SickRage.  If not, see <http://www.gnu.org/licenses/>.

import urllib
import time
import datetime
import os

try:
    import xml.etree.cElementTree as etree
except ImportError:
    import elementtree.ElementTree as etree

import sickbeard
import generic

from sickbeard import classes
from sickbeard import helpers
from sickbeard import scene_exceptions
from sickbeard import encodingKludge as ek
from sickbeard.common import cpu_presets
from sickbeard import logger
from sickbeard import tvcache
from sickbeard.exceptions import ex, AuthException


class NewznabProvider(generic.NZBProvider):
    def __init__(self, name, url, key='', catIDs='5030,5040', search_mode='eponly', search_fallback=False):

        generic.NZBProvider.__init__(self, name)

        self.cache = NewznabCache(self)

        self.url = url

        self.key = key

        self.search_mode = search_mode
        self.search_fallback = search_fallback

        # a 0 in the key spot indicates that no key is needed
        if self.key == '0':
            self.needs_auth = False
        else:
            self.needs_auth = True

        if catIDs:
            self.catIDs = catIDs
        else:
            self.catIDs = '5030,5040'

        self.enabled = True
        self.supportsBacklog = True

        self.default = False

    def configStr(self):
        return self.name + '|' + self.url + '|' + self.key + '|' + self.catIDs + '|' + str(
            int(self.enabled)) + '|' + self.search_mode + '|' + str(int(self.search_fallback))

    def imageName(self):
        if ek.ek(os.path.isfile, ek.ek(os.path.join, sickbeard.PROG_DIR, 'gui', sickbeard.GUI_NAME, 'images', 'providers', self.getID() + '.png')):
            return self.getID() + '.png'
        return 'newznab.png'

    def isEnabled(self):
        return self.enabled

    def _get_season_search_strings(self, ep_obj):

        to_return = []
        cur_params = {}

        # season
        if ep_obj.show.air_by_date or ep_obj.show.sports:
            date_str = str(ep_obj.airdate).split('-')[0]
            cur_params['season'] = date_str
            cur_params['q'] = date_str.replace('-', '.')
        elif ep_obj.show.is_anime:
            cur_params['season'] = "%d" % ep_obj.scene_absolute_number
        else:
            cur_params['season'] = str(ep_obj.scene_season)

        # search
        rid = helpers.mapIndexersToShow(ep_obj.show)[2]
        if rid:
            cur_params['rid'] = rid
            to_return.append(cur_params)
        else:
            # add new query strings for exceptions
            name_exceptions = list(
                set(scene_exceptions.get_scene_exceptions(ep_obj.show.indexerid) + [ep_obj.show.name]))
            for cur_exception in name_exceptions:
                if 'q' in cur_params:
                    cur_params['q'] = helpers.sanitizeSceneName(cur_exception) + '.' + cur_params['q']
                to_return.append(cur_params)

        return to_return

    def _get_episode_search_strings(self, ep_obj, add_string=''):
        to_return = []
        params = {}

        if not ep_obj:
            return [params]

        if ep_obj.show.air_by_date or ep_obj.show.sports:
            date_str = str(ep_obj.airdate)
            params['season'] = date_str.partition('-')[0]
            params['ep'] = date_str.partition('-')[2].replace('-', '/')
        elif ep_obj.show.anime:
            params['ep'] = "%i" % int(ep_obj.scene_absolute_number)
        else:
            params['season'] = ep_obj.scene_season
            params['ep'] = ep_obj.scene_episode

        # search
        rid = helpers.mapIndexersToShow(ep_obj.show)[2]
        if rid:
            params['rid'] = rid
            to_return.append(params)
        else:
            # add new query strings for exceptions
            name_exceptions = list(set(scene_exceptions.get_scene_exceptions(ep_obj.show.indexerid) + [ep_obj.show.name]))
            for cur_exception in name_exceptions:
                params['q'] = helpers.sanitizeSceneName(cur_exception)
                to_return.append(params)

        return to_return

    def _doGeneralSearch(self, search_string):
        return self._doSearch({'q': search_string})

    def _checkAuth(self):

        if self.needs_auth and not self.key:
            logger.log(u"Incorrect authentication credentials for " + self.name + " : " + "API key is missing",
                       logger.DEBUG)
            raise AuthException("Your authentication credentials for " + self.name + " are missing, check your config.")

        return True

    def _checkAuthFromData(self, data):

        if data is None:
            return self._checkAuth()

        if 'error' in data.feed:
            code = data.feed['error']['code']

            if code == '100':
                raise AuthException("Your API key for " + self.name + " is incorrect, check your config.")
            elif code == '101':
                raise AuthException("Your account on " + self.name + " has been suspended, contact the administrator.")
            elif code == '102':
                raise AuthException(
                    "Your account isn't allowed to use the API on " + self.name + ", contact the administrator")
            else:
                logger.log(u"Unknown error given from " + self.name + ": " + data.feed['error']['description'],
                           logger.ERROR)
                return False

        return True

    def _doSearch(self, search_params, search_mode='eponly', epcount=0, age=0):

        self._checkAuth()

        params = {"t": "tvsearch",
                  "maxage": sickbeard.USENET_RETENTION,
                  "limit": 100,
                  "attrs": "rageid"}

        # category ids
        if self.show and self.show.is_sports:
            params['cat'] = self.catIDs + ',5060'
        elif self.show and self.show.is_anime:
            params['cat'] = self.catIDs + ',5070'
        else:
            params['cat'] = self.catIDs

        # if max_age is set, use it, don't allow it to be missing
        if age or not params['maxage']:
            params['maxage'] = age

        if search_params:
            params.update(search_params)

        if self.needs_auth and self.key:
            params['apikey'] = self.key

        search_url = self.url + 'api?' + urllib.urlencode(params)

        logger.log(u"Search url: " + search_url, logger.DEBUG)

        data = self.cache.getRSSFeed(search_url)
        if not data:
            return []

        if self._checkAuthFromData(data):

            items = data.entries
            results = []

            for curItem in items:
                (title, url) = self._get_title_and_url(curItem)

                if title and url:
                    results.append(curItem)
                else:
                    logger.log(
                        u"The data returned from the " + self.name + " is incomplete, this result is unusable",
                        logger.DEBUG)

            return results

        return []

    def findPropers(self, search_date=None):

        search_terms = ['.proper.', '.repack.']

        cache_results = self.cache.listPropers(search_date)
        results = [classes.Proper(x['name'], x['url'], datetime.datetime.fromtimestamp(x['time']), self.show) for x in
                   cache_results]

        index = 0
        alt_search = ('nzbs_org' == self.getID())
        term_items_found = False
        do_search_alt = False

        while index < len(search_terms):
            search_params = {'q': search_terms[index]}
            if alt_search:

                if do_search_alt:
                    index += 1

                if term_items_found:
                    do_search_alt = True
                    term_items_found = False
                else:
                    if do_search_alt:
                        search_params['t'] = "search"

                    do_search_alt = (True, False)[do_search_alt]

            else:
                index += 1

            for item in self._doSearch(search_params, age=4):

                (title, url) = self._get_title_and_url(item)

                if item.has_key('published_parsed') and item['published_parsed']:
                    result_date = item.published_parsed
                    if result_date:
                        result_date = datetime.datetime(*result_date[0:6])
                else:
                    logger.log(u"Unable to figure out the date for entry " + title + ", skipping it")
                    continue

                if not search_date or result_date > search_date:
                    search_result = classes.Proper(title, url, result_date, self.show)
                    results.append(search_result)
                    term_items_found = True
                    do_search_alt = False

        return results


class NewznabCache(tvcache.TVCache):
    def __init__(self, provider):

        tvcache.TVCache.__init__(self, provider)

        # only poll newznab providers every 15 minutes max
        self.minTime = 15

    def _getRSSData(self):

        params = {"t": "tvsearch",
                  "cat": self.provider.catIDs + ',5060,5070',
                  "attrs": "rageid"}

        if self.provider.needs_auth and self.provider.key:
            params['apikey'] = self.provider.key

        rss_url = self.provider.url + 'api?' + urllib.urlencode(params)

        logger.log(self.provider.name + " cache update URL: " + rss_url, logger.DEBUG)

        return self.getRSSFeed(rss_url)

    def _checkAuth(self, data):
        return self.provider._checkAuthFromData(data)

    def updateCache(self):

        # delete anything older then 7 days
        self._clearCache()

        if not self.shouldUpdate():
            return

        if self._checkAuth(None):
            data = self._getRSSData()

            # as long as the http request worked we count this as an update
            if data:
                self.setLastUpdate()
            else:
                return []

            if self._checkAuth(data):
                items = data.entries
                cl = []
                for item in items:
                    ci = self._parseItem(item)
                    if ci is not None:
                        cl.append(ci)

                if len(cl) > 0:
                    myDB = self._getDB()
                    myDB.mass_action(cl)

            else:
                raise AuthException(
                    u"Your authentication credentials for " + self.provider.name + " are incorrect, check your config")

        return []


    # overwrite method with that parses the rageid from the newznab feed
    def _parseItem(self, item):
        title = item.title
        url = item.link

        attrs = item.newznab_attr
        if not isinstance(attrs, list):
            attrs = [item.newznab_attr]

        tvrageid = 0
        for attr in attrs:
            if attr['name'] == 'tvrageid':
                tvrageid = int(attr['value'])
                break

        self._checkItemAuth(title, url)

        if not title or not url:
            logger.log(
                u"The data returned from the " + self.provider.name + " feed is incomplete, this result is unusable",
                logger.DEBUG)
            return None

        url = self._translateLinkURL(url)

        logger.log(u"Attempting to add item from RSS to cache: " + title, logger.DEBUG)
        return self._addCacheEntry(title, url, indexer_id=tvrageid)
