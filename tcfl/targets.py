#! /usr/bin/env python3
#
# Copyright (c) 2022 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

"""
Target handling utilities
-------------------------

Initialize the simple way to do it (synchronous):

>>> import tcfl.targets
>>> tcfl.targets.subsystem_setup()

(this takes care of initializing its dependencies, the server
subsystem and the configuration subsystem).

An asynchronous way to initialize this module:

1. Initialize dependencies:

   >>> import tcfl.servers
   >>> tcfl.servers.subsystem_setup()      # initializes configuration

2. Create a discovery agent

   >>> import tcfl.targets
   >>> discovery_agent = discovery_agent_c()

3. Start the discovery in the background:

   >>> discovery_agent.update_start()      # starts in background
   >>> ... do something else...

4. Wait for the discovery to complete:

   >>> discovery_agent.update_complete(update_globals = True)

"""
# FIXME:
#
# - needs to support a proper aync Python API
# - the discovery_agent_c object shall be able to take servers from a
#   tcfl.server.discover_agent_c object (pending)

import bisect
import collections
import concurrent.futures
import logging

import tcfl
import tcfl.servers

keys_from_inventory = collections.defaultdict(set)
target_inventory = None

logger = logging.getLogger("targets")


class discovery_agent_c:
    """
    Discover targers in a remote server and cache them

    :param list(str) projections: (optional; default all) list of
      fields to load

      Depending on the operation that is to be performed, not all
      fields might be needed and depending on network conditions
      and how many remote targets are available and how much data
      is in their inventory, this can considerably speed up
      operation.

      For example, to only list the target names:

      >>> discovery_agent = tcfl.targets.discover_agent_c(projections = [ 'id' ])
      >>> discovery_agent.update_start()
      >>> discovery_agent.update_complete()

      Only targets that have the field defined will be fetched
      (PENDING: prefix field name with a period `.` will gather
      all targets irrespective of that field being defined or
      not).

    """

    def __init__(self, projections = None):


        #: Remote target inventory (cached)
        self.rts = dict()

        #: Remote target inventory in deep and flat format
        self.rts_flat = dict()

        #: Sorted list of remote target full IDs (SERVER/NAME)
        #:
        #: This is used for iteration algorithms so we can reproduce the
        #: iterations if wished without needing to resort all the time.
        self.rts_fullid_sorted = list()
        self.rts_fullid_disabled = set()
        self.rts_fullid_enabled = set()

        self.projections = projections

        self.executor = None
        self.rs = {}



    def _cache_rt_handle(self, fullid, rt):
        # Given a new remote target descriptor rt, insert/update into
        # the local tables indexed by fullif
        #
        # this accesses the *rts* data without locks, to
        # be executed sequential only
        position = bisect.bisect_left(self.rts_fullid_sorted, fullid)
        if not self.rts_fullid_sorted or self.rts_fullid_sorted[-1] != fullid:
            self.rts_fullid_sorted.insert(position, fullid)
        if rt.get('disabled', None):
            self.rts_fullid_disabled.add(fullid)
            self.rts_fullid_enabled.discard(fullid)
        else:
            self.rts_fullid_disabled.discard(fullid)
            self.rts_fullid_enabled.add(fullid)



    def update_start(self):
        """
        Starts the asynchronous process of updating the target information
        """
        logger.info("caching target information")
        self.rts.clear()
        self.rts_flat.clear()
        self.rts_fullid_sorted.clear()
        # load all the servers at the same time using a thread pool
        if not tcfl.server_c.servers:
            logger.info("found no servers, will find no targets")
            return
        if self.executor or self.rs:	# already started
            return
        logger.info("")
        self.executor = concurrent.futures.ThreadPoolExecutor(len(tcfl.server_c.servers))
        self.rs = self.executor.map(
            lambda server: server.targets_get(projections = self.projections),
            tcfl.server_c.servers.values())
        logger.error("server inventory update started")



    def update_complete(self, update_globals = False):
        """
        Waits for the target update process to finish
        """
        for server_rts, server_rts_flat in self.rs:
            #server_rts, server_rts_flat = self.rs.get()
            # do this here to avoid multithreading issues; only one
            # thread updating the sorted list
            for fullid, rt in server_rts.items():
                self._cache_rt_handle(fullid, rt)
            self.rts.update(server_rts)
            self.rts_flat.update(server_rts_flat)
        logger.info(f"read {len(self.rts)} targets"
                    f" from {len(tcfl.server_c.servers)} servers found")
        self.executor = None
        self.rs = {}

        if update_globals:
            tcfl.rts = self.rts
            tcfl.rts_flat = self.rts_flat

            tcfl.rts_fullid_sorted = self.rts_fullid_sorted
            tcfl.rts_fullid_disabled = self.rts_fullid_disabled
            tcfl.rts_fullid_enabled = self.rts_fullid_enabled


#: Global targets discovery agent, containing the list of discovered targets
#:
#: The list of target full names (*SERVER/TARGETID*):
#:
#: >>> tcfl.targets.discovery_agent.rts_fullid_sorted
#: >>> tcfl.targets.discovery_agent.rts_fullid_disabled
#: >>> tcfl.targets.discovery_agent.rts_fullid_enabled
#:
#: For example, the target data for each target in dictionary format:
#:
#: >>> tcfl.targets.discovery_agent.rts
#:
#: For example, the target data for each target in dictionary format,
#: but also flattened (*a[b]* would look like *a.b*):
#
#: >>> tcfl.targets.discovery_agent.rts_flat
#:
#: Note this gets initializd by tcfl.targets.subsystem_setup()
discovery_agent = None


_subsystem_setup = False



def subsystem_setup(*args, projections = None, **kwargs):
    """
    Initialize the target discovery subsystem in a synchronous way

    Check the module documentation for an asynchronous one.

    Same arguments as:

    - :class:`tcfl.targets.discovery_agent_c`

      Note using *projections* for anything else than just listing
      will limit the amount of information that is loaded from servers
      during the instance lifecycle.

    - :func:`tcfl.config.subsystem_setup`

    Note this initialize all the required dependencies
    (:mod:`tcfl.config` and :mod:`tcfl.servers )` if not already
    initialized).

    """
    # ensure discovery subsystem is setup
    global _subsystem_setup
    if _subsystem_setup:
        return

    tcfl.servers.subsystem_setup()

    # FIXME: move server discovery here, since it is a requirement
    # tcfl.server.discover()

    # discover targets
    global discovery_agent
    discovery_agent = discovery_agent_c(*args, projections = projections, **kwargs)
    discovery_agent.update_start()
    discovery_agent.update_complete(update_globals = True)

    _subsystem_setup = True
