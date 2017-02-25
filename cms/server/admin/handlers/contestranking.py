#!/usr/bin/env python2
# -*- coding: utf-8 -*-

# Contest Management System - http://cms-dev.github.io/
# Copyright © 2010-2013 Giovanni Mascellani <mascellani@poisson.phc.unipi.it>
# Copyright © 2010-2015 Stefano Maggiolo <s.maggiolo@gmail.com>
# Copyright © 2010-2012 Matteo Boscariol <boscarim@hotmail.com>
# Copyright © 2012-2014 Luca Wehrstedt <luca.wehrstedt@gmail.com>
# Copyright © 2014 Artem Iglikov <artem.iglikov@gmail.com>
# Copyright © 2014 Fabian Gundlach <320pointsguy@gmail.com>
# Copyright © 2015 William Di Luigi <williamdiluigi@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Ranking-related handlers for AWS for a specific contest.

"""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

import csv
import io
import sys
import json

from sqlalchemy.orm import joinedload

from cms.db import Contest
from cms.db import SubmissionResult
from cms.grading import task_score, task_scored_submission, scoretypes
from cms.grading.ScoreType import ScoreTypeGroup

from .base import BaseHandler, require_permission


class RankingHandler(BaseHandler):
    """Shows the ranking for a contest.

    """
    @require_permission(BaseHandler.AUTHENTICATED)
    def get(self, contest_id, format="online"):
        # This validates the contest id.
        self.safe_get_item(Contest, contest_id)

        # This massive joined load gets all the information which we will need
        # to generating the rankings.
        self.contest = self.sql_session.query(Contest)\
            .filter(Contest.id == contest_id)\
            .options(joinedload('participations'))\
            .options(joinedload('participations.submissions'))\
            .options(joinedload('participations.submissions.token'))\
            .options(joinedload('participations.submissions.results'))\
            .first()

        self.r_params = self.render_params()
        show_teams = any(map(lambda participation: participation.team_id,
                             self.contest.participations))
        self.r_params["show_teams"] = show_teams
        if format == "txt":
            self.set_header("Content-Type", "text/plain")
            self.set_header("Content-Disposition",
                            "attachment; filename=\"ranking.txt\"")
            self.render("ranking.txt", **self.r_params)
        elif format == "csv":
            self.set_header("Content-Type", "text/csv")
            self.set_header("Content-Disposition",
                            "attachment; filename=\"ranking.csv\"")

            if sys.version_info >= (3, 0):
                output = io.StringIO()  # untested
            else:
                # In python2 we must use this because its csv module does not
                # support unicode input
                output = io.BytesIO()
            writer = csv.writer(output)

            include_partial = True

            contest = self.r_params["contest"]

            row = ["Username", "User"]
            if show_teams:
                row.append("Team")
            for task in contest.tasks:
                row.append(task.name)
                if include_partial:
                    row.append("P")

            row.append("Global")
            if include_partial:
                row.append("P")

            writer.writerow(row)

            for p in sorted(contest.participations,
                            key=lambda p: p.user.username):
                if p.hidden:
                    continue

                score = 0.0
                partial = False

                row = [p.user.username,
                       "%s %s" % (p.user.first_name, p.user.last_name)]
                if show_teams:
                    row.append(p.team.name if p.team else "")
                for task in contest.tasks:
                    t_score, t_partial = task_score(p, task)
                    t_score = round(t_score, task.score_precision)
                    score += t_score
                    partial = partial or t_partial

                    row.append(t_score)
                    if include_partial:
                        row.append("*" if t_partial else "")

                row.append(round(score, contest.score_precision))
                if include_partial:
                    row.append("*" if partial else "")

                if sys.version_info >= (3, 0):
                    writer.writerow(row)  # untested
                else:
                    writer.writerow([unicode(s).encode("utf-8") for s in row])

            self.finish(output.getvalue())
        else:
            self.render("ranking.html", **self.r_params)


class DetailedResultsHandler(BaseHandler):
    """Show detailed results for printing.

    """
    @staticmethod
    def __get_result(text):
        # TODO: use translation files when AWS supports them
        text = json.loads(text)[0]
        messages = {
            "Output is correct": u"Pareizi",
            "Output is partially correct": u"Daļēji pareizi",
            "Output isn't correct": u"Nepareizi",
            "Evaluation didn't produce file %s": u"Trūkst izvaddatu",
            "Execution timed out": u"Laika limits",
            "Execution timed out (wall clock limit exceeded)": u"Laika limits",
            "Execution killed with signal %d (could be triggered by "
            "violating memory limits)": "Izpildes kļūda",
            "Execution killed because of forbidden syscall %s":
                "Neatļauta darbība",
            "Execution killed because of forbidden file access":
                "Neatļauta piekļuve failiem",
            "Execution failed because the return code was nonzero":
                "Izpildes kļūda"
         }
        if text in messages:
            return messages[text]
        return text

    @staticmethod
    def __format_score(score, max_score, precision):
        format_str = "{{:.{0}f}}/{{:.{0}f}}".format(precision)
        return format_str.format(score, max_score)

    @require_permission(BaseHandler.AUTHENTICATED)
    def get(self, contest_id):
        # This validates the contest id.
        self.safe_get_item(Contest, contest_id)

        # This massive joined load gets all the information which we will need
        # to generating the rankings.
        contest = self.sql_session.query(Contest) \
            .filter(Contest.id == contest_id) \
            .options(joinedload('participations')) \
            .options(joinedload('participations.submissions')) \
            .options(joinedload('participations.submissions.token')) \
            .options(joinedload('participations.submissions.results')) \
            .first()

        r_params = {
            'contest': contest,
            'format_score': DetailedResultsHandler.__format_score
        }
        partial_results = False
        results = []

        max_score = 0
        for task in contest.tasks:
            dataset = task.active_dataset
            scoretype = scoretypes.get_score_type(dataset=dataset)
            max_score += scoretype.max_score

        # TODO: decide how to deal with collation
        for p in sorted(contest.participations,
                        key=lambda p: (p.user.last_name, p.user.first_name)):

            if p.hidden:
                continue

            result = {
                'participation': p,
                'max_score': max_score
            }
            total_score = 0
            task_results = []
            for task in contest.tasks:
                score, partial, submission = task_scored_submission(p, task)
                if partial:
                    partial_results = True
                score = round(score, task.score_precision)
                st = scoretypes.get_score_type(dataset=task.active_dataset)
                if not isinstance(st, ScoreTypeGroup):
                    raise Exception("Unsupported score type for task {0}"
                                    .format(task.name))

                task_max_score = st.max_score
                total_score += score

                test_results = []
                if submission:
                    sr = submission.get_result(task.active_dataset)
                    if sr:
                        status = sr.get_status()
                    else:
                        status = SubmissionResult.COMPILING

                    if status == SubmissionResult.SCORED:
                        test_results = json.loads(sr.score_details)
                        for group in test_results:
                            for testcase in group['testcases']:
                                testcase['text'] = DetailedResultsHandler\
                                        .__get_result(testcase['text'])
                elif score == 0.0:  # skip tasks with no submissions and score
                    continue

                task_result = {
                    'task': task,
                    'name': task.name,
                    'score': score,
                    'max_score': task_max_score,
                    'status': status,
                    'test_results': test_results
                }

                task_results.append(task_result)
            result['total_score'] = total_score
            result['tasks'] = task_results

            results.append(result)

        r_params['results'] = results
        r_params['partial_results'] = partial_results

        self.set_header('Content-Type', 'text/html')
        self.set_header('Content-Disposition',
                        'attachment; filename="detailed_results.html"')
        self.render('detailed_results.html', **r_params)
