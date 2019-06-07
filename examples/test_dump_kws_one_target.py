#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
import pprint
import tcfl.tc

@tcfl.tc.target()
@tcfl.tc.tags(build_only = True, ignore_example = True)
class _print_kws(tcfl.tc.tc_c):
    """
    Dump the keywords that are available to this testcase while
    running on a target.

    Notice the test group values are slightly different between the
    multiple targets, the single target or no targets (static) cases.
    """
    def build(self, target):
        self.report_info("Keywords for testcase:\n%s"
                         % pprint.pformat(self.kws),
                         level = 0)
        target.report_info("Keywords for target 0:\n%s"
                           % pprint.pformat(target.kws),
                           level = 0)
