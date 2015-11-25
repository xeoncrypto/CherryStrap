"""
This file deals primarily with initializing, writing, and connecting
to services needed by the web application at runtime
(e.g. sqlite3, apscheduler, config.ini file) and also contains
runtime commands like daemonizing, restarting, and shutting down the web app.
"""

from __future__ import with_statement

import os, sys, subprocess, threading, cherrypy, sqlite3, datetime, uuid

from lib.configobj.configobj import ConfigObj
from lib.apscheduler.schedulers.background import BackgroundScheduler
from lib.apscheduler.triggers.interval import IntervalTrigger
from lib.apscheduler.triggers.cron import CronTrigger
from cherrystrap import logger, formatter

FULL_PATH = None
PROG_DIR = None

ARGS = None
SIGNAL = None

LOGLEVEL = 1
DAEMON = False
PIDFILE = None

SYS_ENCODING = None

SCHED = BackgroundScheduler()

INIT_LOCK = threading.Lock()
__INITIALIZED__ = False

DATADIR = None
DBFILE = None
CONFIGFILE = None
CFG = None

LOGDIR = None
LOGLIST = []

SERVER_NAME = None
HTTP_HOST = None
HTTP_PORT = None
HTTP_USER = None
HTTP_PASS = None
HTTP_ROOT = None
HTTP_LOOK = None
VERIFY_SSL = True
API_TOKEN = None
LAUNCH_BROWSER = False

HTTPS_ENABLED = False
HTTPS_KEY = 'keys/server.key'
HTTPS_CERT = 'keys/server.crt'

def CheckSection(sec):
    """ Check if INI section exists, if not create it """
    try:
        CFG[sec]
        return True
    except:
        CFG[sec] = {}
        return False

################################################################################
# Check_setting_int                                                            #
################################################################################
def check_setting_int(config, cfg_name, item_name, def_val):
    try:
        my_val = int(config[cfg_name][item_name])
    except:
        my_val = def_val
        try:
            config[cfg_name][item_name] = my_val
        except:
            config[cfg_name] = {}
            config[cfg_name][item_name] = my_val
    logger.debug(item_name + " -> " + str(my_val))
    return my_val

################################################################################
# Check_setting_str                                                            #
################################################################################
def check_setting_str(config, cfg_name, item_name, def_val, log=True):
    try:
        my_val = config[cfg_name][item_name]
    except:
        my_val = def_val
        try:
            config[cfg_name][item_name] = my_val
        except:
            config[cfg_name] = {}
            config[cfg_name][item_name] = my_val

    if log:
        logger.debug(item_name + " -> " + my_val)
    else:
        logger.debug(item_name + " -> ******")

    return my_val

def initialize():

    with INIT_LOCK:

        global __INITIALIZED__, FULL_PATH, PROG_DIR, LOGLEVEL, DAEMON, \
        DATADIR, CONFIGFILE, CFG, LOGDIR, SERVER_NAME, HTTP_HOST, HTTP_PORT, \
        HTTP_USER, HTTP_PASS, HTTP_ROOT, HTTP_LOOK, VERIFY_SSL, \
        LAUNCH_BROWSER, HTTPS_ENABLED, HTTPS_KEY, HTTPS_CERT, API_TOKEN

        if __INITIALIZED__:
            return False

        CheckSection('General')

        try:
            HTTP_PORT = check_setting_int(CFG, 'General', 'http_port', 7889)
        except:
            HTTP_PORT = 7889

        if HTTP_PORT < 21 or HTTP_PORT > 65535:
            HTTP_PORT = 7889

        SERVER_NAME = check_setting_str(CFG, 'General', 'server_name', 'Server')
        HTTP_HOST = check_setting_str(CFG, 'General', 'http_host', '0.0.0.0')
        HTTPS_ENABLED = bool(check_setting_int(CFG, 'General', 'https_enabled', 0))
        HTTPS_KEY = check_setting_str(CFG, 'General', 'https_key', 'keys/server.key')
        HTTPS_CERT = check_setting_str(CFG, 'General', 'https_cert', 'keys/server.crt')
        HTTP_USER = check_setting_str(CFG, 'General', 'http_user', '')
        HTTP_PASS = check_setting_str(CFG, 'General', 'http_pass', '')
        HTTP_ROOT = check_setting_str(CFG, 'General', 'http_root', '')
        HTTP_LOOK = check_setting_str(CFG, 'General', 'http_look', 'bootstrap')
        VERIFY_SSL = bool(check_setting_int(CFG, 'General', 'verify_ssl', 1))
        API_TOKEN = check_setting_str(CFG, 'General', 'api_token', uuid.uuid4().hex)
        LAUNCH_BROWSER = bool(check_setting_int(CFG, 'General', 'launch_browser', 0))
        LOGDIR = check_setting_str(CFG, 'General', 'logdir', '')

        if not LOGDIR:
            LOGDIR = os.path.join(DATADIR, 'Logs')

        # Put the cache dir in the data dir for now
        CACHEDIR = os.path.join(DATADIR, 'cache')
        if not os.path.exists(CACHEDIR):
            try:
                os.makedirs(CACHEDIR)
            except OSError:
                logger.error('Could not create cachedir. Check permissions of: ' + DATADIR)

        # Create logdir
        if not os.path.exists(LOGDIR):
            try:
                os.makedirs(LOGDIR)
            except OSError:
                if LOGLEVEL:
                    print LOGDIR + ":"
                    print ' Unable to create folder for logs. Only logging to console.'

        # Start the logger, silence console logging if we need to
        logger.cherrystrap_log.initLogger(loglevel=LOGLEVEL)

        # Initialize the database
        try:
            dbcheck()
        except Exception, e:
            logger.error("Can't connect to the database: %s" % e)

        __INITIALIZED__ = True
        return True

def daemonize():
    """
    Fork off as a daemon
    """

    # Make a non-session-leader child process
    try:
        pid = os.fork() #@UndefinedVariable - only available in UNIX
        if pid != 0:
            sys.exit(0)
    except OSError, e:
        raise RuntimeError("1st fork failed: %s [%d]" % (e.strerror, e.errno))

    os.setsid() #@UndefinedVariable - only available in UNIX

    # Make sure I can read my own files and shut out others
    prev = os.umask(0)
    os.umask(prev and int('077', 8))

    # Make the child a session-leader by detaching from the terminal
    try:
        pid = os.fork() #@UndefinedVariable - only available in UNIX
        if pid != 0:
            sys.exit(0)
    except OSError, e:
        raise RuntimeError("2st fork failed: %s [%d]" % (e.strerror, e.errno))

    dev_null = file('/dev/null', 'r')
    os.dup2(dev_null.fileno(), sys.stdin.fileno())

    if PIDFILE:
        pid = str(os.getpid())
        logger.debug(u"Writing PID " + pid + " to " + str(PIDFILE))
        file(PIDFILE, 'w').write("%s\n" % pid)

def launch_browser(host, port, root):
    if host == '0.0.0.0':
        host = 'localhost'

    if HTTPS_ENABLED:
        protocol = 'https'
    else:
        protocol = 'http'

    try:
        import webbrowser
        webbrowser.open('%s://%s:%i%s' % (protocol, host, port, root))
    except Exception, e:
        logger.error('Could not launch browser: %s' % e)

def config_write():
    new_config = ConfigObj()
    new_config.filename = CONFIGFILE

    new_config['General'] = {}
    new_config['General']['server_name'] = SERVER_NAME
    new_config['General']['http_port'] = HTTP_PORT
    new_config['General']['http_host'] = HTTP_HOST
    new_config['General']['https_enabled'] = int(HTTPS_ENABLED)
    new_config['General']['https_key'] = HTTPS_KEY
    new_config['General']['https_cert'] = HTTPS_CERT
    new_config['General']['http_user'] = HTTP_USER
    new_config['General']['http_pass'] = HTTP_PASS
    new_config['General']['http_root'] = HTTP_ROOT
    new_config['General']['http_look'] = HTTP_LOOK
    new_config['General']['verify_ssl'] = int(VERIFY_SSL)
    new_config['General']['api_token'] = API_TOKEN
    new_config['General']['launch_browser'] = int(LAUNCH_BROWSER)
    new_config['General']['logdir'] = LOGDIR

    new_config.write()

def dbcheck():

    conn = sqlite3.connect(DBFILE)
    c = conn.cursor()
    # Create and modify your database here

    # c.execute('CREATE TABLE IF NOT EXISTS authors (AuthorID TEXT, AuthorName TEXT UNIQUE, AuthorImg TEXT, AuthorLink TEXT, DateAdded TEXT, Status TEXT, LastBook TEXT, LastLink Text, LastDate TEXT, HaveBooks INTEGER, TotalBooks INTEGER, AuthorBorn TEXT, AuthorDeath TEXT, UnignoredBooks INTEGER)')
    # try:
    #     c.execute('SELECT UnignoredBooks from authors')
    #     logger.info('Updating database to hold UnignoredBooks')
    # except sqlite3.OperationalError:
    #     logger.error('Could not create column Unignored Books in table authors')
    #     c.execute('ALTER TABLE authors ADD COLUMN UnignoredBooks INTEGER')

    conn.commit()
    c.close()

def start():
    global __INITIALIZED__, scheduler_started

    if __INITIALIZED__:
        try:
            # Crons and scheduled jobs go here
            # testInterval = IntervalTrigger(weeks=0, days=0, hours=0, minutes=2, seconds=0, start_date=None, end_date=None, timezone=None)
            # testCron = CronTrigger(year=None, month=None, day=None, week=None, day_of_week=None, hour=None, minute='*/2', second=None, start_date=None, end_date=None, timezone=None)
            # SCHED.add_job(formatter.schedulerTest, testCron)
            SCHED.start()
            scheduler_started = True
        except Exception, e:
            logger.error("Can't start scheduled job(s): %s" % e)

def shutdown(restart=False):
    config_write()
    logger.info('CherryStrap is shutting down ...')
    cherrypy.engine.exit()

    try:
        SCHED.shutdown(wait=True)
    except Exception, e:
        logger.error("Can't shutdown scheduler: %s" % e)

    if PIDFILE:
        logger.info('Removing pidfile %s' % PIDFILE)
        os.remove(PIDFILE)

    if restart:
        logger.info('CherryStrap is restarting ...')
        popen_list = [sys.executable, FULL_PATH]
        popen_list += ARGS
        if '--nolaunch' not in popen_list:
            popen_list += ['--nolaunch']
            logger.info('Restarting CherryStrap with ' + str(popen_list))
        subprocess.Popen(popen_list, cwd=os.getcwd())

    os._exit(0)
