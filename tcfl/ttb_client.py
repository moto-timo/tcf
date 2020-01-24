#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

#
# FIXME: cache the target list's per target broker into a pickled
#   ${TCF_CACHE:-~/.tcf/cache}/BROKER.cache; use the cache instead of
#   calling target_list(); implement cache-refresh command.
# FIXME: do a python iterator over the targets
"""
Client API for accessing *ttbd*'s REST API
------------------------------------------

This API provides a way to access teh REST API exposed by the *ttbd*
daemon; it is divided in two main blocks:

 - :class:`rest_target_broker`: abstracts a remote *ttbd* server and
   provides methods to run stuff on targets and and connect/disconnect
   things on/from targets.

 - `rest_*()` methods that take a namespace of arguments, lookup the
   object target, map it to a remote server, execute the method and
   then print the result to console.

   This breakup is a wee arbitrary, it can use some cleanup

"""
# FIXME: this is crap, need to move all the functions to core or something
import cPickle
import contextlib
import errno
import fcntl
import getpass
import hashlib
import json
import logging
import math
import os
import pprint
import re
import struct
import sys
import termios
import threading
import time
import tty
import urlparse

import commonl
# We multithread to run testcases in parallel
#
# When massively running threads in production environments, we end up
# with hundreds/thousands of threads based on the setup which are just
# launching a build and waiting. However, sometimes something dies
# inside Python and leaves the thing hanging with the GIL taken and
# everythin deadlocks.
#
# For those situations, using the PathOS/pools library works better,
# as it can multithread as processes (because of better pickling
# abilities) and doesn't die.
#
# So there, the PATHOS.multiprocess library if available and in said
# case, use process pools for the testcases.

_multiprocessing_pool_c = None

def import_mp_pathos():
    import pathos.multiprocessing
    global _multiprocessing_pool_c
    _multiprocessing_pool_c = pathos.pools._ThreadPool

def import_mp_std():
    import multiprocessing.pool
    global _multiprocessing_pool_c
    _multiprocessing_pool_c = multiprocessing.pool.ThreadPool

mp = os.environ.get('TCF_USE_MP', None)
if mp == None:
    try:
        import_mp_pathos()
    except ImportError as e:
        import_mp_std()
elif mp.lower() == 'std':
    import_mp_std()
elif mp.lower() == 'pathos':
    import_mp_pathos()
else:
    raise RuntimeError('Invalid value to TCF_USE_MP (%s)' % mp)

import commonl
import requests

logger = logging.getLogger("tcfl.ttb_client")

if hasattr(requests, "packages"):
    # Newer versions of Pyython will complain loud about unverified certs
    requests.packages.urllib3.disable_warnings()

tls = threading.local()


def tls_var(name, factory, *args, **kwargs):
    value = getattr(tls, name, None)
    if value == None:
        value = factory(*args, **kwargs)
        setattr(tls, name, value)
    return value


global rest_target_brokers
rest_target_brokers = {}

class rest_target_broker(object):

    # Hold the information about the remote target, as acquired from
    # the servers
    _rts_cache = None

    API_VERSION = 1
    API_PREFIX = "/ttb-v" + str(API_VERSION) + "/"

    def __init__(self, state_path, url, ignore_ssl = False, aka = None,
                 ca_path = None):
        """Create a proxy for a target broker, optionally loading state
        (like cookies) previously saved.

        :param str state_path: Path prefix where to load state from
        :param str url: URL for which we are loading state
        :param bool ignore_ssl: Ignore server's SSL certificate
           validation (use for self-signed certs).
        :param str aka: Short name for this server; defaults to the
           hostname (sans domain) of the URL.
        :param str ca_path: Path to SSL certificate or chain-of-trust bundle
        :returns: True if information was loaded for the URL, False otherwise
        """
        self._url = url
        self._base_url = None
        self.cookies = {}
        self.valid_session = None
        if ignore_ssl == True:
            self.verify_ssl = False
        elif ca_path:
            self.verify_ssl = ca_path
        else:
            self.verify_ssl = True
        self.lock = threading.Lock()
        self.parsed_url = urlparse.urlparse(url)
        if aka == None:
            self.aka = self.parsed_url.hostname.split('.')[0]
        else:
            assert isinstance(aka, basestring)
            self.aka = aka
        # Load state
        url_safe = commonl.file_name_make_safe(url)
        file_name = state_path + "/cookies-%s.pickle" % url_safe
        try:
            with open(file_name, "r") as f:
                self.cookies = cPickle.load(f)
            logger.info("%s: loaded state", file_name)
        except cPickle.UnpicklingError as e: #invalid state, clean file
            os.remove(file_name)
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise e
            else:
                logger.debug("%s: no state-file, will not load", file_name)

    def __str__(self):
        return self.parsed_url.geturl()

    @classmethod
    def _rt_list_to_dict(cls, rt_list):
        rts = {}
        for rt in rt_list:
            rt_fullid = rt['fullid']
            # Introduce two symbols after the ID and fullid, so "-t
            # TARGETNAME" works
            rt[rt_fullid] = True
            rt[rt['id']] = True
            rts[rt_fullid] = rt
        return rts

    class __metaclass__(type):
        @classmethod
        def _rts_get(cls, rtb):
            try:
                rt_list = rtb.rest_tb_target_list(all_targets = True)
            except requests.exceptions.RequestException as e:
                logger.error("%s: can't use: %s", rtb._url, e)
                return {}
            return rtb._rt_list_to_dict(rt_list)

        @property
        def rts_cache(cls):
            if cls._rts_cache != None:
                return cls._rts_cache
            if not rest_target_brokers:
                cls._rts_cache = {}
                return cls._rts_cache
            # Collect the targets into a list of tuples (FULLID, SUFFIX),
            # where suffix will be *! (* if powered, ! if owned)
            # Yes, there are better ways to do this, but this one
            # is simple -- just launch one thread per server and
            # then collect the data in a single cache -- shall use
            # process pool, for better performance, but can't get
            # it to serialize properly
            tp = _multiprocessing_pool_c(processes = len(rest_target_brokers))
            threads = {}
            for rtb in sorted(rest_target_brokers.itervalues()):
                threads[rtb] = tp.apply_async(cls._rts_get, (rtb,))
            tp.close()
            tp.join()
            cls._rts_cache = {}
            for thread in threads.values():
                cls._rts_cache.update(thread.get())
            return cls._rts_cache

    @classmethod
    def rts_cache_flush(cls):
        del cls._rts_cache
        cls._rts_cache = None

    def tb_state_trash(self):
        # remove the state so tb_state_save() later will not save any
        # cookies and thus effectively log out this user from the
        # client side standpoint.
        self.cookies = {}

    def tb_state_save(self, filepath):
        """Save cookies in *path* so they can be loaded by when the object is
        created.

        :param path: Filename where to save to
        :type path: str

        """
        url_safe = commonl.file_name_make_safe(self._url)
        if not os.path.isdir(filepath):
            logger.warning("%s: created state storage directory", filepath)
            os.mkdir(filepath)
        fname = filepath + "/cookies-%s.pickle" % url_safe
        if self.cookies == {}:
            logger.debug("%s: state deleted (no cookies)", self._url)
            commonl.rm_f(fname)
        else:
            with os.fdopen(os.open(fname, os.O_CREAT | os.O_WRONLY, 0o600),
                           "w") as f, \
                    self.lock:
                cPickle.dump(self.cookies, f, protocol = 2)
                logger.debug("%s: state saved %s",
                             self._url, pprint.pformat(self.cookies))

    # FIXME: this timeout has to be proportional to how long it takes
    # for the target to flash, which we know from the tags
    def send_request(self, method, url, data = None, files = None,
                     stream = False, raw = False, timeout = 480):
        """
        Send request to server using url and data, save the cookies
        generated from request, search for issues on connection and
        raise and exception or return the response object.

        :param url: url to request
        :type url: str
        :param data: args to send in the request. default None
        :type data: dict
        :param method: method used to request GET, POST and PUT. default PUT
        :type method: str
        :param raise_error: if true, raise an error if something goes
            wrong in the request. default True
        :type raise_error: bool
        :returns: response object
        :rtype: requests.Response

        """
        # create the url to send request based on API version
        if not self._base_url:
            self._base_url = urlparse.urljoin(
                self._url, rest_target_broker.API_PREFIX)
        if url.startswith("/"):
            url = url[1:]
        url_request = urlparse.urljoin(self._base_url, url)
        logger.debug("send_request: %s %s", method, url_request)
        with self.lock:
            cookies = self.cookies
        session = tls_var("session", requests.Session)
        if method == 'GET':
            r = session.get(url_request, cookies = cookies,
                            data = data, verify = self.verify_ssl,
                            stream = stream, timeout = timeout)
        elif method == 'POST':
            r = session.post(url_request, cookies = cookies,
                             data = data, files = files,
                             verify = self.verify_ssl,
                             stream = stream, timeout = timeout)
        elif method == 'PUT':
            r = session.put(url_request, cookies = cookies,
                            data = data, verify = self.verify_ssl,
                            stream = stream, timeout = timeout)
        elif method == 'DELETE':
            r = session.delete(url_request, cookies = cookies,
                               data = data, verify = self.verify_ssl,
                               stream = stream, timeout = timeout)
        else:
            raise Exception("Unknown method '%s'" % method)

        #update cookies
        if len(r.cookies) > 0:
            with self.lock:
                # Need to update like this because r.cookies is not
                # really a dict, but supports iteritems() -- overwrite
                # existing cookies (session cookie) and keep old, as
                # it will have the stuff we need to auth with the
                # server (like the remember_token)
                # FIXME: maybe filter to those two only?
                for cookie, value in r.cookies.iteritems():
                    self.cookies[cookie] = value
        commonl.request_response_maybe_raise(r)
        if raw:
            return r
        rdata = r.json()
        diagnostics = rdata.get('diagnostics', "").encode("utf-8", 'replace')
        if diagnostics != "":
            for line in diagnostics.split("\n"):
                logger.warning("diagnostics: " + line)
        return rdata

    def login(self, email, password):
        data = {"email": email, "password": password}
        try:
            self.send_request('PUT', "login", data)
        except requests.exceptions.HTTPError as e:
            if e.status_code == 404:
                logger.error("%s: login failed: %s", self._url, e)
            return False
        return True

    def logout(self):
        self.send_request('GET', "logout")

    def validate_session(self, validate = False):
        if self.valid_session is None or validate:
            valid_session = False
            r = None
            try:
                r = self.send_request('GET', "validate_session")
                if 'status' in r and r['status'] == "You have a valid session":
                    valid_session = True
            except requests.exceptions.HTTPError:
                # Invalid session
                pass
            finally:
                with self.lock:
                    self.valid_session = valid_session
        return valid_session

    def rest_tb_target_list(self, all_targets = False, target_id = None):
        """
        List targets in this server

        :param bool all_targets: If True, include also targets that are marked
          as disabled.
        :param str target_id: Only get information for said target id
        """
        if target_id:
            r = self.send_request("GET", "targets/" + target_id)
        else:
            r = self.send_request("GET", "targets/")
        _targets = []
        for rt in r['targets']:
            # Skip disabled targets
            if target_id != None and rt.get('disabled', False) == True \
               and all_targets != True:
                continue
            rt['fullid'] = self.aka + "/" + rt['id']
            # FIXME: hack, we need this for _rest_target_find_by_id,
            # we need to change where we store it in this cache
            rt['rtb'] = self
            _targets.append(rt)
        del r
        return _targets

    def rest_tb_target_update(self, target_id):
        """
        Update information about a target

        :param str target_id: ID of the target to operate on
        :returns: updated target tags
        """
        fullid = self.aka + "/" + target_id
        r = self.rest_tb_target_list(target_id = target_id, all_targets = True)
        if r:
            rtd = self._rt_list_to_dict(r)
            # Update the cache
            type(self)._rts_cache.update(rtd)
            return rtd[fullid]
        else:
            raise ValueError("%s/%s: unknown target" % (self.aka, target_id))

    def rest_tb_target_acquire(self, rt, ticket = '', force = False):
        return self.send_request("PUT", "targets/%s/acquire" % rt['id'],
                                 data = { 'ticket': ticket, 'force': force })

    def rest_tb_target_active(self, rt, ticket = ''):
        self.send_request("PUT", "targets/%s/active" % rt['id'],
                          data = { 'ticket': ticket })

    def rest_tb_target_enable(self, rt, ticket = ''):
        data = { 'ticket': ticket }
        return self.send_request("PUT", "targets/%s/enable" % rt['id'], data)

    def rest_tb_target_disable(self, rt, ticket = ''):
        data = { 'ticket': ticket }
        return self.send_request("PUT", "targets/%s/disable" % rt['id'], data)

    def rest_tb_target_release(self, rt, ticket = '', force = False):
        self.send_request(
            "PUT", "targets/%s/release" % rt['id'],
            data = { 'force': force, 'ticket': ticket })

    def rest_tb_property_set(self, rt, prop, value, ticket = ''):
        self.send_request(
            "PUT", "targets/%s/property_set" % rt['id'],
            data = {
                'ticket': ticket,
                'property': prop,
                'value': value
            })

    def rest_tb_property_get(self, rt, prop, ticket = ''):
        r = self.send_request(
            "PUT", "targets/%s/property_get" % rt['id'],
            data = {
                'ticket': ticket,
                'property': prop
            })
        return r['value']


    # COMPAT
    def rest_tb_target_power_on(self, rt, ticket = ''):
        self.send_request(
            "PUT", "targets/%s/power_on" % rt['id'],
            data = { 'ticket': ticket })

    def rest_tb_target_power_off(self, rt, ticket = ''):
        self.send_request(
            "PUT", "targets/%s/power_off" % rt['id'],
            data = { 'ticket': ticket })

    def rest_tb_target_reset(self, rt, ticket = ''):
        self.send_request(
            "PUT", "targets/%s/reset" % rt['id'],
            data = { 'ticket': ticket })

    def rest_tb_target_power_cycle(self, rt, ticket = '', wait = None):
        data = { 'ticket': ticket }
        if wait != None:
            data['wait'] = "%f" % wait
        self.send_request("PUT", "targets/%s/power_cycle" % rt['id'],
                          data = data)

    def rest_tb_target_power_get(self, rt):
        r = self.send_request(
            "GET", "targets/%s/power_get" % rt['id'])
        return r['powered']

    def rest_tb_file_upload(self, remote_filename, local_filename):
        with open(local_filename, 'rb') as f:
            self.send_request(
                "POST", "files/" + remote_filename,
                files = { 'file': f })

    def rest_tb_file_dnload(self, remote_filename, local_filename):
        """
        Download a remote file from the broker to a local file

        :param str remote_filename: filename in the broker's user
          storage area
        :params str local_filename: local filename where to download it
        """
        with open(local_filename, "w") as lf:
            self.rest_tb_file_dnload_to_fd(lf.fileno(), remote_filename)

    def rest_tb_file_dnload_to_fd(self, fd, remote_filename):
        """
        Download a remote file from the broker to a local file

        :param str remote_filename: filename in the broker's user
          storage area
        :params int fd: file descriptor where to write the data to
        """
        url = "files/%s" % remote_filename
        with contextlib.closing(self.send_request("GET", url, data = {},
                                                  stream = True,
                                                  raw = True)) as r:
            # http://docs.python-requests.org/en/master/user/quickstart/#response-content
            chunk_size = 1024
            total = 0
            for chunk in r.iter_content(chunk_size):
                os.write(fd, chunk)
                total += len(chunk)
            return total

    def rest_tb_file_delete(self, remote_filename):
        self.send_request("DELETE", url = "files/" + remote_filename,
                          data = {})

    def rest_tb_file_list(self):
        """
        Return a dictionary of files names available to the user in the
        broker and their sha256 hash.
        """
        return self.send_request("GET", "files/")

    def rest_tb_target_console_read(self, rt, console, offset, ticket = ''):
        url = "targets/%s/console/" % rt['id']
        data = {
            'offset': offset,
        }
        if console:
            data['console'] = console
        if ticket != '':
            data['ticket'] = ticket
        return self.send_request("GET", url, data = data,
                                 stream = False, raw = True)

    def rest_tb_target_console_size(self, rt, console, ticket = ''):
        r = self.send_request(
            'GET', "targets/%s/console_size" % rt['id'],
            data = {
                'console': console,
                'ticket': ticket
            }
        )
        return r['byte_count']

    def rest_tb_target_console_read_to_fd(self, fd, rt, console, offset,
                                          max_size = 0, ticket = ''):
        url = "targets/%s/console/" % rt['id']
        data = {
            'offset': offset,
        }
        if console:
            data['console'] = console
        if ticket != '':
            data['ticket'] = ticket
        with contextlib.closing(self.send_request("GET", url, data = data,
                                                  stream = True,
                                                  raw = True)) as r:
            # http://docs.python-requests.org/en/master/user/quickstart/#response-content
            chunk_size = 1024
            total = 0
            for chunk in r.iter_content(chunk_size):
                os.write(fd, chunk)
                # don't use chunk_size, as it might be less
                total += len(chunk)
                if max_size > 0 and total >= max_size:
                    break
            return total

    def rest_tb_target_console_write(self, rt, console, data, ticket = ''):
        url = "targets/%s/console/" % rt['id']
        # gosh this naming sucks...
        _data = dict(data = data)
        if console:
            _data['console'] = console
        if ticket != '':
            _data['ticket'] = ticket
        return self.send_request('POST', url, data = _data)


def rest_init(path, url, ignore_ssl = False, aka = None):
    """
    Initialize access to a remote target broker.

    :param state_path: Path prefix where to load state from
    :type state_path: str
    :param url: URL for which we are loading state
    :type url: str
    :returns: True if information was loaded for the URL, False otherwise
    """
    rtb = rest_target_broker(path, url, ignore_ssl, aka)
    rest_target_brokers[url] = rtb
    return rtb

def rest_shutdown(path):
    """
    Shutdown REST API, saving state in *path*.

    :param path: Path to where to save state information
    :type path: str
    """
    for rtb in rest_target_brokers.itervalues():
        rtb.tb_state_save(path)


def _credentials_get(domain, aka, args):
    # env general
    user_env = os.environ.get("TCF_USER", None)
    password_env = os.environ.get("TCF_PASSWORD", None)
    # server specific
    user_env_aka = os.environ.get("TCF_USER_" + aka, None)
    password_env_aka = os.environ.get("TCF_PASSWORD_" + aka, None)

    # from commandline
    user_cmdline = args.user
    password_cmdline = args.password

    # default to what came from environment
    user = user_env
    password = password_env
    # override with server specific from envrionment
    if user_env_aka:
        user = user_env_aka
    if password_env_aka:
        password = password_env_aka
    # override with what came from the command line
    if user_cmdline:
        user = user_cmdline
    if password_cmdline:
        password = password_cmdline

    if not user:
        if args.quiet:
            raise RuntimeError(
                "Cannot obtain login name and"
                " -q was given (can't ask); "
                " please specify a login name or use environment"
                " TCF_USER[_AKA]")
        if not sys.stdout.isatty():
            raise RuntimeError(
                "Cannot obtain login name and"
                " terminal is not a TTY (can't ask); "
                " please specify a login name or use environment"
                " TCF_USER[_AKA]")
        user = raw_input('Login for %s [%s]: ' \
                         % (domain, getpass.getuser()))
        if user == "":	# default to LOGIN name
            user = getpass.getuser()
            print "I: defaulting to login name %s (login name)" % user

    if not password:
        if args.quiet:
            raise RuntimeError(
                "Cannot obtain password and"
                " -q was given (can't ask); "
                " please specify a login name or use environment"
                " TCF_PASSWORD[_AKA]")
        if not sys.stdout.isatty():
            raise RuntimeError(
                "Cannot obtain password and"
                " terminal is not a TTY (can't ask); "
                " please specify a login name or use environment"
                " TCF_PASSWORD[_AKA]")
        password = getpass.getpass("Password for %s at %s: " % (user, domain))
    return user, password

def rest_login(args):
    """
    Login into remote servers.

    :param argparse.Namespace args: login arguments like -q (quiet) or
      userid.
    :returns: True if it can be logged into at least 1 remote server.
    """
    logged = False
    if not args.split and sys.stdout.isatty() and not args.quiet:
        if args.user == None:
            args.user = raw_input('Login [%s]: ' % getpass.getuser())
        if args.password in ( "ask", None):
            args.password = getpass.getpass("Password: ")
    for rtb in rest_target_brokers.itervalues():
        logger.info("%s: checking for a valid session", rtb._url)
        if not rtb.valid_session:
            user, password = _credentials_get(rtb._url, rtb.aka, args)
            try:
                if rtb.login(user, password):
                    logged = True
                else:
                    logger.error("%s (%s): cannot login: with given "
                                 "credentials %s", rtb._url, rtb.aka, user)
            except Exception as e:
                logger.error("%s (%s): cannot login: %s",
                             rtb._url, rtb.aka, e)
        else:
            logged = True
    if not logged:
        logger.error("Could not login to any server, "
                     "please check your config")
        exit(1)

def rest_logout(args):
    for rtb in rest_target_brokers.itervalues():
        logger.info("%s: checking for a valid session", rtb._url)
        rtb.tb_state_trash()
        if rtb.valid_session:
            rtb.logout()

def _power_get(rt):
    if 'powered' in rt:
        return rt['powered'] == True
    else:
        return None

def rest_target_print(rt, verbosity = 0):
    """
    Print information about a REST target taking into account the
    verbosity level from the logging module

    :param rt: object describing the REST target to print
    :type rt: dict

    """
    if verbosity == 0:
        print "%(fullid)s" % rt
    elif verbosity == 1:
        # Simple list, just show owner and power state
        _power = _power_get(rt)
        if _power == True:
            power = " ON"
        elif _power == False:
            power = " OFF"
        else:				# no power control
            power = ""
        if rt['owner'] != None:
            owner = "[" + rt['owner'] + "]"
        else:
            owner = ""
        print "%s %s%s" % (rt['fullid'], owner, power)
    elif verbosity == 2:
        print rt['fullid']
        commonl._dict_print_dotted(rt, "  ")
    elif verbosity == 3:
        pprint.pprint(rt)
    else:
        print json.dumps(rt, skipkeys = True, indent = 4)

def _rest_target_find_by_id(_target):
    """
    Find a target by ID.

    Ignores if the target is disabled or enabled.

    :param str target: Target to locate; it can be a *name* or a full *url*.
    """
    # Try to see if it is cached by that ID
    rt = rest_target_broker.rts_cache.get(_target, None)
    if rt != None:
        return rt['rtb'], rt
    # Dirty messy search
    for rt in rest_target_broker.rts_cache.itervalues():
        if rt['id'] == _target:
            return rt['rtb'], rt
    raise IndexError("target-id '%s': not found" % _target)

def _rest_target_broker_find_by_id_url(target):
    # Note this function finds by ID and does nt care if the target is
    # disabled or enabled
    if target in rest_target_brokers:
        return rest_target_brokers[target]
    rtb, _rt = _rest_target_find_by_id(target)
    return rtb


def _target_select_by_spec( rt, spec, _kws = None):
    if not _kws:
        _kws = {}
    origin = "cmdline"
    # FIXME: merge with tcfl.tc.t_c._targets_select_by_spec()
    # We are going to modify the _kws dict, so make a copy!
    kws = dict(_kws)
    # We don't consider BSP models, just iterate over all the BSPs
    bsps = rt.get('bsps', {}).keys()
    kws['bsp_count'] = len(bsps)
    kws_bsp = dict()
    commonl.kws_update_from_rt(kws, rt)
    rt_full_id = rt['fullid']
    rt_type = rt.get('type', 'n/a')

    for bsp in bsps:
        kws_bsp.clear()
        kws_bsp.update(kws)
        kws_bsp['bsp'] = bsp
        commonl.kws_update_type_string(kws_bsp, rt['bsps'][bsp])
        logger.info("%s/%s (type:%s): considering by spec",
                    rt_full_id, bsp, rt_type)
        if commonl.conditional_eval("target selection", kws_bsp,
                                    spec, origin, kind = "specification"):
            # This remote target matches the specification for
            # this target want
            logger.info("%s/%s (type:%s): candidate by spec",
                        rt_full_id, bsp, rt_type)
            return True
        else:
            logger.info(
                "%s/%s (type:%s): ignoring by spec; didn't match '%s'",
                rt_full_id, bsp, rt_type, spec)
    if bsps == []:
        # If there are no BSPs, just match on the core keywords
        if commonl.conditional_eval("target selection", kws,
                                    spec, origin, kind = "specification"):
            # This remote target matches the specification for
            # this target want
            logger.info("%s (type:%s): candidate by spec w/o BSP",
                        rt_full_id, rt_type)
            return True
        else:
            logger.info("%s (type:%s): ignoring by spec w/o BSP; "
                        "didn't match '%s'", rt_full_id, rt_type, spec)
            return False



def rest_target_list_table(args, spec):
    """
    List all the targets in a table format, appending * if powered
    up, ! if owned.
    """

    # Collect the targets into a list of tuples (FULLID, SUFFIX),
    # where suffix will be *! (* if powered, ! if owned)

    l = []
    for rt_fullid, rt in sorted(rest_target_broker.rts_cache.iteritems(),
                                key = lambda x: x[0]):
        try:
            if spec and not _target_select_by_spec(rt, spec):
                continue
            suffix = ""
            if rt['owner']:
                suffix += "@"
            _power = _power_get(rt)
            if _power == True:
                suffix += "!"
            l.append((rt_fullid, suffix))
        except requests.exceptions.ConnectionError as e:
            logger.error("%s: can't use: %s", rt_fullid, e)
    if not l:
        return

    # Figure out the max target name length, so from there we can see
    # how many entries we can fit per column. Note that the suffix is
    # max two characters, separated from the target name with a
    # space and we must leave another space for the next column (hence
    # +4).
    _h, display_w, _hp, _wp = struct.unpack(
        'HHHH', fcntl.ioctl(0, termios.TIOCGWINSZ,
                            struct.pack('HHHH', 0, 0, 0, 0)))

    maxlen = max([len(i[0]) for i in l])
    columns = int(math.floor(display_w / (maxlen + 4)))
    if columns < 1:
        columns = 1
    rows = int((len(l) + columns - 1) / columns)

    # Print'em sorted; filling out columns first -- there might be a
    # more elegant way to do it, but this one is quite simple and I am
    # running on fumes sleep-wise...
    l = sorted(l)
    for row in range(rows):
        for column in range(columns):
            index = rows * column + row
            if index >= len(l):
                break
            i = l[index]
            sys.stdout.write(u"{fullid:{column_width}} {suffix:2} ".format(
                fullid = i[0], suffix = i[1], column_width = maxlen))
        sys.stdout.write("\n")

def rest_target_list(args):
    specs = []
    # Bring in disabled targets? (note the field is a text, not a bool)
    if args.all == False:
        specs.append("( disabled != 'True' )")
    # Bring in target specification from the command line (if any)
    if args.target:
        specs.append("(" + ") or (".join(args.target) +  ")")
    spec = " and ".join(specs)

    if args.verbosity < 1 and sys.stderr.isatty() and sys.stdout.isatty():
        rest_target_list_table(args, spec)
        return
    else:
        l = []
        for rt_fullid, rt in sorted(rest_target_broker.rts_cache.iteritems(),
                                    key = lambda x: x[0]):
            rt.pop('rtb')	# can't json this
            try:
                if spec and not _target_select_by_spec(rt, spec):
                    continue
                l.append(rt)
            except requests.exceptions.ConnectionError as e:
                logger.error("%s: can't use: %s", rt_fullid, e)

        if  args.verbosity == 4:
            # print as a JSON dump
            print json.dumps(l, skipkeys = True, indent = 4)
        else:
            for rt in l:
                rest_target_print(rt, args.verbosity)


def rest_target_find_all(all_targets = False):
    """
    Return descriptors for all the known remote targets

    :param bool all_targets: Include or not disabled targets
    :returns: list of remote target descriptors (each being a dictionary).
    """
    if all_targets == True:
        return list(rest_target_broker.rts_cache.values())
    targets = []
    for rt in rest_target_broker.rts_cache.values():
        if rt.get('disabled', 'False') in ('True', True):
            continue
        targets.append(rt)
    return targets

def rest_target_acquire(args):
    """
    :param argparse.Namespace args: object containing the processed
      command line arguments; need args.target
    :returns: dictionary of tags
    :raises: IndexError if target not found
    """
    for target in args.target:
        rtb, rt = _rest_target_find_by_id(target)
        rtb.rest_tb_target_acquire(
            rt, ticket = args.ticket, force = args.force)

def rest_target_enable(args):
    """
    :param argparse.Namespace args: object containing the processed
      command line arguments; need args.target
    :raises: IndexError if target not found
    """
    for target in args.target:
        rtb, rt = _rest_target_find_by_id(target)
        rtb.rest_tb_target_enable(rt, ticket = args.ticket)

def rest_target_disable(args):
    """
    :param argparse.Namespace args: object containing the processed
      command line arguments; need args.target
    :raises: IndexError if target not found
    """
    for target in args.target:
        rtb, rt = _rest_target_find_by_id(target)
        rtb.rest_tb_target_disable(rt, ticket = args.ticket)

def rest_target_property_set(args):
    """
    :param argparse.Namespace args: object containing the processed
      command line arguments; need args.target
    :raises: IndexError if target not found
    """
    rtb, rt = _rest_target_find_by_id(args.target)
    rtb.rest_tb_property_set(rt, args.property, args.value,
                             ticket = args.ticket)

def rest_target_property_get(args):
    """
    :param argparse.Namespace args: object containing the processed
      command line arguments; need args.target
    :raises: IndexError if target not found
    """
    rtb, rt = _rest_target_find_by_id(args.target)
    value = rtb.rest_tb_property_get(rt, args.property, ticket = args.ticket)
    if value != None:
        print value

def rest_target_release(args):
    """
    :param argparse.Namespace args: object containing the processed
      command line arguments; need args.target
    :raises: IndexError if target not found
    """
    for target in args.target:
        rtb, rt = _rest_target_find_by_id(target)
        rtb.rest_tb_target_release(rt, force = args.force,
                                   ticket = args.ticket)

def rest_target_images_set(args):
    """
    :param argparse.Namespace args: object containing the processed
      command line arguments; need args.target
    :raises: IndexError if target not found
    """
    rtb, rt = _rest_target_find_by_id(args.target)
    images = dict((image_spec.split(":", 1)) for image_spec in args.images)
    return rtb.rest_tb_target_images_set(rt, images, ticket = args.ticket)

def rest_tb_target_images_upload(rtb, _images):	# COMPAT
    """
    Upload images from a list images

    :param dict rtb: Remote Target Broker
    :param _images: list of images, which can be specified as:

      - string with ``"IMAGE1:FILE1 IMAGE2:FILE2..."``
      - list or set of strings ``["IMAGE1:FILE1", "IMAGE2:FILE2", ...]``
      - list or set of tuples ``[("IMAGE1", "FILE1"), ("IMAGE2", "FILE2"), ...]``

    :returns: list of remote images (that can be fed straight to
      :meth:`tcfl.ttb_client.rest_target_broker.rest_tb_target_images_set`)

    """
    images = []
    if isinstance(_images, basestring):
        for image_spec in _images:
            try:
                t, f = image_spec.split(":", 1)
                images.append((t, f))
            except ValueError as _e:
                raise ValueError("Bad image specification `%s` "
                                 "(expecting TYPE:FILE)" % image_spec)
    elif isinstance(_images, set) or isinstance(_images, list):
        for image_spec in _images:
            if isinstance(image_spec, basestring):
                t, f = image_spec.split(":", 1)
                images.append((t, f))
            elif isinstance(image_spec, tuple) and len(image_spec) == 2:
                images.append(image_spec)
            else:
                raise TypeError("Invalid image specification %s" % image_spec)
    else:
        raise TypeError("_images is type %s" % type(_images).__name__)

    remote_images = {}
    for image_type, local_filename in images:
        logger.info("%s: uploading %s", rtb._url, local_filename)
        digest = commonl.hash_file(hashlib.sha256(), local_filename)\
                        .hexdigest()[:10]
        remote_filename = commonl.file_name_make_safe(
            os.path.abspath(local_filename)) + "-" + digest
        rtb.rest_tb_file_upload(remote_filename, local_filename)
        remote_images[image_type] = remote_filename

    return remote_images
