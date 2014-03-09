import sublime
from datetime import datetime,timedelta
from os import path
import calendar,json

pyVersion = 2
try:
    import urllib2 as urllib
    from sun import Sun
    from timezone import FixedOffset,UTC
except (ImportError):
    pyVersion = 3
    import urllib.request as urllib
    from .sun import Sun
    from .timezone import FixedOffset,UTC

INTERVAL = 0.3 # interval in minutes to do new cycle check

ST2_THEME_PREFIX = 'Packages/Color Scheme - Default/'
ST2_THEME_SUFFIX = '.tmTheme'
ST3_THEME_PREFIX = 'Packages/User/'
ST3_THEME_SUFFIX = ' (SL).tmTheme'

TZ_URL = 'https://maps.googleapis.com/maps/api/timezone/json?location={0[latitude]},{0[longitude]}&timestamp={1}&sensor=false'
TZ_CACHE_LIFETIME = timedelta(days=1)

IP_URL = 'http://freegeoip.net/json/'
IP_CACHE_LIFETIME = timedelta(days=1)

PACKAGE = path.splitext(path.basename(__file__))[0]

def logToConsole(str):
    print(PACKAGE + ': {0}'.format(str))

class Settings():
    def __init__(self, onChange=None):
        self.loaded = False
        self.onChange = onChange
        self.sun = None
        self.coordinates = None
        self.timezone = None

        self.load()

    def _needsIpCacheRefresh(self, datetime):
        if not self._ipcache:
            return True

        return self._ipcache['date'] < (datetime - IP_CACHE_LIFETIME)

    def _needsTzCacheRefresh(self, datetime):
        if not self._tzcache:
            return True

        if self._tzcache['fixedCoordinates'] != self.fixedCoordinates:
            return True

        if self._tzcache['coordinates'] != self.coordinates:
            return True

        return self._tzcache['date'] < (datetime - TZ_CACHE_LIFETIME)

    def _callJsonApi(self, url):
        try:
            response = urllib.urlopen(url, None, 2)
            result = response.read()
            if (pyVersion == 3):
                result = result.decode('utf-8')
            return json.loads(result)
        except Exception as err:
            logToConsole(err)
            logToConsole('Failed to get a result from {0}'.format(url))

    def _getIPData(self):
        return self._callJsonApi(IP_URL)

    def _getTimezoneData(self, timestamp):
        url = TZ_URL.format(self.coordinates, timestamp)
        return self._callJsonApi(url)

    def getSun(self):
        if self.fixedCoordinates:
            # settings contain fixed values
            if not self.sun:
                self.sun = Sun(self.coordinates)
            return self.sun

        now = datetime.utcnow()
        if self._needsIpCacheRefresh(now):
            result = self._getIPData()
            self._ipcache = {'date': now}
            if 'latitude' in result and 'longitude' in result:
                self.coordinates = {'latitude': result['latitude'], 'longitude': result['longitude']}
                logToConsole('Using location [{0[latitude]}, {0[longitude]}] from IP lookup'.format(self.coordinates))
                self.sun = Sun(self.coordinates)

        if (self.sun):
            return self.sun
        else:
            raise KeyError('SunCycle: no coordinates')

    def getTimeZone(self):
        now = datetime.utcnow()

        if self._needsTzCacheRefresh(now):
            result = self._getTimezoneData(calendar.timegm(now.timetuple()))
            self._tzcache = {'date': now, 'fixedCoordinates': self.fixedCoordinates, 'coordinates': self.coordinates}
            if result and 'timeZoneName' in result:
                self.timezone = FixedOffset((result['rawOffset'] + result['dstOffset']) / 60, result['timeZoneName'])
            else:
                self.timezone = UTC()
            logToConsole('Using {0}'.format(self.timezone.tzname()))

        return self.timezone

    def load(self):
        settings = sublime.load_settings(PACKAGE + '.sublime-settings')
        settings.clear_on_change(PACKAGE)
        settings.add_on_change(PACKAGE, self.load)

        if not settings.has('day'):
            raise KeyError('SunCycle: missing day setting')

        if not settings.has('night'):
            raise KeyError('SunCycle: missing night setting')

        self._tzcache = None
        self._ipcache = None

        self.day = settings.get('day')
        self.night = settings.get('night')

        self.fixedCoordinates = False
        if settings.has('latitude') and settings.has('longitude'):
            self.fixedCoordinates = True
            self.coordinates = {'latitude': settings.get('latitude'), 'longitude': settings.get('longitude')}
            logToConsole('Using location [{0[latitude]}, {0[longitude]}] from settings'.format(self.coordinates))

        sun = self.getSun()
        now = datetime.now(tz=self.getTimeZone())
        logToConsole('Sunrise at {0}'.format(sun.sunrise(now)))
        logToConsole('Sunset at {0}'.format(sun.sunset(now)))

        if self.loaded and self.onChange:
            self.onChange()

        self.loaded = True

class SunCycle():
    def __init__(self):
        self.dayPart = None
        self.halt = False
        sublime.set_timeout(self.start, 500) # delay execution so settings can load

    def getDayOrNight(self):
        sun = self.settings.getSun()
        now = datetime.now(tz=self.settings.getTimeZone())
        return 'day' if now >= sun.sunrise(now) and now <= sun.sunset(now) else 'night'

    def cycle(self):
        sublimeSettings = sublime.load_settings('Preferences.sublime-settings')

        if sublimeSettings is None:
            raise Exception('Preferences not loaded')

        config = getattr(self.settings, self.getDayOrNight())

        sublimeSettingsChanged = False

        compareWith = newColorScheme = config.get('color_scheme')

        # color scheme name matching in Sublime Text 3
        if pyVersion == 3 and newColorScheme.startswith(ST2_THEME_PREFIX) and newColorScheme.endswith(ST2_THEME_SUFFIX):
            compareWith = (ST3_THEME_PREFIX +
                          newColorScheme.replace(ST2_THEME_PREFIX, '').replace(ST2_THEME_SUFFIX, '') +
                          ST3_THEME_SUFFIX)

        if newColorScheme and compareWith != sublimeSettings.get('color_scheme'):
            logToConsole('Switching to {0}'.format(newColorScheme))
            sublimeSettings.set('color_scheme', newColorScheme)
            sublimeSettingsChanged = True

        newTheme = config.get('theme')
        if newTheme and newTheme != sublimeSettings.get('theme'):
            logToConsole('Switching to {0}'.format(newTheme))
            sublimeSettings.set('theme', newTheme)
            sublimeSettingsChanged = True

        if sublimeSettingsChanged:
            sublime.save_settings('Preferences.sublime-settings')

    def start(self):
        self.settings = Settings(onChange=self.cycle)
        self.loop()

    def loop(self):
        if not self.halt:
            sublime.set_timeout(self.loop, INTERVAL * 60000)
            self.cycle()

    def stop(self):
        self.halt = True

# stop previous instance
if 'sunCycle' in globals():
    globals()['sunCycle'].stop()

# start cycle
sunCycle = SunCycle()
